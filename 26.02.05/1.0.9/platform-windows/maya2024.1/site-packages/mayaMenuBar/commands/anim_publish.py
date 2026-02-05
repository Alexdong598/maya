# -*- coding: utf-8 -*-
"""
Animation publishing tool with Qt UI for Maya.

- 几何/ABC/OBJ + Skeleton(USD/FBX)
- USD 导出支持 strip namespaces（无 temp group / 无 post-rename）
- WithShader 工作流（非扁平，父-子包含式）：
  1) 从 shader.usd(c) 收集所有 Mesh prim 路径
  2) 生成 zeroXform.usdc（**只改 xform**：reset 到 identity/zero；可选 embed shader 到 zeroXform，默认开启）
     * 对 Mesh 的祖先先 Override 占位，避免被更强层清空
  3) 组装最终 withShader.usdc（父层，仅挂子层）：
       withShader.usdc
         ├─ anim.usdc   [强]
         └─ zeroXform.usdc [弱]  （zero 内是否 embed shader 由步骤 2 决定）
  4) 只在 withShader 顶层写 subdivisionScheme='catmullClark'（作为 over）

兼容性/健壮性：
- 兼容旧版 USD：不用 Path.IsEmpty()
- resetXformStack：必要的祖先先 over 占位
- Maya USD 导出带 flags 尝试/降级重试
- 路径全部用 os.path.normpath / os.sep；比较用小写规范化
"""

import os, re, sys, json, subprocess, traceback, importlib, inspect, time, shutil, contextlib, uuid, hashlib
from datetime import datetime

import maya.cmds as cmds
import maya.utils as utils
import maya.mel as mel
import maya.OpenMayaUI as omui

from PySide2 import QtWidgets, QtCore, QtUiTools
from PySide2.QtWidgets import QMainWindow, QMessageBox, QWidget
from shiboken2 import wrapInstance
try:
    from shiboken2 import isValid as _isValid
except Exception:
    def _isValid(obj):
        try: return obj is not None and hasattr(obj, "metaObject")
        except Exception: return False

# ---------- Optional deps ----------
ShotgunDataManager = None
def export_abc(*a, **k): raise RuntimeError("utils.exportABC not found")
shotgun_shader_library = None

# relative import styles
try:
    from ..utils.SGlogin import ShotgunDataManager as _SG
    from ..utils.exportABC import export_abc as _EA
    from ..utils import shotgun_shader_library as _SSL
    ShotgunDataManager = _SG; export_abc = _EA; shotgun_shader_library = _SSL
except Exception:
    try:
        from utils.SGlogin import ShotgunDataManager as _SG
        from utils.exportABC import export_abc as _EA
        import shotgun_shader_library as _SSL
        ShotgunDataManager = _SG; export_abc = _EA; shotgun_shader_library = _SSL
    except Exception:
        pass

# ---------- PXR USD ----------
try:
    from pxr import Usd, Sdf, Gf, UsdGeom, Tf, Pcp
    PXR_USD_AVAILABLE = True
except Exception:
    PXR_USD_AVAILABLE = False


# =============================================================================
# 小工具：路径与 UI
# =============================================================================

def _normpath(p): 
    return os.path.normpath(p) if p else p

def _canon(p):   # 比较用：小写 + norm
    return (_normpath(p) or "").lower()

def maya_main_window():
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QWidget)

def load_ui(ui_file):
    loader = QtUiTools.QUiLoader()
    f = QtCore.QFile(ui_file)
    if not f.open(QtCore.QFile.ReadOnly):
        raise RuntimeError("Cannot open UI file: " + ui_file)
    ui = loader.load(f); f.close()
    return ui

def _ensure_maya_usd():
    for plug in ("mayaUsdPlugin", "mayaUsdPlugin.mll"):
        try:
            if not cmds.pluginInfo(plug, q=True, loaded=True):
                cmds.loadPlugin(plug, quiet=True)
        except Exception:
            pass
    if not cmds.pluginInfo("mayaUsdPlugin", q=True, loaded=True):
        raise RuntimeError("Could not load mayaUsdPlugin.")

def _ensure_plugin(name):
    if not cmds.pluginInfo(name, q=True, loaded=True):
        cmds.loadPlugin(name)


# =============================================================================
# 名称/上下文解析（保持你原先逻辑）
# =============================================================================

CATEGORY_ABBREVIATIONS = {
    'characters': 'chr','environments': 'env','props': 'prp','vehicles': 'veh','cgfx': 'cgfx',
}
ABBR_TO_CATEGORY = {v: k for k, v in CATEGORY_ABBREVIATIONS.items()}

ASSET_TYPES = ["mdl","shd","rig","txt","cgfx-setup","cncpt","assy"]
SHOT_TYPES  = ["anim","cgfx","comp","layout","lgt","mm","matp","paint","roto","assy"]
MAP_TO_SHD  = {"rig","mdl","cgfx-setup","cgfx"}

def _selected_namespace_token():
    sel = cmds.ls(sl=True, l=True) or []
    if not sel: return ""
    leaf = sel[0].split("|")[-1]
    ns = leaf.rpartition(":")[0]
    parts = [p for p in ns.split(":") if p]
    return parts[-1] if parts else ns

def _extract_asset_and_task(last_token):
    tokens = sorted(set(ASSET_TYPES + SHOT_TYPES), key=len, reverse=True)
    pat = r"_(%s)_" % "|".join(map(re.escape, tokens))
    m = re.search(pat, last_token)
    if not m:
        base = re.split(r"_v\d+", last_token)[0]
        task = ""; asset_with_prefix = base
    else:
        task = m.group(1); asset_with_prefix = last_token[:m.start()]
    cat_abbr = None
    for ab in sorted(ABBR_TO_CATEGORY.keys(), key=len, reverse=True):
        if asset_with_prefix.startswith(ab + "_"):
            cat_abbr = ab; break
    asset_basename = asset_with_prefix[len(cat_abbr)+1:] if cat_abbr else asset_with_prefix
    return asset_with_prefix, task, cat_abbr, asset_basename

