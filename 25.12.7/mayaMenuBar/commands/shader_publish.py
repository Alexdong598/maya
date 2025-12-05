# -*- coding: utf-8 -*-
"""
Shader publishing tool with Qt UI for Maya.
Integrates USD Arnold export with proxy + LOD variants.

This version uses a MEL-equivalent polyReduce (preserveTopology + keep* borders)
to avoid creating nonmanifold geometry, and keeps the rest of your pipeline:

- <Top>.usdc PAYLOADS variant.usdc so the 'levels' variant set appears at the top prim.
- payload.usdc sublayers [meta.usdc (strongest), proxy.usdc, shd.usdc].
- LOD wraps sublayer meta.usdc then reference the LOD geo so meta bindings apply.
- Optional LOD count. Proxy reduction and LOD reduction are independent.
"""
import os
import sys
import importlib
import subprocess
import re
import shutil

import maya.cmds as cmds
import maya.utils as utils
import maya.mel as mel
import maya.OpenMayaUI as omui

from PySide2 import QtWidgets, QtCore, QtUiTools
from PySide2.QtWidgets import QMainWindow, QMessageBox, QWidget
from shiboken2 import wrapInstance

from ..utils import camThumbnail
from ..utils.SGlogin import ShotgunDataManager

# -----------------------------------------------------------------------------
# -- BEGIN: USD / Arnold helpers
# -----------------------------------------------------------------------------

def _ensure_mtoa():
    if not cmds.pluginInfo("mtoa", q=True, loaded=True):
        cmds.loadPlugin("mtoa")
    global arnold
    import arnold  # noqa: F401


def _ensure_maya_usd():
    if not cmds.pluginInfo("mayaUsdPlugin", q=True, loaded=True):
        cmds.loadPlugin("mayaUsdPlugin")


def _next_version_folder(parent_dir):
    if not os.path.isdir(parent_dir):
        os.makedirs(parent_dir)
    pat = re.compile(r'^v(\d{3,})$', re.IGNORECASE)
    max_n = 0
    for name in os.listdir(parent_dir):
        full = os.path.join(parent_dir, name)
        if os.path.isdir(full):
            m = pat.match(name)
            if m:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
    ver = f'v{(max_n+1):03d}'
    ver_path = os.path.join(parent_dir, ver)
    if not os.path.isdir(ver_path):
        os.makedirs(ver_path)
    return ver, ver_path


def _non_intermediate_mesh_shapes_under(root):
    shapes = cmds.listRelatives(root, ad=True, type='mesh', fullPath=True) or []
    out = []
    for s in shapes:
        try:
            if not cmds.getAttr(s + '.intermediateObject'):
                out.append(s)
        except Exception:
            out.append(s)
    return out


def _unique_parents_of_shapes(shapes):
    parents = set()
    for s in shapes:
        p = cmds.listRelatives(s, parent=True, fullPath=True) or []
        if p:
            parents.add(p[0])
    return parents


def _safe_rename(node, new_name):
    """Rename but always return long DAG path; be resilient to stale paths."""
    if not node or not cmds.objExists(node):
        # Node 已经因为上游重命名/删除而失效，返回目标短名，调用方不要依赖它是存在的
        return new_name
    try:
        new = cmds.rename(node, new_name)
        long = cmds.ls(new, l=True) or [new]
        return long[0]
    except Exception:
        # 尝试用当前能解析到的长名返回，避免 IndexError
        found = cmds.ls(node, l=True) or cmds.ls(node) or []
        return found[0] if found else new_name


# ---------- polyReduce helpers (MEL-equivalent) -----------------------------

def _cleanup_light(xform):
    """Non-manifold / lamina / n-gons cleanup; no history."""
    try:
        cmds.polyCleanup(
            xform, ch=False,
            nonManifoldGeometry=1,
            laminaFace=1,
            facesWithMoreThanFourSides=1
        )
    except Exception:
        pass

def _poly_reduce_like_mel(xform, percent):
    """
    Mirror your MEL flags:
    -preserveTopology 1, keep* borders, hard/crease edges, weights=0.5, etc.
    """
    return cmds.polyReduce(
        xform,
        ver=1, trm=0, shp=0,
        keepBorder=1, keepMapBorder=1, keepColorBorder=1, keepFaceGroupBorder=1,
        keepHardEdge=1, keepCreaseEdge=1,
        keepBorderWeight=0.5, keepMapBorderWeight=0.5, keepColorBorderWeight=0.5,
        keepFaceGroupBorderWeight=0.5, keepHardEdgeWeight=0.5, keepCreaseEdgeWeight=0.5,
        useVirtualSymmetry=0, symmetryTolerance=0.01,
        sx=0, sy=1, sz=0, sw=0,
        preserveTopology=1,
        keepQuadsWeight=1,
        vertexMapName="",
        cachingReduce=1,
        ch=1,
        p=float(percent),
        vct=0, tct=0,
        replaceOriginal=1
    )

