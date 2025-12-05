# -*- coding: utf-8 -*-
"""
Quick Shader Picker (mini)
- 从当前选择解析 ns -> 映射到 shd/<category>，锁定 entity
- 查询该 asset 的所有 shd 版本（新→旧），只显示 USD/usdc/usda 路径
- 迷你 UI：顶部信息 + 仅 5 行表格 + 底部工具（复制路径/打开文件夹/刷新/确认）
- 非阻塞；选中后 emit 路径并关闭
"""

import os, re, sys, traceback
import maya.cmds as cmds
from PySide2 import QtWidgets, QtCore, QtGui
from shiboken2 import wrapInstance
import maya.OpenMayaUI as omui

# ---------- studio vocab ----------
ASSET_TYPES = ["mdl", "shd", "rig", "txt", "cgfx-setup", "cgfx", "cncpt", "assy"]
SHOT_TYPES  = ["anim", "cgfx", "comp", "layout", "lgt", "mm", "matp", "paint", "roto", "assy"]
MAP_TO_SHD  = {"rig", "mdl", "cgfx-setup", "cgfx"}
CATEGORY_ABBREVIATIONS = {'characters':'chr', 'environments':'env', 'props':'prp', 'vehicles':'veh', 'cgfx':'cgfx'}
ABBR_TO_CATEGORY = {v:k for k,v in CATEGORY_ABBREVIATIONS.items()}
USD_EXTS = (".usd", ".usdc", ".usda")

def _maya_main_window():
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget) if ptr else None

def _canon(s):
    s = (s or "").strip().lower()
    return re.sub(r'[_\-]', '', s)

def _selected_namespace_token():
    sel = cmds.ls(sl=True, l=True) or []
    if not sel: return ""
    leaf = sel[0].split("|")[-1]
    ns = leaf.rpartition(":")[0]
    parts = [p for p in ns.split(":") if p]
    return parts[-1] if parts else ns

def _extract_asset_and_task(last_token):
    tokens = sorted(set(ASSET_TYPES + SHOT_TYPES), key=len, reverse=True)
    m = re.search(r"_(%s)_" % "|".join(map(re.escape, tokens)), last_token)
    if not m:
        base = re.split(r"_v\d+", last_token)[0]
        task=""; asset_with_prefix=base
    else:
        task = m.group(1); asset_with_prefix = last_token[:m.start()]
    cat_abbr = None
    for ab in sorted(ABBR_TO_CATEGORY.keys(), key=len, reverse=True):
        if asset_with_prefix.startswith(ab+"_"):
            cat_abbr = ab; break
    asset_basename = asset_with_prefix[len(cat_abbr)+1:] if cat_abbr else asset_with_prefix
    return asset_with_prefix, task, cat_abbr, asset_basename

def _entity_matches_name(entity_name, cat_abbr, asset_basename):
    en = _canon(entity_name)
    no_prefix = _canon(asset_basename)
    if cat_abbr:
        with_prefix = _canon(f"{cat_abbr}_{asset_basename}")
        return en==no_prefix or en==with_prefix
    return en==no_prefix

def _flatten_paths(x):
    if not x: return []
    if isinstance(x, str): return [x]
    if isinstance(x, (list, tuple)):
        out=[]; [out.extend(_flatten_paths(i)) for i in x]; return out
    return []

def _first_usd(paths):
    for p in _flatten_paths(paths):
        if isinstance(p, str) and p.lower().endswith(USD_EXTS):
            return p.replace("\\","/")
    return ""

def _get_sgdm():
    for modpath, attr in (("utils.SGlogin","ShotgunDataManager"),
                          ("shotgun_data_manager","ShotgunDataManager")):
        try:
            m = __import__(modpath, fromlist=[attr])
            return getattr(m, attr)()
        except Exception:
            pass
    print("[QuickPicker] ShotgunDataManager 导入失败"); return None