def _canon_name(s):
    s = (s or "").strip().lower()
    return re.sub(r'[_\-]', '', s)

def _entity_matches_name(entity_name, category_abbr, asset_basename):
    en = _canon_name(entity_name)
    cand_no_prefix  = _canon_name(asset_basename)
    if category_abbr:
        cand_with_prefix = _canon_name(f"{category_abbr}_{asset_basename}")
        return en == cand_no_prefix or en == cand_with_prefix
    return en == cand_no_prefix

def _sg_project_entity(dm):
    try:
        pid = int(getattr(dm, "HAL_PROJECT_SGID", 0))
        return {'type': 'Project', 'id': pid} if pid else None
    except Exception:
        return None


# =============================================================================
# stripNamespaces 的临时重命名（保持你原先逻辑）
# =============================================================================

def _compute_basename_wo_ns(short_name): return short_name.split(':')[-1]
def _depth(path): return path.count('|')

def _list_transforms_under(selection_roots):
    nodes = []
    for r in selection_roots:
        if not cmds.objExists(r): continue
        nodes.append(r)
        kids = cmds.listRelatives(r, ad=True, type='transform', f=True) or []
        nodes.extend(kids)
    return sorted(set(nodes), key=_depth, reverse=True)

def _plan_unique_names_by_parent(selection_roots):
    transforms = _list_transforms_under(selection_roots)
    plan, by_parent = [], {}
    for t in transforms:
        p = cmds.listRelatives(t, p=True, f=True)
        parent = p[0] if p else None
        short = t.split('|')[-1]
        base = _compute_basename_wo_ns(short)
        by_parent.setdefault(parent, []).append((t, base))
    for parent, items in by_parent.items():
        used, counts = set(), {}
        for t, base in items:
            name = base
            if name in used:
                idx = counts.get(base, 1)
                while f"{base}{idx}" in used: idx += 1
                name = f"{base}{idx}"; counts[base] = idx + 1
            else:
                counts.setdefault(base, 1)
            used.add(name); plan.append((t, name))
    return plan

@contextlib.contextmanager
def _with_temp_unique_names_for_strip_ns(selection_roots):
    plan = _plan_unique_names_by_parent(selection_roots)
    todo = []
    for full, new_short in plan:
        if not cmds.objExists(full): continue
        short = full.split('|')[-1]
        base = _compute_basename_wo_ns(short)
        if short == new_short: continue
        if base == new_short and ':' not in short: continue
        todo.append((full, new_short))
    renamed = []
    try:
        for old_full, new_short in todo:
            if not cmds.objExists(old_full): continue
            try:
                new_full = cmds.rename(old_full, new_short)
                renamed.append((old_full, new_full))
            except Exception:
                pass
        yield
    finally:
        for old_full, new_full in reversed(renamed):
            try:
                if cmds.objExists(new_full):
                    old_short = old_full.split('|')[-1]
                    cmds.rename(new_full, old_short)
            except Exception:
                pass


# =============================================================================
# USD Export（含降级重试）
# =============================================================================

def _usd_export_direct(
    out_path, start, end, *,
    as_skeleton=False,
    usd_format="usdc",
    renderable_only=False,
    export_visibility=True,
    export_display_color=True,
    default_mesh_scheme="catmullClark",
    export_uvs=True,
    export_color_sets=True,
    export_materials=False,
    export_instances=True,
    export_skin=True,
    export_blendshapes=True,
    merge_transform_and_shape=None,
    strip_namespaces=False
):
    _ensure_maya_usd()
    out_path = _normpath(out_path)
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    if merge_transform_and_shape is None:
        merge_transform_and_shape = (not as_skeleton)

    base = dict(
        f=out_path.replace(os.sep, "/"),   # mayaUSDExport 要 POSIX
        selection=True,
        frameRange=(int(start), int(end)),
        frameStride=1.0,
        defaultUSDFormat=usd_format,
        shadingMode="none",
        verbose=False,
        stripNamespaces=(1 if strip_namespaces else 0),
        renderableOnly=bool(renderable_only),
        exportVisibility=bool(export_visibility),
        exportDisplayColor=bool(export_display_color),
        exportUVs=bool(export_uvs),
        exportColorSets=bool(export_color_sets),
        exportInstances=bool(export_instances),
        mergeTransformAndShape=bool(merge_transform_and_shape),
        bakeMaterials=bool(export_materials),
        defaultMeshScheme=str(default_mesh_scheme),
    )

    def _call_with_flag_pruning(k):
        removed = set()
        while True:
            try:
                cmds.mayaUSDExport(**k); return True
            except TypeError as e:
                m = re.search(r"Invalid flag '([^']+)'", str(e))
                if m:
                    bad = m.group(1)
                    if bad in k and bad not in removed:
                        removed.add(bad); k.pop(bad, None); continue
                raise

    skel_variants = []
    if as_skeleton:
        skel_variants += [
            dict(skeletons="auto", skinClusters="auto", exportBlendShapes=bool(export_blendshapes), mergeTransformAndShape=False),
            dict(skeletons="auto", skinClusters="auto", mergeTransformAndShape=False),
            dict(exportSkels="auto", exportSkin=("auto" if export_skin else "none"), exportBlendShapes=bool(export_blendshapes), mergeTransformAndShape=False),
            dict(exportSkels="auto", exportSkin=("auto" if export_skin else "none"), mergeTransformAndShape=False),
        ]
    else:
        skel_variants += [
            dict(mergeTransformAndShape=True),
            dict(mergeTransformAndShape=True, exportVisibility=False),
            dict(mergeTransformAndShape=True, exportVisibility=False, exportDisplayColor=False),
        ]

    optional_keys_drop_order = [
        "exportInstances","exportColorSets","exportUVs","exportDisplayColor",
        "exportVisibility","defaultMeshScheme","bakeMaterials","mergeTransformAndShape",
    ]

    last_err = None
    for v in skel_variants:
        cur = dict(base); cur.update(v)
        drop_list = list(optional_keys_drop_order)
        tried_configs = 0

        selection_roots = cmds.ls(sl=True, l=True) or []
        use_temp_rename = bool(cur.get('stripNamespaces'))
        ctx = _with_temp_unique_names_for_strip_ns(selection_roots) if use_temp_rename else contextlib.nullcontext()

        with ctx:
            while True:
                tried_configs += 1
                try:
                    _call_with_flag_pruning(dict(cur))
                    print(f"[USD Export] OK after {tried_configs} attempt(s). kwargs={{{', '.join(sorted(k for k in cur.keys()))}}}")
                    print(f"[USD Export] wrote: {out_path}  as_skeleton={as_skeleton}  stripNamespaces={cur.get('stripNamespaces', 0)}")
                    return
                except RuntimeError as e:
                    last_err = e
                    if not drop_list:
                        if cur.get("renderableOnly", False):
                            cur["renderableOnly"] = False
                            drop_list = list(optional_keys_drop_order); continue
                        break
                    key = drop_list.pop(0)
                    if key in cur:
                        cur.pop(key, None)
                    else:
                        if key == "mergeTransformAndShape":
                            cur["mergeTransformAndShape"] = (not cur.get("mergeTransformAndShape", True))
                    continue
                except Exception as e:
                    last_err = e; break

    raise RuntimeError(f"mayaUSDExport failed after multi-variant retries. Last error: {last_err}")