def _reduce_with_cleanup(xform, percent):
    """
    Try MEL-equivalent reduce; if it errors on problem topology, cleanup + retry.
    Final fallback: short '-p' path (still with history) to avoid hard failure.
    """
    try:
        _poly_reduce_like_mel(xform, percent)
        return True
    except RuntimeError:
        _cleanup_light(xform)
        try:
            _poly_reduce_like_mel(xform, percent)
            return True
        except Exception:
            pass
    except Exception:
        pass

    # Last resort
    try:
        cmds.polyReduce(xform, ch=1, p=float(percent), replaceOriginal=1)
        return True
    except Exception:
        print(f"[WARN] polyReduce failed on {xform} even after cleanup.")
        return False


def _duplicate_and_reduce(src, suffix='_proxy', percent=50.0):
    dup = cmds.duplicate(src, rr=True)[0]
    dup = cmds.ls(dup, l=True)[0]  # 确保后续全用长路径

    mesh_shapes = _non_intermediate_mesh_shapes_under(dup)
    # 关键：从“深”到“浅”重命名，避免改父后子路径失效
    for x in sorted(_unique_parents_of_shapes(mesh_shapes),
                    key=lambda p: p.count('|'), reverse=True):
        short = x.split('|')[-1]
        if not short.endswith(suffix):
            _safe_rename(x, short + suffix)

    # 之后再重算一次 shape 列表再给 shape 加后缀（可保留你现在的写法）
    for s in _non_intermediate_mesh_shapes_under(dup):
        short = s.split('|')[-1]
        if not short.endswith(suffix):
            _safe_rename(s, short + suffix)

    top_short = src.split('|')[-1]
    dup = _safe_rename(dup, f'{top_short}{suffix}')

    # use MEL-equivalent reducer (+ cleanup fallback)
    parents = sorted(_unique_parents_of_shapes(_non_intermediate_mesh_shapes_under(dup)),
                     key=lambda p: p.count('|'))
    for x in parents:
        _reduce_with_cleanup(x, percent)

    return dup


# ------------------------------ USD helpers --------------------------------

def _create_empty_usd_stage(stage_name):
    _ensure_maya_usd()
    xf = cmds.createNode("transform", name=stage_name)
    shp = cmds.createNode("mayaUsdProxyShape", name=f"{stage_name}Shape", parent=xf)
    cmds.setAttr(f"{shp}.filePath", "", type="string")
    return xf, shp


def _rename_nonmesh_parents_in_layer_with_sdf(usd_file, suffix='_proxy'):
    from pxr import Usd, UsdGeom, Sdf, Tf
    stage = Usd.Stage.Open(usd_file)
    if not stage:
        raise RuntimeError("Could not open USD: %s" % usd_file)
    layer = stage.GetRootLayer()
    candidates = set()
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh):
            p = prim.GetParent()
            while p and p != stage.GetPseudoRoot():
                if not p.IsA(UsdGeom.Mesh):
                    nm = p.GetName()
                    if nm.endswith(suffix) and len(nm) > len(suffix):
                        candidates.add(p.GetPath().pathString)
                p = p.GetParent()
    if not candidates:
        layer.Save()
        return 0, 0
    paths = sorted(candidates, key=lambda s: s.count('/'), reverse=True)
    renamed, skipped = 0, 0
    mapping = {}

    def remap(pstr):
        for old, new in mapping.items():
            if pstr.startswith(old):
                return pstr.replace(old, new, 1)
        return pstr

    for old_s in paths:
        cur_s = remap(old_s)
        cur = Sdf.Path(cur_s)
        if not layer.GetPrimAtPath(cur):
            skipped += 1
            continue
        parent = cur.GetParentPath()
        name = cur.name
        if not name.endswith(suffix) or len(name) <= len(suffix):
            skipped += 1
            continue
        base = Tf.MakeValidIdentifier(name[:-len(suffix)]) or "renamed"
        dst = parent.AppendChild(base)
        i = 1
        while layer.GetPrimAtPath(dst):
            dst = parent.AppendChild(f"{base}_r{i}")
            i += 1
        edit = Sdf.BatchNamespaceEdit()
        edit.Add(cur, dst)
        if not layer.Apply(edit):
            skipped += 1
            continue
        mapping[cur_s] = dst.pathString
        renamed += 1
    layer.Save()
    return renamed, skipped


def _write_payload_contents_layer(top_name, proxy_path, shd_path, out_path):
    from pxr import Sdf
    out_path = out_path.replace("\\", "/")
    lyr = Sdf.Layer.CreateNew(out_path)
    if not lyr:
        raise RuntimeError(f"Cannot create payload layer: {out_path}")
    lyr.defaultPrim = top_name
    lyr.subLayerPaths = [proxy_path.replace("\\", "/"), shd_path.replace("\\", "/")]
    lyr.Save()
    print(f"[USD] wrote contents(payload) layer: {out_path}")
    return out_path