def _find_entity_and_versions(dm):
    """解析选择 → 锁定 entity；并拿到它的 shd 版本（新→旧）"""
    token = _selected_namespace_token()
    if not token:
        return None, [], "请选择一个带命名空间的节点"
    _awp, task, cat_abbr, asset_basename = _extract_asset_and_task(token)
    if task in MAP_TO_SHD: task="shd"
    category = ABBR_TO_CATEGORY.get(cat_abbr or "", "cgfx")

    # 先通过 context 快速拉一批版本，再精确定位 entity
    print(f"Applying Shotgun filters based on context: {task or 'shd'}/{category} for entity type: Asset")
    filters = [
        ['project','is', {'type':'Project','id': int(dm.HAL_PROJECT_SGID)}],
        ['sg_path_to_geometry','is_not', None],
        ['entity','type_is','Asset'],
        ['code','contains','_shd_'],
    ]
    if cat_abbr:
        filters.append({'filter_operator':'all','filters':[
            ['code','contains', cat_abbr],
            ['code','contains', 'shd'],
        ]})
    fields = ['id','code','sg_path_to_geometry','image','created_at','user','entity']
    try:
        vers = dm.sg.find('Version', filters, fields, order=[{'field_name':'created_at','direction':'desc'}]) or []
    except Exception as e:
        return None, [], f"查询失败: {e}"

    with_geo = [v for v in vers if _flatten_paths(v.get('sg_path_to_geometry'))]
    print(f"Found {len(with_geo)} versions with geometry paths after Shotgun filtering.")

    entity = None
    for v in with_geo:
        ent = (v.get('entity') or {})
        if _entity_matches_name(ent.get('name',''), cat_abbr, asset_basename):
            entity = ent; break
    if not entity:
        return None, [], "未命中该资产（shd）"

    # 真正拿该资产所有 shd 版本（新→旧）
    filters2 = [
        ['project','is', {'type':'Project','id': int(dm.HAL_PROJECT_SGID)}],
        ['entity','is', entity],
        ['code','contains','_shd_'],
    ]
    try:
        all_shd = dm.sg.find('Version', filters2, fields, order=[{'field_name':'created_at','direction':'desc'}]) or []
        return entity, all_shd, ""
    except Exception as e:
        return entity, [], f"取资产所有 shd 版本失败：{e}"