# =============================================================================
# zeroXform（只改变 xform），以及 withShader 非扁平合成
# =============================================================================

def _debug_log(msg): print(f"[DEBUG {datetime.now().strftime('%H:%M:%S')}] {msg}")

def _collect_mesh_paths_from_usd(shader_usd_path):
    if not PXR_USD_AVAILABLE: raise RuntimeError("pxr USD not available.")
    stage = Usd.Stage.Open(_normpath(shader_usd_path))
    if not stage: raise RuntimeError(f"Cannot open shader USD: {shader_usd_path}")
    paths = []
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh): paths.append(prim.GetPath())
    return paths

def _ensure_over_ancestors(stage, path: Sdf.Path):
    cur = path; parents = []
    while True:
        cur = cur.GetParentPath()
        if not cur or cur == Sdf.Path.absoluteRootPath: break
        parents.append(cur)
    for p in reversed(parents):
        if not stage.GetPrimAtPath(p):
            stage.OverridePrim(p)

def _build_zeroXform_from_shader_def(shader_usd_path, out_zero_usd_path, *, embed_shader=True):
    """生成 zeroXform.usdc：embed_shader=True 时把 shader 作为 sublayer 挂在 zero 根层。只归零/重置 xform 相关。"""
    if not PXR_USD_AVAILABLE: raise RuntimeError("pxr USD not available.")
    shader_usd_path = _normpath(shader_usd_path)
    out_zero_usd_path = _normpath(out_zero_usd_path)

    mesh_paths = _collect_mesh_paths_from_usd(shader_usd_path)
    _debug_log(f"zeroXform: mesh count = {len(mesh_paths)}  (shader={shader_usd_path})")

    out_dir = os.path.dirname(out_zero_usd_path)
    os.makedirs(out_dir, exist_ok=True)

    root_layer = Sdf.Layer.CreateNew(out_zero_usd_path)
    if embed_shader:
        root_layer.subLayerPaths = [shader_usd_path.replace(os.sep, "/")]
        root_layer.Save()
        _debug_log("zeroXform layer SUBLAYER shader inside.")

    stage = Usd.Stage.Open(out_zero_usd_path) if embed_shader else Usd.Stage.CreateNew(out_zero_usd_path)
    if not stage: stage = Usd.Stage.Open(out_zero_usd_path)

    with Usd.EditContext(stage, stage.GetEditTarget()):
        for p in mesh_paths:
            try:
                _ensure_over_ancestors(stage, p)
                prim = stage.GetPrimAtPath(p)
                if not prim: continue
                stage.OverridePrim(p)
                xf = UsdGeom.Xformable(prim)
                ops = xf.GetOrderedXformOps()
                if not ops: continue
                for op in ops:
                    t = op.GetOpType()
                    if t == UsdGeom.XformOp.TypeTransform:
                        op.Set(Gf.Matrix4d(1.0))
                    elif t in (
                        UsdGeom.XformOp.TypeRotateXYZ, UsdGeom.XformOp.TypeRotateXZY, UsdGeom.XformOp.TypeRotateYXZ,
                        UsdGeom.XformOp.TypeRotateYZX, UsdGeom.XformOp.TypeRotateZXY, UsdGeom.XformOp.TypeRotateZYX,
                        UsdGeom.XformOp.TypeRotateX, UsdGeom.XformOp.TypeRotateY, UsdGeom.XformOp.TypeRotateZ
                    ):
                        op.Set(Gf.Vec3d(0,0,0) if op.GetPrecision()==UsdGeom.XformOp.PrecisionDouble else Gf.Vec3f(0,0,0))
                    elif t == UsdGeom.XformOp.TypeTranslate:
                        op.Set(Gf.Vec3d(0,0,0) if op.GetPrecision()==UsdGeom.XformOp.PrecisionDouble else Gf.Vec3f(0,0,0))
                    elif t == UsdGeom.XformOp.TypeScale:
                        op.Set(Gf.Vec3d(1,1,1) if op.GetPrecision()==UsdGeom.XformOp.PrecisionDouble else Gf.Vec3f(1,1,1))
            except Exception as e:
                _debug_log(f"zeroXform write failed at {p}: {e}")

    stage.GetRootLayer().Save()
    _debug_log(f"zeroXform saved: {out_zero_usd_path}  (embed_shader={embed_shader})")
    return out_zero_usd_path


def _safe_new_path(pref_path: str) -> str:
    """若首选路径已存在，附加时间戳；始终返回可写的新路径。"""
    pref_path = _normpath(pref_path)
    if not os.path.exists(pref_path):
        return pref_path
    ts = time.strftime("%Y%m%d_%H%M%S")
    d, fn = os.path.split(pref_path)
    base, ext = os.path.splitext(fn)
    cand = _normpath(os.path.join(d, f"{base}_{ts}{ext or '.usdc'}"))
    if not os.path.exists(cand): return cand
    i = 2
    while True:
        cand_i = _normpath(os.path.join(d, f"{base}_{ts}_{i}{ext or '.usdc'}"))
        if not os.path.exists(cand_i): return cand_i
        i += 1