def _write_interface_top_layer(top_name, payload_or_variant_path, out_path, add_geommodelapi=True):
    from pxr import Sdf, Usd, Kind, UsdGeom
    out_path = out_path.replace("\\", "/")
    root = Sdf.Layer.CreateNew(out_path)
    if not root:
        raise RuntimeError(f"Cannot create interface layer: {out_path}")
    stg = Usd.Stage.Open(root)
    stg.SetDefaultPrim(stg.DefinePrim(Sdf.Path("/" + top_name), "Xform"))
    top = stg.GetPrimAtPath("/" + top_name)
    Usd.ModelAPI(top).SetKind(Kind.Tokens.component)
    if add_geommodelapi:
        try:
            UsdGeom.ModelAPI.Apply(top)
        except Exception as e:
            print("[USD][WARN] UsdGeom.ModelAPI.Apply failed:", e)
    top.GetPayloads().AddPayload(payload_or_variant_path, Sdf.Path("/" + top_name))
    top.SetCustomDataByKey("geo", top_name)
    class_container = Sdf.Path("/__class__")
    class_path = class_container.AppendChild(top_name)
    Sdf.CreatePrimInLayer(root, class_container).specifier = Sdf.SpecifierClass
    Sdf.CreatePrimInLayer(root, class_path).specifier = Sdf.SpecifierClass
    top.GetInherits().AddInherit(class_path)
    stg.GetRootLayer().defaultPrim = top_name
    stg.GetRootLayer().Save()
    print(f"[USD] wrote interface(top) layer: {out_path}")
    return out_path


def _set_strength_stronger(binding_api):
    from pxr import UsdShade
    try:
        attr = binding_api.GetMaterialBindingStrengthAttr()
        if attr:
            attr.Set(UsdShade.Tokens.strongerThanDescendants)
    except Exception:
        pass


def _author_meta_and_fix_materials(top_name, payload_usdc, meta_out_path):
    from pxr import Usd, UsdGeom, UsdShade, Sdf, Ar
    payload_layer = Sdf.Layer.FindOrOpen(payload_usdc.replace("\\", "/"))
    if not payload_layer:
        raise RuntimeError("Cannot open payload layer")
    meta_layer = Sdf.Layer.CreateNew(meta_out_path.replace("\\", "/"))
    resolver = Ar.GetResolver()
    meta_id_norm = resolver.Resolve(meta_layer.identifier) or meta_layer.identifier
    subs = list(payload_layer.subLayerPaths)
    subs_norm = [resolver.Resolve(p) or p for p in subs]
    if meta_id_norm not in subs_norm:
        subs.insert(0, meta_id_norm)
        payload_layer.subLayerPaths = subs
        payload_layer.Save()
        print(f"[USD] prepended meta layer into payload: {meta_id_norm}")

    stg = Usd.Stage.Open(payload_layer)
    stg.SetEditTarget(meta_layer)
    top_path = Sdf.Path("/" + top_name)
    mtl_parent = top_path.AppendChild("mtl")

    def _ensure_over_prim(layer, path):
        spec = layer.GetPrimAtPath(path)
        if not spec:
            spec = Sdf.CreatePrimInLayer(layer, path)
            spec.specifier = Sdf.SpecifierOver
        return spec

    def _ensure_def_scope(layer, path):
        spec = layer.GetPrimAtPath(path)
        if not spec:
            spec = Sdf.CreatePrimInLayer(layer, path)
            spec.specifier = Sdf.SpecifierDef
            spec.typeName = "Scope"
        return spec

    _ensure_over_prim(meta_layer, top_path)
    _ensure_def_scope(meta_layer, mtl_parent)

    def _get_defining_layer_for_prim(prim):
        for spec in prim.GetPrimStack():
            if spec.layer.GetPrimAtPath(spec.path):
                return spec.layer, spec.path
        return None, None

    mat_remap = {}
    copied_mats = 0
    for prim in stg.TraverseAll():
        if prim.IsA(UsdShade.Material) and not prim.GetPath().HasPrefix(top_path):
            src_layer, src_path = _get_defining_layer_for_prim(prim)
            if not src_layer:
                continue
            base = prim.GetName()
            dst = mtl_parent.AppendChild(base)
            i = 1
            while meta_layer.GetPrimAtPath(dst):
                dst = mtl_parent.AppendChild(f"{base}_r{i}")
                i += 1
            Sdf.CopySpec(src_layer, src_path, meta_layer, dst)
            mat_remap[prim.GetPath()] = dst
            copied_mats += 1
            print(f"[meta][copy] {prim.GetPath()} -> {dst}")

    from pxr import UsdShade as _UsdShade
    rebind_count = 0
    subset_rebind_count = 0
    coll_rebind_count = 0

    for prim in stg.TraverseAll():
        if _UsdShade.MaterialBindingAPI.CanApply(prim):
            _ensure_over_prim(meta_layer, prim.GetPath())
            _UsdShade.MaterialBindingAPI.Apply(prim)
            mb = _UsdShade.MaterialBindingAPI(prim)
            rel = mb.GetDirectBindingRel()
            if rel:
                tgts = rel.GetTargets()
                if tgts:
                    old = tgts[0]
                    new = mat_remap.get(old, old)
                    if new != old:
                        print(f"[meta][bind] {prim.GetPath()} : {old} -> {new}")
                    else:
                        print(f"[meta][bind] {prim.GetPath()} : keep {old}")
                    try:
                        rel.ClearTargets(True)
                    except Exception:
                        pass
                    rel.SetTargets([new])
                    _set_strength_stronger(mb)
                    if prim.IsA(UsdGeom.Mesh):
                        prim.SetCustomDataByKey("materialBinding", new.pathString)
                    rebind_count += 1

        if prim.IsA(UsdGeom.Mesh):
            prim.SetCustomDataByKey("primNameTag", prim.GetName())
            imageable = UsdGeom.Imageable(prim)
            purpose_token = UsdGeom.Tokens.proxy if prim.GetName().endswith('_proxy') else UsdGeom.Tokens.render
            imageable.GetPurposeAttr().Set(purpose_token)
            print(f"[meta][purpose] {prim.GetPath()} set to {purpose_token}")

            mb_mesh = _UsdShade.MaterialBindingAPI(prim)
            for subset in mb_mesh.GetMaterialBindSubsets():
                _ensure_over_prim(meta_layer, subset.GetPath())
                _UsdShade.MaterialBindingAPI.Apply(subset)
                s_mb = _UsdShade.MaterialBindingAPI(subset)
                s_rel = s_mb.GetDirectBindingRel()
                if not s_rel:
                    continue
                s_tgts = s_rel.GetTargets()
                if not s_tgts:
                    continue
                s_old = s_tgts[0]
                s_new = mat_remap.get(s_old, s_old)
                if s_new != s_old:
                    print(f"[meta][subset] {subset.GetPath()} : {s_old} -> {s_new}")
                else:
                    print(f"[meta][subset] {subset.GetPath()} : keep {s_old}")
                try:
                    s_rel.ClearTargets(True)
                except Exception:
                    pass
                s_rel.SetTargets([s_new])
                _set_strength_stronger(s_mb)
                subset_rebind_count += 1

    for prim in stg.TraverseAll():
        for rel in prim.GetRelationships():
            name = rel.GetName()
            if not name.startswith('material:binding:collection'):
                continue
            _ensure_over_prim(meta_layer, prim.GetPath())
            _UsdShade.MaterialBindingAPI.Apply(prim)
            targets = rel.GetTargets()
            if len(targets) < 2:
                continue
            material_path, collection_path = None, None
            for tgt in targets:
                prim_tgt = stg.GetPrimAtPath(tgt)
                if prim_tgt and prim_tgt.IsA(_UsdShade.Material):
                    material_path = tgt
                else:
                    collection_path = tgt
            if not material_path or not collection_path:
                continue
            new_mat = mat_remap.get(material_path, material_path)
            if new_mat != material_path:
                print(f"[meta][collection] {prim.GetPath()}::{name} : {material_path} -> {new_mat}")
            else:
                print(f"[meta][collection] {prim.GetPath()}::{name} : keep {material_path}")
            try:
                rel.ClearTargets(True)
            except Exception:
                pass
            rel.SetTargets([collection_path, new_mat])
            coll_rebind_count += 1

    def _extract_filename_between_ats(v):
        try:
            from pxr import Sdf
            if isinstance(v, Sdf.AssetPath):
                return v.path or v.assetPath or None
        except Exception:
            pass
        if isinstance(v, str) and '@' in v:
            parts = v.split('@')
            if len(parts) >= 3:
                return parts[1] or None
        return None

    for prim in stg.TraverseAll():
        if prim.IsA(UsdShade.Material):
            for child in prim.GetChildren():
                if UsdShade.Shader(child):
                    shader = UsdShade.Shader(child)
                    inp = shader.GetInput("filename")
                    if inp:
                        attr = inp.GetAttr()
                        if attr and attr.HasAuthoredValueOpinion():
                            val = attr.Get()
                            extracted = _extract_filename_between_ats(val)
                            if extracted:
                                child.SetCustomDataByKey("inputs:filename_str", extracted)
                                print(f"[meta][shader] {child.GetPath()} filename_str='{extracted}'")

    meta_layer.Save()
    print(f"[USD] meta saved. copied {copied_mats} materials, "
          f"rebound {rebind_count} direct bindings, "
          f"{subset_rebind_count} subset bindings, "
          f"{coll_rebind_count} collection bindings.")