class QuickShaderPickerMini(QtWidgets.QDialog):
    pathSelected = QtCore.Signal(str)  # 发射 USD 路径

    def __init__(self, parent=None):
        super().__init__(parent or _maya_main_window())
        self.setWindowTitle("Quick Shader Picker – mini")
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.resize(960, 360)

        self.dm = _get_sgdm()
        self.entity = None
        self.versions = []   # 仅用于展示（新→旧）
        self._build_ui()
        self._wire()
        self.refresh_from_selection()

    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(8,8,8,8); lay.setSpacing(8)
        self.info = QtWidgets.QLabel("等待刷新…"); self.info.setStyleSheet("font-weight:600;")
        lay.addWidget(self.info)

        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Version", "Created", "User", "USD Path"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        for col in (0,1,2):
            self.table.horizontalHeader().setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)

        # 高度锁定为 5 行
        fm = self.table.fontMetrics()
        approx_row_h = fm.height() + 10
        header_h = self.table.horizontalHeader().height()
        target_h = header_h + approx_row_h * 5 + 6
        self.table.setMinimumHeight(target_h); self.table.setMaximumHeight(target_h)
        lay.addWidget(self.table, 1)

        tool = QtWidgets.QHBoxLayout()
        self.btn_copy = QtWidgets.QPushButton("复制路径")
        self.btn_open = QtWidgets.QPushButton("打开文件夹")
        tool.addWidget(self.btn_copy); tool.addWidget(self.btn_open); tool.addStretch(1)
        self.btn_refresh = QtWidgets.QPushButton("刷新（当前选择）")
        self.btn_ok = QtWidgets.QPushButton("确认使用并发布")
        self.btn_cancel = QtWidgets.QPushButton("取消")
        tool.addWidget(self.btn_refresh); tool.addWidget(self.btn_ok); tool.addWidget(self.btn_cancel)
        lay.addLayout(tool)

        self.status = QtWidgets.QLabel(""); self.status.setStyleSheet("color:#888;")
        lay.addWidget(self.status)

    def _wire(self):
        self.btn_refresh.clicked.connect(self.refresh_from_selection)
        self.btn_copy.clicked.connect(self.copy_selected)
        self.btn_open.clicked.connect(self.open_selected_folder)
        self.btn_ok.clicked.connect(self._use_selected)
        self.btn_cancel.clicked.connect(self.close)
        self.table.itemSelectionChanged.connect(self._update_status)
        # 双击直接确定
        self.table.itemDoubleClicked.connect(lambda *_: self._use_selected())

    def refresh_from_selection(self):
        if not self.dm:
            QtWidgets.QMessageBox.warning(self, "ShotGrid", "无法初始化 ShotgunDataManager。"); return
        try:
            ent, all_shd, tip = _find_entity_and_versions(self.dm)
            if tip: print(tip)
            self.entity = ent
            # 只保留带 USD 路径的版本（取该版本中的首个 USD）
            rows=[]
            for v in all_shd:
                usd = _first_usd(v.get('sg_path_to_geometry'))
                if usd:
                    rows.append((v, usd))
            self.versions = rows
            asset_name = ent.get('name') if ent else "Unknown"
            self.info.setText(f"资产：{asset_name} | USD 版本：{len(rows)}（新→旧）")
            self._rebuild_table()
        except Exception:
            traceback.print_exc()
            self.entity=None; self.versions=[]; self._rebuild_table()
            self.info.setText("刷新失败，请查看脚本编辑器输出。")

    def _rebuild_table(self):
        self.table.setRowCount(0)
        for v, usd in self.versions:
            r = self.table.rowCount(); self.table.insertRow(r)
            code = v.get('code','N/A')
            created = v.get('created_at'); created_str = created.strftime("%Y-%m-%d %H:%M") if created else "N/A"
            user = (v.get('user') or {}).get('name') or 'unknown'

            it_code = QtWidgets.QTableWidgetItem(code); it_code.setToolTip(code)
            it_time = QtWidgets.QTableWidgetItem(created_str)
            it_user = QtWidgets.QTableWidgetItem(user)
            it_path = QtWidgets.QTableWidgetItem(usd); it_path.setToolTip(usd)
            self.table.setItem(r,0,it_code); self.table.setItem(r,1,it_time)
            self.table.setItem(r,2,it_user); self.table.setItem(r,3,it_path)
        if self.versions: self.table.selectRow(0)
        self._update_status()

    def _selected_row(self):
        idxs = self.table.selectedIndexes()
        return idxs[0].row() if idxs else -1

    def _cur_usd(self):
        r = self._selected_row()
        if r<0: return ""
        it = self.table.item(r, 3)
        return (it.text() or "").strip() if it else ""

    def copy_selected(self):
        p = self._cur_usd()
        if not p:
            QtWidgets.QMessageBox.information(self, "复制路径", "请选择一个带 USD 路径的条目。"); return
        QtWidgets.QApplication.clipboard().setText(p)
        self.status.setText("已复制路径到剪贴板。")

    def open_selected_folder(self):
        p = self._cur_usd()
        if not p:
            QtWidgets.QMessageBox.information(self, "打开文件夹", "请选择一个带 USD 路径的条目。"); return
        folder = p if os.path.isdir(p) else os.path.dirname(p)
        if not os.path.isdir(folder):
            QtWidgets.QMessageBox.warning(self, "打开文件夹", f"找不到文件夹：\n{folder}"); return
        if sys.platform.startswith("win"): os.startfile(folder)
        elif sys.platform == "darwin":
            import subprocess; subprocess.call(["open", folder])
        else:
            import subprocess; subprocess.call(["xdg-open", folder])
        self.status.setText(f"已打开：{folder}")

    def _use_selected(self):
        p = self._cur_usd()
        if not (p and p.lower().endswith(USD_EXTS)):
            QtWidgets.QMessageBox.information(self, "提示", "请选择一个有效的 USD/usdc/usda 路径。"); return
        print(f"[QuickPicker] Selected USD: {p}")
        self.pathSelected.emit(p)
        QtCore.QTimer.singleShot(0, self.close)

    def _update_status(self):
        self.status.setText("已选择 1 条" if self._selected_row()>=0 else "未选择。")

def show_quick_shader_picker(parent=None, on_select=None):
    dlg = QuickShaderPickerMini(parent or _maya_main_window())
    if on_select: dlg.pathSelected.connect(on_select)
    dlg.setWindowModality(QtCore.Qt.NonModal)
    dlg.show(); dlg.raise_(); dlg.activateWindow()
    return dlg