def _compose_withshader_nonflatten(anim_path: str, zero_path: str, prefer_out_path: str) -> str:
    """
    生成 withShader（非扁平；父层 + 两个子层）：
      - withShader.subLayerPaths = [anim(强), zeroXform(弱)]
      - 仅在 withShader 顶层写 Mesh.subdivisionScheme = "catmullClark"（Over）
    """
    anim_path = _normpath(anim_path)
    zero_path = _normpath(zero_path)
    out_path  = _safe_new_path(_normpath(prefer_out_path))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # 1) 创建最终层并声明 sublayers（靠前更强）
    lyr = Sdf.Layer.CreateNew(out_path)
    lyr.subLayerPaths = [anim_path.replace(os.sep,"/"), zero_path.replace(os.sep,"/")]
    lyr.Save()

    # 2) 在最终层写 subdivisionScheme（Overs）
    st = Usd.Stage.Open(out_path)
    for prim in st.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            UsdGeom.Mesh(prim).GetSubdivisionSchemeAttr().Set("catmullClark")
    st.GetRootLayer().Save()

    # 3) 打印确认
    subs = [ _normpath(p) for p in (st.GetRootLayer().subLayerPaths or []) ]
    print(f"[Compose] withShader (non-flatten): {_normpath(out_path)}")
    print("  sublayers (strong→weak):")
    for i, p in enumerate(subs):
        tag = "ANIM" if "_anim_" in os.path.basename(p).lower() else ("ZERO" if "zeroxform" in os.path.basename(p).lower() else "OTHER")
        print(f"    {i:02d}  {tag:5s} {p}")
    return out_path


# =============================================================================
# 其它导出（OBJ/FBX）
# =============================================================================

def _export_obj(path, at_frame):
    path = _normpath(path)
    cmds.currentTime(int(at_frame))
    cmds.file(path, force=True,
              options="groups=1;ptgroups=1;materials=1;smoothing=1;normals=1",
              typ="OBJexport", es=True)

def _export_fbx(path, s, e):
    path = _normpath(path)
    _ensure_plugin("fbxmaya")
    mel.eval('FBXResetExport; FBXExportSkins -v true; FBXExportShapes -v true; FBXExportBakeComplexAnimation -v true;')
    mel.eval(f'FBXExportBakeComplexStart -v {int(s)}; FBXExportBakeComplexEnd -v {int(e)};')
    cmds.file(path, force=True, options="v=0;", type="FBX export", pr=True, es=True)


# =============================================================================
# ShotGrid 快捷拾取（保留）
# =============================================================================

def _quickpick_resolve_entity_via_versions(dm):
    token = _selected_namespace_token()
    if not token: return None, None, None
    _asset_with_prefix, task_token, cat_abbr, asset_basename = _extract_asset_and_task(token)
    if not cat_abbr: return None, None, None
    if not (re.search(r'_(%s)_' % "|".join(map(re.escape, ASSET_TYPES + SHOT_TYPES)), token)):
        return None, cat_abbr, asset_basename
    category = ABBR_TO_CATEGORY.get(cat_abbr or "", "cgfx")
    context_key = f"shd/{category}"
    try:
        versions = dm.find_files(context_key, entity_type="Asset")
    except Exception as e:
        print(f"[QuickShd] find_files failed: {e}")
        return None, cat_abbr, asset_basename
    for v in versions:
        ent = (v.get("entity") or {})
        name = ent.get("name") or ""
        if _entity_matches_name(name, cat_abbr, asset_basename):
            return ent, cat_abbr, asset_basename
    return None, cat_abbr, asset_basename

def _sg_find_shd_versions_for_entity(dm, entity):
    if not entity or 'id' not in entity or 'type' not in entity: return []
    project_entity = _sg_project_entity(dm)
    filters = []
    if project_entity: filters.append(['project', 'is', project_entity])
    filters.extend([ ['entity','is',entity], ['code','contains','_shd_'] ])
    fields = ['id','code','sg_path_to_geometry','image','created_at','user','entity']
    try:
        return dm.sg.find('Version', filters, fields,
                          order=[{'field_name':'created_at','direction':'desc'}]) or []
    except Exception as e:
        print(f"[QuickShd] sg.find Version failed: {e}")
        return []


# =============================================================================
# UI 主窗口
# =============================================================================