def _create_lod_usd(top_name, src, variant_dir, mask, lod_count=2, per_step_percent=50.0):
    from pxr import Sdf, Usd
    if not os.path.isdir(variant_dir):
        os.makedirs(variant_dir, exist_ok=True)

    lod_dup = cmds.duplicate(src, rr=True)[0]
    lod_dup = _safe_rename(lod_dup, f"{top_name}_LOD")

    lod_paths = []
    for i in range(lod_count):
        mesh_shapes = _non_intermediate_mesh_shapes_under(lod_dup)
        parents = sorted(_unique_parents_of_shapes(mesh_shapes), key=lambda p: p.count('|'))
        for p in parents:
            _reduce_with_cleanup(p, per_step_percent)

        lod_path = os.path.join(variant_dir, f"lod{i+1}.usdc").replace("\\", "/")
        cmds.select(lod_dup, r=True)
        cmds.arnoldExportAss(
            f=lod_path, selected=True, mask=mask,
            lightLinks=False, shadowLinks=False, expandProcedurals=True
        )
        lyr = Sdf.Layer.FindOrOpen(lod_path)
        stage = Usd.Stage.Open(lyr)
        prim = stage.GetPrimAtPath(f"/{top_name}_LOD")
        if prim:
            prim.SetCustomDataByKey("geo", top_name)
        lyr.Save()
        lod_paths.append(lod_path)
        print(f"[LOD] saved lod{i+1} to {lod_path}")

    try:
        cmds.delete(lod_dup)
    except Exception:
        pass

    return lod_paths


def _write_lod_wrap_layer(top_name, lod_path, meta_path, out_path):
    from pxr import Sdf, Usd
    out_path = out_path.replace("\\", "/")
    lod_path = lod_path.replace("\\", "/")
    meta_path = meta_path.replace("\\", "/")
    lyr = Sdf.Layer.CreateNew(out_path)
    if not lyr:
        raise RuntimeError(f"Cannot create LOD wrap layer: {out_path}")
    lyr.subLayerPaths = [meta_path]
    stg = Usd.Stage.Open(lyr)
    prim = stg.DefinePrim(f"/{top_name}", "Xform")
    prim.GetReferences().AddReference(lod_path, f"/{top_name}_LOD")
    stg.SetDefaultPrim(prim)
    stg.GetRootLayer().defaultPrim = top_name
    stg.GetRootLayer().Save()
    print(f"[wrap] wrote {out_path} (meta + {os.path.basename(lod_path)})")
    return out_path


def _create_variant_layer(top_name, payload_path, lod_wrap_paths, variant_path):
    from pxr import Usd, Sdf
    variant_path = variant_path.replace("\\", "/")
    lyr = Sdf.Layer.CreateNew(variant_path)
    if not lyr:
        raise RuntimeError(f"Cannot create variant layer: {variant_path}")
    stg = Usd.Stage.Open(lyr)
    prim = stg.DefinePrim(f"/{top_name}", "Xform")
    vset = prim.GetVariantSets().AddVariantSet("levels")

    # LOD0 = payload
    vset.AddVariant("LOD0")
    vset.SetVariantSelection("LOD0")
    with vset.GetVariantEditContext():
        prim.GetReferences().ClearReferences()
        prim.GetReferences().AddReference(payload_path, f"/{top_name}")

    # Subsequent LODs
    for i, wrap_path in enumerate(lod_wrap_paths):
        lod_name = f"LOD{i+1}"
        vset.AddVariant(lod_name)
        vset.SetVariantSelection(lod_name)
        with vset.GetVariantEditContext():
            prim.GetReferences().ClearReferences()
            prim.GetReferences().AddReference(wrap_path, f"/{top_name}")

    vset.SetVariantSelection("LOD0")
    stg.SetDefaultPrim(prim)
    stg.GetRootLayer().defaultPrim = top_name
    stg.GetRootLayer().Save()
    print(f"[variant] created {variant_path} with {len(lod_wrap_paths)+1} variants")
    return variant_path


# ------------------------------ Main exporter ------------------------------