class PublishToolWindow(QMainWindow):
    def __init__(self, parent=None):
        super(PublishToolWindow, self).__init__(parent)
        self.setWindowTitle("Animation Publish Tool v2.18 (withShader non-flatten)")
        self.export_paths = []
        self._shader_path_manual = None
        self._pending_with_shader = False
        self._withshader_sel = []
        self._shader_ui = None
        self.sg_manager = None
        self._workspace_path = None
        self._sandbox_path = None
        self._load_ui()
        self._connect_signals()
        self._set_default_ui_states()
        self._init_sg()

    # ---------- UI ----------
    def _load_ui(self):
        try:
            script_path = inspect.getframeinfo(inspect.currentframe()).filename
            script_dir = os.path.dirname(os.path.abspath(script_path))
        except Exception:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        maya_menu_dir = os.path.dirname(script_dir)
        ui_file = _normpath(os.path.join(maya_menu_dir, "QtWindows", "anim_publish_tool.ui"))
        if not os.path.exists(ui_file):
            raise RuntimeError("UI file not found: " + ui_file)
        self.ui = load_ui(ui_file)
        self.setCentralWidget(self.ui)

    def _connect_signals(self):
        self.ui.actionOpen_Project_Folder.triggered.connect(self.open_project_folder)
        self.ui.actionOpen_Playblast_Folder.triggered.connect(self.open_playblast_folder)
        self.ui.actionReset_Options.triggered.connect(self.reset_publish_options)

        self.ui.publishButton.clicked.connect(self._dispatch_publish)
        self.ui.publishWithShaderButton.clicked.connect(self.publish_with_shader)

        self.ui.radio_method_auto.toggled.connect(self._on_method_changed)
        self.ui.radio_method_sandbox.toggled.connect(self._on_method_changed)

        self.ui.prepareSceneButton.clicked.connect(self.run_prepare_scene_workflow)
        self.ui.returnToWorkspaceButton.clicked.connect(self.return_to_workspace)

        self.ui.UnusedShadeButton.clicked.connect(self.remove_unused_shade)
        self.ui.tagAnimOrNot.toggled.connect(self.ui.tagName.setEnabled)
        self.ui.exportCamOrNot.toggled.connect(self._toggle_camera_widgets)
        self.ui.refreshCamerasButton.clicked.connect(self._populate_camera_dropdown)
        self.ui.currentStartFrame.clicked.connect(self.set_current_start_frame)
        self.ui.currentEndFrame.clicked.connect(self.set_current_end_frame)
        self.ui.SGframeImport.clicked.connect(self.set_sg_frame_range)
        self.ui.AlembicTag.toggled.connect(self.ui.curveExportOptions.setEnabled)

    def _set_default_ui_states(self):
        self.ui.USDCTag.setChecked(True)
        self.ui.AlembicTag.setChecked(True)
        self.ui.tagName.setEnabled(False)
        self.ui.curveExportOptions.setEnabled(self.ui.AlembicTag.isChecked())
        self._toggle_camera_widgets(self.ui.exportCamOrNot.isChecked())
        self.set_current_start_frame()
        self.set_current_end_frame()
        self.ui.returnToWorkspaceButton.setEnabled(False)
        self._on_method_changed()

    def _init_sg(self):
        if ShotgunDataManager:
            try:
                self.sg_manager = ShotgunDataManager()
            except Exception as e:
                QMessageBox.critical(self, "ShotGrid 错误", f"初始化SG失败: {e}")
                self.sg_manager = None

    # ---------- With Shader ----------
    def publish_with_shader(self):
        if not self.validate_frame_range(): return
        sel = cmds.ls(sl=True, l=True)
        if not sel:
            QMessageBox.warning(self, "选择错误", "请选择要发布的物体（骨骼+蒙皮/几何）。"); return
        self._withshader_sel = sel[:]

        # 先尝试 SG 快捷拾取，再回退到库
        try:
            if self.sg_manager and getattr(self.sg_manager, "sg", None):
                from ..utils.quick_shader_picker_mini import show_quick_shader_picker
                ent, cat_abbr, asset_basename = _quickpick_resolve_entity_via_versions(self.sg_manager)
                if ent:
                    def _on_pick(usd_path):
                        self._shader_path_manual = usd_path
                        self._do_publish_with_shader()
                    show_quick_shader_picker(parent=self, on_select=_on_pick); return
                else:
                    print("[WithShader] Quick picker: asset not found in versions context, fallback to library.")
            else:
                print("[WithShader] Quick picker skipped: SG manager not ready.")
        except Exception as _e:
            traceback.print_exc()
            print(f"[WithShader] Quick picker failed, fallback to library. Cause: {_e}")

        # fallback to library
        global shotgun_shader_library
        try:
            if shotgun_shader_library is None:
                import shotgun_shader_library as _ssl
                shotgun_shader_library = _ssl
            else:
                shotgun_shader_library = importlib.reload(shotgun_shader_library)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "缺少模块", f"加载/重载 shotgun_shader_library 失败：\n{e}")
            return

        self._pending_with_shader = True
        def _on_pick(path):
            try:
                self._shader_path_manual = path
                self._do_publish_with_shader()
            except Exception:
                traceback.print_exc()

        try:
            if hasattr(shotgun_shader_library, "show_for_publish"):
                ui = shotgun_shader_library.show_for_publish(parent=self, on_select=_on_pick)
            elif hasattr(shotgun_shader_library, "show"):
                ui = shotgun_shader_library.show(parent=self, on_select_callback=_on_pick)
            else:
                raise RuntimeError("shotgun_shader_library 缺少 show_for_publish/show 接口")
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "错误", f"打开材质库失败：\n{e}")
            self._pending_with_shader = False
            return

        self._shader_ui = ui
        try: ui.destroyed.connect(lambda *_: setattr(self, "_shader_ui", None))
        except Exception: pass
        try: ui.setWindowModality(QtCore.Qt.NonModal); ui.show(); ui.raise_(); ui.activateWindow()
        except Exception: pass

    def _do_publish_with_shader(self):
        if not self._shader_path_manual:
            QMessageBox.warning(self, "无效材质路径", "没有选择有效的材质 USD 路径，操作终止。"); return
        if not PXR_USD_AVAILABLE:
            QMessageBox.critical(self, "缺少依赖", "未检测到 PXR USD（pxr.Usd/Sdf），无法合成‘带材质’USD。"); return

        start, end = self._get_frame_range()
        ver = self.get_next_version()
        tag = self.ui.tagName.text().strip() if self.ui.tagAnimOrNot.isChecked() else ""
        if not self._validate_tag_name(tag): return

        # 恢复选择（关节 + Mesh xform）
        try:
            final_sel = []
            if self._withshader_sel:
                dag_nodes = cmds.ls(self._withshader_sel, dag=True, l=True) or []
                joints = cmds.ls(dag_nodes, type='joint', l=True) or []
                meshes = cmds.ls(dag_nodes, type='mesh', l=True) or []
                mesh_xforms = cmds.listRelatives(meshes, p=True, f=True) or []
                final_sel = sorted(set(joints + mesh_xforms))
            if final_sel: cmds.select(final_sel, r=True)
        except Exception:
            pass

        as_skeleton = (self.ui.tabWidget_publishMode.currentIndex() == 1)

        # 1) anim USD（不带材质）
        try:
            anim_usd = _normpath(self.get_publish_path("usdc", ver, tag))
            prev_sup_warn = cmds.scriptEditorInfo(q=True, suppressWarnings=True)
            try:
                cmds.scriptEditorInfo(suppressWarnings=True)
                _usd_export_direct(
                    anim_usd, start, end,
                    as_skeleton=as_skeleton,
                    usd_format="usdc",
                    strip_namespaces=True,
                    export_materials=False,
                    renderable_only=True,
                    export_display_color=False,
                    export_color_sets=False
                )
            finally:
                cmds.scriptEditorInfo(suppressWarnings=prev_sup_warn)
            print(f"[WithShader] Anim USD exported: {anim_usd}")
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "导出失败", f"动画 USD 导出失败：\n{e}")
            return

        # 2) zeroXform（**内嵌 shader 到 zeroXform**，便于单独打开也完整）
        try:
            root, _, _ = self.get_publish_base()
            base_name = os.path.splitext(os.path.basename(self._build_name(ver, tag)))[0]
            zero_usd = _normpath(os.path.join(root, "_publish", f"{base_name}_zeroXform.usdc"))
            _build_zeroXform_from_shader_def(self._shader_path_manual, zero_usd, embed_shader=True)
            print(f"[WithShader] zeroXform DEF layer created: {zero_usd}")
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "zeroXform 失败", f"生成 zeroXform DEF 层失败：\n{e}")
            return

        # 3) 合成最终层（非扁平，父层 + 两个子层）
        try:
            final_usd = self._compose_shader_layer(anim_usd, self._shader_path_manual, zero_usd, ver, tag, zero_embeds_shader=True)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "合成失败", f"叠加材质 USD 失败：\n{e}")
            return

        try:
            self.export_paths = [final_usd]
            self._submit_thumbnail_and_sg(start, end, self.export_paths, tag)
            QMessageBox.information(self, "成功", "带材质 Publish 完成。")
        except Exception as e:
            traceback.print_exc()
            QMessageBox.warning(self, "提交提示", f"已生成带材质 USD，但提交 SG 失败：\n{e}")

    def _compose_shader_layer(self, anim_usd_path, shader_usd_path, zero_usd_path, ver, tag, zero_embeds_shader=True):
        """类内唯一 compose：直接调用非扁平装配函数。"""
        root, _, _ = self.get_publish_base()
        base_name = os.path.splitext(os.path.basename(self._build_name(ver, tag)))[0]
        prefer_out = _normpath(os.path.join(root, "_publish", f"{base_name}_withShader.usdc"))
        return _compose_withshader_nonflatten(anim_usd_path, zero_usd_path, prefer_out)

    # ---------- Sandbox / 其它（保持你原有逻辑，路径全部规范化） ----------
    def _get_writable_tmp_dir(self):
        task_root = os.environ.get("HAL_TASK_ROOT", "")
        if task_root:
            d = _normpath(os.path.join(task_root, "_publish", "_tmp"))
            try:
                os.makedirs(d, exist_ok=True)
                test = _normpath(os.path.join(d, f".t_{uuid.uuid4().hex}"))
                with open(test, "wb") as f: f.write(b"ok")
                os.remove(test); return d
            except Exception:
                pass
        try:
            d = _normpath(cmds.internalVar(userTmpDir=True))
            os.makedirs(d, exist_ok=True); return d
        except Exception:
            pass
        import tempfile
        d = _normpath(tempfile.gettempdir())
        os.makedirs(d, exist_ok=True); return d

    def _import_references_in_layers(self):
        max_pass = 10
        for _ in range(max_pass):
            refs = cmds.ls(type='reference') or []
            any_done = False
            for ref_node in refs:
                try:
                    if cmds.referenceQuery(ref_node, isLoaded=True):
                        file_path = cmds.referenceQuery(ref_node, filename=True, withoutCopyNumber=True)
                        cmds.file(file_path, importReference=True)
                        any_done = True
                except Exception:
                    continue
            if not any_done: break

    def _strip_namespaces_for_all_transforms(self):
        transforms = cmds.ls(type='transform', l=True) or []
        transforms = sorted(set(transforms), key=lambda p: p.count('|'), reverse=True)

        def _short(n): return n.split('|')[-1]
        def _basename_wo_ns(short): return short.split(':')[-1]

        parent_children = {}
        for t in transforms:
            parent = cmds.listRelatives(t, p=True, f=True)
            parent = parent[0] if parent else None
            parent_children.setdefault(parent, set()).add(_short(t))

        for t in transforms:
            if not cmds.objExists(t): continue
            parent = cmds.listRelatives(t, p=True, f=True)
            parent = parent[0] if parent else None
            used = parent_children.setdefault(parent, set())

            old_short = _short(t)
            target = _basename_wo_ns(old_short)
            if target == old_short: continue

            new_name = target
            if new_name in used:
                i = 1
                while f"{target}_dup{i}" in used: i += 1
                new_name = f"{target}_dup{i}"

            try:
                new_full = cmds.rename(t, new_name)
                used.discard(old_short)
                used.add(_short(new_full))
            except Exception:
                continue

    def _on_method_changed(self):
        if self.ui.radio_method_auto.isChecked():
            self.ui.stackedWidget_method_details.setCurrentIndex(0)
        else:
            self.ui.stackedWidget_method_details.setCurrentIndex(1)
        in_sandbox = bool(self._sandbox_path)
        self.ui.prepareSceneButton.setEnabled(not in_sandbox)
        self.ui.returnToWorkspaceButton.setEnabled(in_sandbox)

    def run_prepare_scene_workflow(self):
        current_filepath = _normpath(cmds.file(q=True, sceneName=True))
        if not current_filepath:
            QMessageBox.critical(self, "保存错误", "请先保存你的场景文件再创建沙盒。"); return
        try: cmds.file(save=True)
        except Exception as e:
            QMessageBox.critical(self, "保存错误", f"保存当前工程失败：{e}"); return

        tmp_dir = self._get_writable_tmp_dir()
        base_name, ext = os.path.splitext(os.path.basename(current_filepath))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sandbox_filename = f"{base_name}_sandbox_{timestamp}{ext or '.ma'}"
        sandbox_filepath = _normpath(os.path.join(tmp_dir, sandbox_filename))

        try: shutil.copy2(current_filepath, sandbox_filepath)
        except Exception as e:
            QMessageBox.critical(self, "复制失败", f"创建沙盒失败：\n{e}\n目标：{sandbox_filepath}"); return

        try: cmds.file(sandbox_filepath, open=True, force=True)
        except Exception as e:
            QMessageBox.critical(self, "打开错误", f"打开沙盒失败：\n{e}"); return

        self._workspace_path = current_filepath
        self._sandbox_path = sandbox_filepath
        self._on_method_changed()

        try:
            self._import_references_in_layers()
            self._strip_namespaces_for_all_transforms()
            QMessageBox.information(self, "成功", f"沙盒已就绪：\n{sandbox_filename}")
        except Exception as e:
            traceback.print_exc()
            QMessageBox.warning(self, "沙盒处理提示", f"沙盒已创建，但后续清理出现问题：\n{e}")

    def return_to_workspace(self):
        if not self._workspace_path or not os.path.exists(self._workspace_path):
            QMessageBox.warning(self, "文件未找到", "无法找到原始工作文件路径。"); return
        try:
            cmds.file(self._workspace_path, open=True, force=True)
            QMessageBox.information(self, "返回成功", "已返回原始工作文件。")
        finally:
            self._sandbox_path = None
            self._on_method_changed()

    # ---------- Publish dispatch ----------
    def _dispatch_publish(self):
        if not self.validate_frame_range(): return
        if self.ui.tabWidget_publishMode.currentIndex() == 0:
            self.publish_geometry()
        else:
            self.publish_skeleton()

    # ---------- paths & versions ----------
    def get_next_version(self):
        pub_dir = _normpath(os.path.join(os.environ.get("HAL_TASK_ROOT", ""), "_publish"))
        os.makedirs(pub_dir, exist_ok=True)
        versions = [int(m.group(1)) for f in os.listdir(pub_dir) if (m := re.search(r'_v(\d{3,})', f))]
        return f"v{max(versions)+1:03d}" if versions else "v001"

    def get_publish_base(self):
        task_root = os.environ.get("HAL_TASK_ROOT", "")
        if not task_root: raise RuntimeError("HAL_TASK_ROOT not set")
        env = os.environ
        if "_library" in task_root:
            base = f"{env.get('HAL_PROJECT_ABBR')}_{env.get('HAL_ASSET')}_{env.get('HAL_TASK')}"
        else:
            base = f"{env.get('HAL_PROJECT_ABBR')}_{env.get('HAL_SEQUENCE')}_{env.get('HAL_SHOT')}_{env.get('HAL_TASK')}"
        user = env.get('HAL_USER_ABBR')
        return _normpath(task_root), base, user

    def _build_name(self, ver, tag):
        _, base, user = self.get_publish_base()
        name = f"{base}_{ver}_{user}"
        return f"{name}_{tag}" if tag else name

    def get_publish_path(self, fmt, ver, tag=""):
        root, _, _ = self.get_publish_base()
        name = self._build_name(ver, tag)
        return _normpath(os.path.join(root, "_publish", f"{name}.{fmt}"))

    # ---------- publish geometry ----------
    def publish_geometry(self):
        sel = cmds.ls(sl=True, l=True)
        if not sel:
            QMessageBox.warning(self, "选择错误", "请选择要发布的物体。"); return

        start, end = self._get_frame_range()
        ver = self.get_next_version()
        tag = self.ui.tagName.text().strip() if self.ui.tagAnimOrNot.isChecked() else ""
        if not self._validate_tag_name(tag): return

        formats = []
        if self.ui.USDCTag.isChecked(): formats.append("usdc")
        if self.ui.USDATag.isChecked(): formats.append("usda")
        if self.ui.AlembicTag.isChecked(): formats.append("abc")
        if self.ui.OBJTag.isChecked(): formats.append("obj")
        if not formats:
            QMessageBox.warning(self, "格式错误", "请至少选择一种导出格式。"); return

        self.export_paths = []
        curves = self.ui.exportCurvesYes.isChecked()

        try:
            for fmt in formats:
                cmds.select(sel, r=True)
                if fmt in ("usdc","usda"):
                    out_path = self.get_publish_path(fmt, ver, tag)
                    prev_sup_warn = cmds.scriptEditorInfo(q=True, suppressWarnings=True)
                    try:
                        cmds.scriptEditorInfo(suppressWarnings=True)
                        _usd_export_direct(
                            out_path, start, end,
                            as_skeleton=False,
                            usd_format=fmt,
                            strip_namespaces=True,
                            export_materials=False,
                            renderable_only=True,
                            export_display_color=False,
                            export_color_sets=False
                        )
                    finally:
                        cmds.scriptEditorInfo(suppressWarnings=prev_sup_warn)
                    self.export_paths.append(out_path)
                elif fmt == "abc":
                    abc_path = self.get_publish_path(fmt, ver, tag)
                    export_abc(abc_path, start, end, include_curves=curves)
                    self.export_paths.append(abc_path)
                elif fmt == "obj":
                    obj_path = self.get_publish_path(fmt, ver, tag)
                    _export_obj(obj_path, start)
                    self.export_paths.append(obj_path)

            self._submit_thumbnail_and_sg(start, end, self.export_paths, tag)
            QMessageBox.information(self, "成功", "Publish 完成。")
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "失败", str(e))

    # ---------- publish skeleton (USD or FBX) ----------
    def publish_skeleton(self):
        sel = cmds.ls(sl=True, l=True)
        if not sel:
            QMessageBox.warning(self, "选择错误", "请选择根关节和网格。"); return
        nodes = sel + (cmds.listRelatives(sel, ad=True, f=True) or [])
        if not cmds.ls(nodes, type='joint', l=True) or not cmds.ls(nodes, type='mesh', l=True):
            QMessageBox.warning(self, "选择错误", "骨骼导出选择必须包含骨骼和网格。"); return

        start, end = self._get_frame_range()
        ver = self.get_next_version()
        tag = self.ui.tagName.text().strip() if self.ui.tagAnimOrNot.isChecked() else ""
        if not self._validate_tag_name(tag): return

        try:
            cmds.select(sel, r=True)
            if self.ui.radio_export_fbx.isChecked():
                fbx = self.get_publish_path("fbx", ver, tag)
                _export_fbx(fbx, start, end)
                self.export_paths = [fbx]
            else:
                usd = self.get_publish_path("usdc", ver, tag)
                prev_sup_warn = cmds.scriptEditorInfo(q=True, suppressWarnings=True)
                try:
                    cmds.scriptEditorInfo(suppressWarnings=True)
                    _usd_export_direct(
                        usd, start, end,
                        as_skeleton=True,
                        usd_format="usdc",
                        strip_namespaces=True,
                        export_materials=False,
                        renderable_only=True,
                        export_display_color=False,
                        export_color_sets=False
                    )
                finally:
                    cmds.scriptEditorInfo(suppressWarnings=prev_sup_warn)
                self.export_paths = [usd]

            self._submit_thumbnail_and_sg(start, end, self.export_paths, tag)
            QMessageBox.information(self, "成功", "骨骼 Publish 完成。")
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "发布失败", str(e))

    # ---------- commons ----------
    def validate_frame_range(self):
        try:
            s, e = self._get_frame_range()
            return int(s) < int(e)
        except Exception:
            QMessageBox.warning(self, "帧范围错误", "起始/结束帧必须是有效整数，且结束帧 > 起始帧。")
            return False

    def _get_frame_range(self):
        return int(self.ui.startFrameEdit.text()), int(self.ui.endFrameEdit.text())

    def _validate_tag_name(self, tag):
        if tag and not re.match(r'^[a-zA-Z0-9_]+$', tag):
            QMessageBox.warning(self, "无效标签", "标签名称只能包含字母、数字和下划线。"); return False
        return True

    def _toggle_camera_widgets(self, checked):
        self.ui.camExportArea.setEnabled(checked)
        self.ui.refreshCamerasButton.setEnabled(checked)

    def _populate_camera_dropdown(self):
        self.ui.camExportArea.clear()
        cam_shapes = cmds.ls(type='camera', l=True)
        startup = {'frontShape','perspShape','sideShape','topShape'}
        renderable = [c for c in cam_shapes if cmds.getAttr(f"{c}.renderable")]
        parents = cmds.listRelatives([c for c in renderable if c.split('|')[-1] not in startup], p=True, f=True) or []
        if parents: self.ui.camExportArea.addItems(sorted(set(parents)))

    def _submit_thumbnail_and_sg(self, start, end, export_paths, tag):
        if not (ShotgunDataManager and self.sg_manager): return
        try:
            task_root, _, _ = self.get_publish_base()
            thumb_dir = _normpath(os.path.join(task_root, "_publish", "_SGthumbnail"))
            os.makedirs(thumb_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(export_paths[0]))[0]
            thumb_prefix = _normpath(os.path.join(thumb_dir, f"{base}_temp"))
            pb_args = dict(f=thumb_prefix.replace(os.sep,"/"), st=int(start), et=int(start), fmt='image', c='png',
                           qlt=100, p=100, wh=(1920,1080), orn=False, fo=True, v=False)
            if self.ui.exportCamOrNot.isChecked() and self.ui.camExportArea.currentText():
                panel = cmds.getPanel(withFocus=True)
                if "modelPanel" in panel:
                    cmds.lookThru(panel, self.ui.camExportArea.currentText())
            cmds.playblast(**pb_args)
            thumb_path = _normpath(f"{thumb_prefix}.{str(int(start)).zfill(4)}.png")
            file_export_path = json.dumps(list(export_paths))
            self.sg_manager.Create_SG_Version(thumb_path, file_export_path, int(start), int(end), anim_tag=tag or "")
            print("[SG] Version created.")
        except Exception as e:
            print(f"[SG] submit failed: {e}")

    # ---- misc ui ----
    def open_project_folder(self):
        path = os.environ.get("HAL_TASK_ROOT", "")
        if path and os.path.isdir(path):
            subprocess.Popen(f'explorer "{_normpath(path)}"')

    def open_playblast_folder(self):
        path = _normpath(os.path.join(os.environ.get("HAL_TASK_OUTPUT_ROOT", ""), "playblast"))
        if os.path.isdir(path):
            subprocess.Popen(f'explorer "{path}"')

    def reset_publish_options(self):
        self._set_default_ui_states()

    def remove_unused_shade(self):
        mel.eval('hyperShadePanelMenuCommand "hyperShadePanel1" "deleteUnusedNodes";')
        cmds.inViewMessage(msg="已移除未使用的材质", pos="topLeft", fade=True)

    def set_current_start_frame(self):
        self.ui.startFrameEdit.setText(str(int(cmds.playbackOptions(q=True, min=True))))

    def set_current_end_frame(self):
        self.ui.endFrameEdit.setText(str(int(cmds.playbackOptions(q=True, max=True))))

    def set_sg_frame_range(self):
        if not (self.sg_manager and hasattr(self.sg_manager, 'HAL_SHOT_SGID') and self.sg_manager.HAL_SHOT_SGID):
            QMessageBox.warning(self, "信息缺失", "非镜头任务或缺少镜头ID。"); return
        try:
            frame_data = self.sg_manager.getSGData("Shot", int(self.sg_manager.HAL_SHOT_SGID))[0]
            start = frame_data.get('sg_head_in', frame_data.get('sg_cut_in'))
            end   = frame_data.get('sg_tail_out', frame_data.get('sg_cut_out'))
            if start: self.ui.startFrameEdit.setText(str(int(start)))
            if end:   self.ui.endFrameEdit.setText(str(int(end)))
        except Exception as e:
            QMessageBox.warning(self, "SG 错误", f"无法获取帧范围: {e}")


# =============================================================================
# Entry
# =============================================================================

def get_command():
    def _command():
        global anim_publish_tool_window
        try:
            if 'anim_publish_tool_window' in globals() and _isValid(anim_publish_tool_window) and anim_publish_tool_window.isVisible():
                anim_publish_tool_window.close()
                anim_publish_tool_window.deleteLater()
        except Exception:
            pass
        anim_publish_tool_window = PublishToolWindow(parent=maya_main_window())
        anim_publish_tool_window.show()
    return _command

def execute():
    cmd = get_command()
    utils.executeInMainThreadWithResult(cmd)