def export_lookdev_with_payload_and_interface(
    add_proxy=True,
    reduce_percent=50.0,
    add_lods=True,
    lod_count=2,
    per_step_percent=50.0,
    stage_suffix="_stage",
):
    _ensure_mtoa()
    _ensure_maya_usd()

    hal_root = os.environ.get('HAL_TASK_ROOT', '')
    if not hal_root:
        cmds.error('HAL_TASK_ROOT is not set.')
        return None

    sel = cmds.ls(sl=True, long=True) or []
    if len(sel) != 1 or cmds.nodeType(sel[0]) != 'transform':
        cmds.error('Select exactly ONE top transform.')
        return None

    src = sel[0]
    top_name = src.split('|')[-1]

    maya_pub_root = os.path.join(hal_root, '_publish', 'maya')
    version, version_dir = _next_version_folder(maya_pub_root)
    version_dir = version_dir.replace('\\', '/')

    print(f"[Publish] HAL_TASK_ROOT: {hal_root}")
    print(f"[Publish] Version: {version} -> {version_dir}")

    shd_path     = f"{version_dir}/shd.usdc"
    proxy_path   = f"{version_dir}/proxy.usdc"
    payload_usdc = f"{version_dir}/payload.usdc"
    meta_usdc    = f"{version_dir}/meta.usdc"
    variant_dir  = os.path.join(version_dir, 'variant').replace('\\', '/')
    variant_usdc = f"{version_dir}/variant.usdc"
    top_usdc     = f"{version_dir}/{top_name}.usdc"

    import arnold
    mask = (arnold.AI_NODE_SHADER | arnold.AI_NODE_SHAPE | arnold.AI_NODE_COLOR_MANAGER)

    # 1) Export shd.usdc
    cmds.select(src, r=True)
    cmds.arnoldExportAss(f=shd_path, selected=True, mask=mask, lightLinks=False, shadowLinks=False, expandProcedurals=True)
    print(f"[Publish] wrote shd.usdc  : {shd_path}")

    # 2) Optional proxy.usdc
    if add_proxy:
        proxy_dup = _duplicate_and_reduce(src, suffix='_proxy', percent=reduce_percent)
        src_tmp = _safe_rename(src, f"{top_name}_origTmp")
        proxy_as_src = _safe_rename(proxy_dup, top_name)
        cmds.select(proxy_as_src, r=True)
        cmds.arnoldExportAss(f=proxy_path, selected=True, mask=mask, lightLinks=False, shadowLinks=False, expandProcedurals=True)
        print(f"[Publish] wrote proxy.usdc: {proxy_path}")
        proxy_restored = _safe_rename(proxy_as_src, f"{top_name}_proxy")
        _safe_rename(src_tmp, top_name)
        if cmds.objExists(proxy_restored):
            try:
                cmds.delete(proxy_restored)
            except Exception as e:
                print(f"[Cleanup][WARN] delete failed: {e}")
        try:
            renamed, skipped = _rename_nonmesh_parents_in_layer_with_sdf(proxy_path, suffix='_proxy')
            print(f"[USD] cleaned proxy parents: renamed={renamed}, skipped={skipped}")
        except Exception as e:
            print(f"[USD][WARN] proxy parent rename failed: {e}")
    else:
        proxy_path = shd_path  # fallback so payload still builds (no proxy)

    # 3) payload.usdc = [meta (prepended later), proxy, shd]
    _write_payload_contents_layer(top_name, proxy_path, shd_path, payload_usdc)

    # 4) Author meta (and prepend into payload)
    _author_meta_and_fix_materials(top_name, payload_usdc, meta_usdc)

    # 5) LODs (+ wraps) and variant.usdc
    final_target_for_top = payload_usdc
    lod_wrap_paths = []
    if add_lods and lod_count > 0:
        lod_paths = _create_lod_usd(top_name, src, variant_dir, mask, lod_count=lod_count, per_step_percent=per_step_percent)
        for i, lod_geo_path in enumerate(lod_paths):
            wrap_path = f"{variant_dir}/lod{i+1}_wrap.usdc"
            _write_lod_wrap_layer(top_name, lod_geo_path, meta_usdc, wrap_path)
            lod_wrap_paths.append(wrap_path)
        _create_variant_layer(top_name, payload_usdc, lod_wrap_paths, variant_usdc)
        final_target_for_top = variant_usdc

    # 6) Top interface **payloads the VARIANT file** so variants show up
    _write_interface_top_layer(top_name, final_target_for_top, top_usdc, add_geommodelapi=True)

    # 7) Preview in Maya
    stage_xf, stage_shape = _create_empty_usd_stage(f"{top_name}{stage_suffix}")
    try:
        cmds.setAttr(f"{stage_shape}.filePath", top_usdc, type="string")
    except Exception:
        cmds.setAttr(f"{stage_shape.split('|')[-1]}.filePath", top_usdc, type="string")
    cmds.select(stage_xf, r=True)

    out = {
        "version": version,
        "versionDir": version_dir,
        "shd": shd_path,
        "proxy": proxy_path if add_proxy else None,
        "payload": payload_usdc,
        "meta": meta_usdc,
        "variant": variant_usdc if lod_wrap_paths else None,
        "lodWraps": lod_wrap_paths,
        "topInterface": top_usdc,
        "stageXform": stage_xf,
        "topName": top_name,
    }
    print("[RESULT]", out)
    return out

# -----------------------------------------------------------------------------
# -- END: USD / Arnold helpers
# -----------------------------------------------------------------------------


def maya_main_window():
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QWidget)


def load_ui(ui_file):
    loader = QtUiTools.QUiLoader()
    file = QtCore.QFile(ui_file)
    if not file.open(QtCore.QFile.ReadOnly):
        raise RuntimeError(f"Cannot open UI file: {ui_file}")
    ui = loader.load(file)
    file.close()
    return ui


class PublishToolWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(540, 580)
        self.setWindowTitle("着色器发布工具")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        maya_menu_dir = os.path.dirname(script_dir)
        ui_file = os.path.join(maya_menu_dir, "QtWindows", "shader_publish_tool.ui")

        self.ui = load_ui(ui_file)
        self.setCentralWidget(self.ui)

        # === Menu: Open Project Folder ===
        # New UI uses actionOpen_Project_Folder_2 in the File menu.
        if hasattr(self.ui, "actionOpen_Project_Folder_2"):
            self.ui.actionOpen_Project_Folder_2.triggered.connect(self.open_project_folder)
        # Support older action name as well, if present.
        if hasattr(self.ui, "actionOpen_Project_Folder"):
            self.ui.actionOpen_Project_Folder.triggered.connect(self.open_project_folder)

        from ..utils.openHoudiniTool import execute as open_houdini
        self.ui.NameSpaceButton.clicked.connect(self.name_space_checking)
        self.ui.PublishInfoButton.clicked.connect(self.publish)
        self.ui.OpenHoudiniButton.clicked.connect(open_houdini)

        self.ui.proxyGroupBox.toggled.connect(self.sync_proxy_options)
        self.ui.lodGroupBox.toggled.connect(self.sync_lod_options)

        self.ui.proxyReduceSlider.valueChanged.connect(self.update_proxy_spinbox)
        self.ui.proxyReduceSpinBox.valueChanged.connect(self.update_proxy_slider)
        self.ui.lodReduceSlider.valueChanged.connect(self.update_lod_spinbox)
        self.ui.lodReduceSpinBox.valueChanged.connect(self.update_lod_slider)

    def sync_proxy_options(self, checked):
        for i in range(self.ui.proxyGroupBox.layout().count()):
            w = self.ui.proxyGroupBox.layout().itemAt(i).widget()
            if w:
                w.setVisible(checked)

    def sync_lod_options(self, checked):
        for i in range(self.ui.lodGroupBox.layout().count()):
            w = self.ui.lodGroupBox.layout().itemAt(i).widget()
            if w:
                w.setVisible(checked)

    def update_proxy_spinbox(self, v):
        self.ui.proxyReduceSpinBox.setValue(v / 10.0)

    def update_proxy_slider(self, v):
        self.ui.proxyReduceSlider.setValue(int(v * 10))

    def update_lod_spinbox(self, v):
        self.ui.lodReduceSpinBox.setValue(v / 10.0)

    def update_lod_slider(self, v):
        self.ui.lodReduceSlider.setValue(int(v * 10))

    def open_project_folder(self):
        """
        Opens HAL_TASK_ROOT in the OS file browser.
        If the path doesn't exist yet, it will be created first.
        """
        hal_task_root = os.environ.get("HAL_TASK_ROOT", "").strip()
        if not hal_task_root:
            QMessageBox.warning(self, "环境变量缺失", "未设置 HAL_TASK_ROOT，无法打开项目文件夹。")
            return

        # Normalize path separators for the current OS
        path = os.path.normpath(hal_task_root)

        # Create it if missing
        try:
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "创建失败", f"无法创建路径：\n{path}\n\n错误：{e}")
            return

        # Open in system file browser
        try:
            if sys.platform.startswith("win"):
                # Use explorer with absolute, quoted path
                subprocess.Popen(f'explorer "{path}"')
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(self, "打开失败", f"无法打开文件夹：\n{path}\n\n错误：{e}")

    def name_space_checking(self):
        selected = cmds.ls(sl=True)
        if not selected:
            cmds.warning("Please select a top-level group or any node in a shading network.")
            return
        all_nodes_to_check = set()
        for item in selected:
            all_nodes_to_check.add(item)
            if cmds.objectType(item, isType='transform'):
                descendants = cmds.listRelatives(item, allDescendents=True, fullPath=True) or []
                all_nodes_to_check.update(descendants)
                shapes = cmds.listRelatives(item, allDescendents=True, type='shape', fullPath=True) or []
                if shapes:
                    sgs = cmds.listConnections(shapes, type='shadingEngine')
                    if sgs:
                        for sg in set(sgs):
                            history = cmds.listHistory(sg) or []
                            all_nodes_to_check.update(history)
            else:
                history = cmds.listHistory(item) or []
                all_nodes_to_check.update(history)
        nodes_with_namespace = [node for node in all_nodes_to_check if ':' in node and cmds.objExists(node)]
        if not nodes_with_namespace:
            cmds.inViewMessage(msg="✅ 没有在所选物体或其关联网络中找到命名空间。", pos="topLeft", fade=True)
            return
        cleaned_count = 0
        for node in sorted(nodes_with_namespace, key=len, reverse=True):
            if ':' in node:
                try:
                    if cmds.objExists(node) and not cmds.lockNode(node, q=True)[0]:
                        clean_name = node.rpartition(':')[-1]
                        cmds.rename(node, clean_name)
                        cleaned_count += 1
                except Exception as e:
                    print(f"Warning: Could not rename node {node}. Reason: {e}")
        cmds.inViewMessage(msg=f"清理了 {cleaned_count} 个节点的命名空间。", pos="topLeft", fade=True)

    def auto_save_scene(self):
        try:
            current_file = cmds.file(q=True, sn=True)
            if not current_file:
                temp_dir = cmds.internalVar(userTmpDir=True)
                temp_path = os.path.join(temp_dir, "temp_publish_scene.ma")
                cmds.file(rename=temp_path)
            cmds.file(save=True, type='mayaAscii')
            return True
        except Exception as e:
            cmds.error(f"Auto save failed: {e}")
            return False

    def publish(self):
        if not self.auto_save_scene():
            return
        original_selection = cmds.ls(sl=True, long=True)
        if not original_selection or len(original_selection) != 1 or cmds.nodeType(original_selection[0]) != 'transform':
            QMessageBox.warning(self, "发布警告", "请只选择一个顶级变换组进行发布。")
            return
        try:
            add_proxy = self.ui.proxyGroupBox.isChecked()
            proxy_percent = self.ui.proxyReduceSpinBox.value()
            add_lods = self.ui.lodGroupBox.isChecked()
            lod_count = self.ui.lodCountSpinBox.value()
            per_step_percent = self.ui.lodReduceSpinBox.value()

            cmds.select(original_selection, r=True)
            publish_results = export_lookdev_with_payload_and_interface(
                add_proxy=add_proxy,
                reduce_percent=proxy_percent,
                add_lods=add_lods,
                lod_count=lod_count,
                per_step_percent=per_step_percent,
            )
            if not publish_results:
                raise RuntimeError("USD Arnold export did not return any results. Check the Maya script editor for errors.")

            version = publish_results['version']
            version_dir = publish_results['versionDir']
            top_interface_file = publish_results['topInterface']

            thumbnail_path = self._create_publish_thumbnail(top_interface_file)
            if not thumbnail_path:
                raise RuntimeError("Thumbnail generation failed. Aborting publish.")

            self.submit_to_shotgun(top_interface_file, thumbnail_path)
            ma_publish_path = self._publish_ma_scene(version, version_dir)
            self.submit_to_shotgun(ma_publish_path.replace(os.sep, "/"), thumbnail_path)

            QMessageBox.information(self, "发布成功", f"已成功发布USD资产和Maya场景。\n版本: {version}\n路径: {version_dir}")

        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "发布失败", f"发布过程中发生错误:\n{e}")
        finally:
            if original_selection and cmds.ls(original_selection):
                cmds.select(original_selection, r=True)

    def _publish_ma_scene(self, version, version_dir):
        print("\n=== Publishing Maya Scene ===")
        current_scene_path = cmds.file(q=True, sn=True)
        if not current_scene_path or not os.path.exists(current_scene_path):
            raise RuntimeError("The scene has not been saved. Cannot publish .ma file.")

        HAL_ASSET = os.environ.get("HAL_ASSET", "")
        HAL_SEQUENCE = os.environ.get("HAL_SEQUENCE", "")
        HAL_SHOT = os.environ.get("HAL_SHOT", "")
        HAL_TASK = os.environ.get("HAL_TASK", "")
        HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
        HAL_PROJECT_ABBR = os.environ.get("HAL_PROJECT_ABBR", "")
        HAL_USER_ABBR = os.environ.get("HAL_USER_ABBR", "")

        path_segments = re.split(r"[\\/]", HAL_TASK_ROOT)
        if "_library" in path_segments:
            file_name = f"{HAL_PROJECT_ABBR}_{HAL_ASSET}_{HAL_TASK}_{version}_{HAL_USER_ABBR}.ma"
        else:
            file_name = f"{HAL_PROJECT_ABBR}_{HAL_SEQUENCE}_{HAL_SHOT}_{HAL_TASK}_{version}_{HAL_USER_ABBR}.ma"

        ma_publish_path = os.path.join(version_dir, file_name)
        print(f"Copying current scene to publish location: {ma_publish_path}")
        shutil.copy2(current_scene_path, ma_publish_path)
        return ma_publish_path

    def _create_publish_thumbnail(self, representative_path):
        camera = None
        try:
            print("\n=== Starting thumbnail generation process ===")
            camera = camThumbnail.frame_all_top_level_objects_in_maya(spin_offset=45, pitch_offset=-20)
            if not camera or not cmds.objExists(camera):
                raise RuntimeError(f"Failed to create or find camera: {camera}")
            print(f"Created camera: {camera}")
            HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
            if not HAL_TASK_ROOT:
                raise RuntimeError("HAL_TASK_ROOT not set. Cannot create thumbnail.")
            basename = os.path.basename(representative_path)
            thumb_dir = os.path.join(HAL_TASK_ROOT, "_publish", "_SGthumbnail")
            os.makedirs(thumb_dir, exist_ok=True)
            thumb_name = os.path.splitext(basename)[0] + "_temp"
            thumb_path = os.path.join(thumb_dir, thumb_name).replace("\\", "/")
            cmds.lookThru(camera)
            cmds.playblast(
                filename=thumb_path, startTime=1001, endTime=1001,
                format='image', compression='png', quality=100, percent=100,
                widthHeight=(1920, 1080), showOrnaments=False, forceOverwrite=True,
                viewer=False, framePadding=4
            )
            final_path = thumb_path + ".1001.png"
            if not os.path.exists(final_path):
                raise RuntimeError(f"Playblast file was not created at {final_path}")
            print(f"Successfully created thumbnail at: {final_path}")
            return final_path
        except Exception as e:
            QMessageBox.warning(self, "Thumbnail Error", f"Could not create thumbnail:\n{e}")
            return None
        finally:
            print("Cleaning up temporary thumbnail camera...")
            cameras_to_delete = cmds.ls("defaultFramedCamera*", type='transform')
            if cameras_to_delete:
                cmds.delete(cameras_to_delete)
                print(f"Successfully cleaned up camera(s): {cameras_to_delete}")
            print("=== Thumbnail generation process completed ===")

    def submit_to_shotgun(self, asset_path, thumbnail_path):
        try:
            print(f"Creating Shotgun version for: {os.path.basename(asset_path)}")
            sg_manager = ShotgunDataManager()
            sg_manager.Create_SG_Version(thumbnail_path, asset_path)
            print("Successfully created Shotgun version.")
        except Exception as e:
            raise RuntimeError(f"Failed to submit {os.path.basename(asset_path)} to Shotgun: {e}")


SHADER_PUBLISH_TOOL_INSTANCE = None


def execute():
    global SHADER_PUBLISH_TOOL_INSTANCE
    UI_NAME = "ShaderPublishToolWindow"

    try:
        importlib.reload(sys.modules['mayaMenuBar.utils.camThumbnail'])
        importlib.reload(sys.modules['mayaMenuBar.utils.SGlogin'])
        importlib.reload(sys.modules[__name__])
    except Exception as e:
        print(f"Could not reload modules: {e}")

    if cmds.window(UI_NAME, exists=True):
        cmds.deleteUI(UI_NAME, window=True)

    parent = maya_main_window()
    SHADER_PUBLISH_TOOL_INSTANCE = PublishToolWindow(parent=parent)
    SHADER_PUBLISH_TOOL_INSTANCE.setObjectName(UI_NAME)
    SHADER_PUBLISH_TOOL_INSTANCE.show()
