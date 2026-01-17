# -*- coding: utf-8 -*-
"""
Shader Publishes (ASSETS/shd) – mini UI for Maya  (非阻塞)
- 与既有 ui.py 风格一致
- 仅保留 USD 系列格式：usd / usdc / usda
- 『选择指定USD路径并发布…』按钮；选择后 emit 路径并自动 close
- 缩略图修复：根据 _SGthumbnail/前缀.*.png 匹配
"""

import os, sys, re, traceback, importlib, ast, glob
from datetime import datetime
from PySide2 import QtWidgets, QtCore, QtGui

# -------------------- Maya 主窗口 --------------------
def _maya_main_window():
    try:
        from shiboken2 import wrapInstance
        import maya.OpenMayaUI as omui
        ptr = omui.MQtUtil.mainWindow()
        return wrapInstance(int(ptr), QtWidgets.QWidget) if ptr else None
    except Exception:
        return None

# -------------------- 依赖 --------------------
try:
    import shotgun_data_manager as sdm
    importlib.reload(sdm)
except Exception:
    sdm = None

# **只保留 USD 系列**
USD_EXTS = ("usd","usdc","usda")

def _expand_vars_and_norm(p):
    if not isinstance(p, str) or not p.strip(): return ""
    p = p.replace("\\", "/"); p = os.path.expandvars(p)
    for k, v in os.environ.items(): p = p.replace("%%%s%%" % k, v)
    p = os.path.normpath(p)
    if not os.path.isabs(p):
        try: p = os.path.abspath(p)
        except Exception: pass
    return p

def _flatten_and_clean_paths(data):
    if isinstance(data, str):
        data = data.strip()
        if (data.startswith('[') and data.endswith(']')) or (data.startswith('(') and data.endswith(')')):
            try: return _flatten_and_clean_paths(ast.literal_eval(data))
            except (ValueError, SyntaxError): return [_expand_vars_and_norm(data.strip('\'" '))]
        else: return [_expand_vars_and_norm(data.strip('\'" '))]
    elif isinstance(data, (list, tuple)):
        cleaned = []
        for item in data: cleaned.extend(_flatten_and_clean_paths(item))
        return cleaned
    return []

def _get_file_format(path):
    if not path or not isinstance(path, str): return "unknown"
    lower_path = path.lower()
    return lower_path.rsplit('.', 1)[-1] if '.' in lower_path else "unknown"

def _find_files_with_ext_recursive(root, exts):
    found_files = []
    try:
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                ext = _get_file_format(filename)
                if ext in exts:
                    found_files.append(os.path.join(dirpath, filename))
    except Exception:
        pass
    return found_files

def _best_file_match(files, version_code=""):
    if not files: return None
    files = [_expand_vars_and_norm(f) for f in files]
    vtag_match = re.search(r"(_v\d+)", version_code or "")
    if vtag_match:
        vtag = vtag_match.group(1)
        for f in files:
            if vtag in os.path.basename(f): return f
    return sorted(files, key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0, reverse=True)[0]

def _choose_path_for_version(version):
    paths = _flatten_and_clean_paths(version.get("sg_path_to_geometry"))
    code  = version.get("code", "")
    real = []
    for p in paths:
        if os.path.isdir(p):
            real.extend(_find_files_with_ext_recursive(p, USD_EXTS))
        elif _get_file_format(p) in USD_EXTS:
            real.append(p)
    if not real: return None
    return _best_file_match(real, version_code=code)

def _extract_version_from_path(path):
    if not path or not isinstance(path, str): return None
    m = re.search(r'[_./](v\d+)', path, re.IGNORECASE)
    return m.group(1) if m else None

def _wrap_path_for_label(p):
    if not p: return "N/A"
    return p.replace("\\", "\\\u200b").replace("/", "/\u200b")

# ---------- 缩略图查找 ----------
def _find_thumb_for_version(version):
    prefix = version.get("image")
    if not prefix:
        return None
    geo_paths = _flatten_and_clean_paths(version.get("sg_path_to_geometry"))
    for p in geo_paths:
        if not p:
            continue
        base_dir = p if os.path.isdir(p) else os.path.dirname(p)
        thumb_dir = os.path.join(base_dir, "_SGthumbnail")
        if not os.path.isdir(thumb_dir):
            parent = os.path.dirname(base_dir)
            alt = os.path.join(parent, "_SGthumbnail")
            thumb_dir = alt if os.path.isdir(alt) else thumb_dir
        if os.path.isdir(thumb_dir):
            pattern = os.path.join(thumb_dir, f"{prefix}.*.png")
            candidates = glob.glob(pattern)
            if candidates:
                candidates.sort(key=lambda f: os.path.getmtime(f), reverse=True)
                return candidates[0].replace("\\","/")
    return None


# -------------------- 缩略图卡片 --------------------
class ThumbItem(QtWidgets.QFrame):
    clicked = QtCore.Signal(object)
    BASE = "QFrame#ThumbItem{border:1px solid #555;background:#2a2a2a;border-radius:4px;} QLabel{color:#ccc;}"
    HOV  = "QFrame#ThumbItem{border:1px solid #777;background:#3a3a3a;border-radius:4px;} QLabel{color:#ccc;}"
    SEL  = "QFrame#ThumbItem{border:2px solid #427ab3;background:#404040;border-radius:4px;} QLabel{color:#fff;}"
    def __init__(self, version, thumb_size=(110,110), parent=None):
        super().__init__(parent); self.setObjectName("ThumbItem")
        self.version = version; self.thumb_size = thumb_size
        self._sel = False; self._hov = False
        self.setMouseTracking(True); self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self._build(); self.setFixedSize(self.sizeHint()); self._apply()
    def _build(self):
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(5,5,5,5); lay.setSpacing(2)
        self.thumb = QtWidgets.QLabel(); self.thumb.setFixedSize(*self.thumb_size); self.thumb.setAlignment(QtCore.Qt.AlignCenter)
        img_path = _find_thumb_for_version(self.version)
        if img_path and os.path.exists(img_path):
            pm = QtGui.QPixmap(img_path)
            if not pm.isNull():
                self.thumb.setPixmap(pm.scaled(self.thumb.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            else:
                self.thumb.setText("Invalid Image")
        else:
            self.thumb.setText("No Image")
        lay.addWidget(self.thumb)
        disp = self.version.get('display_name') or self.version.get('code', 'N/A')
        self.name = QtWidgets.QLabel(disp); self.name.setAlignment(QtCore.Qt.AlignCenter); self.name.setWordWrap(True)
        self.name.setToolTip(self.version.get('code', 'N/A')); self.name.setFixedWidth(self.thumb_size[0]); lay.addWidget(self.name)
    def sizeHint(self):
        label_h = self.name.sizeHint().height()
        w = self.thumb_size[0] + 10; h = self.thumb_size[1] + 10 + 2 + label_h
        return QtCore.QSize(w, h)
    def _apply(self):
        self.setStyleSheet(self.SEL if self._sel else (self.HOV if self._hov else self.BASE))
    def enterEvent(self, e): self._hov = True; self._apply(); super().enterEvent(e)
    def leaveEvent(self, e): self._hov = False; self._apply(); super().leaveEvent(e)
    def set_selected(self, sel): self._sel = bool(sel); self._apply()
    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton: self.clicked.emit(self.version)
        super().mousePressEvent(e)

# -------------------- 主 UI --------------------
class ShaderPublishMiniUI(QtWidgets.QWidget):
    pathSelected = QtCore.Signal(str)

    HAL_CATEGORY_TYPES = ["characters", "environments", "props", "vehicles", "cgfx"]
    THUMB_SIZES = [(90,90), (110,110), (140,140), (170,170)]
    DEFAULT_THUMB_IDX = 1

    def __init__(self, parent=None):
        super().__init__(parent or _maya_main_window())
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowMinimizeButtonHint |
                            QtCore.Qt.WindowMaximizeButtonHint | QtCore.Qt.WindowCloseButtonHint |
                            QtCore.Qt.Tool)
        self.setWindowTitle(u"Shader Publishes (ASSETS / shd)")
        self.resize(1200, 750)
        self.setMinimumSize(1100, 720)

        self._settings = QtCore.QSettings("HAL", "ShaderPublishMiniUI")
        if self._settings.value("size"):    self.resize(self._settings.value("size"))
        if self._settings.value("pos"):     self.move(self._settings.value("pos"))

        self.dm = None; self.thumb_size = self.THUMB_SIZES[self.DEFAULT_THUMB_IDX]
        self.all_versions_for_category = []; self.filtered_versions = []; self.history_for_selected_asset = []
        self._selected_thumb_widget = None
        self._rebuild_timer = QtCore.QTimer(self); self._rebuild_timer.setSingleShot(True); self._rebuild_timer.setInterval(120)
        self._rebuild_timer.timeout.connect(self._rebuild_left_grid)

        self._build_ui(); self._wire(); self._set_empty_left_panel()

    def _build_ui(self):
        self.main = QtWidgets.QHBoxLayout(self); self.main.setContentsMargins(6,6,6,6)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal); self.main.addWidget(self.splitter)

        # 左
        self.left = QtWidgets.QWidget(); lp = QtWidgets.QVBoxLayout(self.left); lp.setContentsMargins(0,0,0,0); lp.setSpacing(6)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Category:"))
        self.category_combo = QtWidgets.QComboBox(); self.category_combo.addItems(["<请选择>"] + self.HAL_CATEGORY_TYPES)
        top.addWidget(self.category_combo, 1)
        top.addSpacing(12); top.addWidget(QtWidgets.QLabel("Thumb Size:"))
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal); self.size_slider.setRange(0, len(self.THUMB_SIZES)-1); self.size_slider.setValue(self.DEFAULT_THUMB_IDX)
        top.addWidget(self.size_slider, 1)
        lp.addLayout(top)

        self.scroll = QtWidgets.QScrollArea(); self.scroll.setWidgetResizable(True)
        self.grid_host = QtWidgets.QWidget(); self.grid = QtWidgets.QGridLayout(self.grid_host)
        self.grid.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft); self.grid.setContentsMargins(10,10,10,10); self.grid.setSpacing(10)
        self.scroll.setWidget(self.grid_host); lp.addWidget(self.scroll, 1)

        tool = QtWidgets.QHBoxLayout()
        self.refresh_btn = QtWidgets.QPushButton("Refresh"); tool.addWidget(self.refresh_btn)
        tool.addStretch(1)
        self.cancel_btn = QtWidgets.QPushButton("取消选择"); tool.addWidget(self.cancel_btn)
        lp.addLayout(tool)
        self.splitter.addWidget(self.left)

        # 右
        self.right = QtWidgets.QWidget(); rp = QtWidgets.QVBoxLayout(self.right); rp.setContentsMargins(12,8,8,8)
        title = QtWidgets.QLabel("Options"); title.setAlignment(QtCore.Qt.AlignCenter); title.setStyleSheet("font-weight:bold;font-size:14px;"); rp.addWidget(title)
        form = QtWidgets.QFormLayout(); form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        # **格式筛选只保留 USD**
        self.format_combo  = QtWidgets.QComboBox()
        self.asset_combo   = QtWidgets.QComboBox(); self.asset_combo.setEnabled(False)
        self.version_combo = QtWidgets.QComboBox()
        form.addRow(u"格式筛选：", self.format_combo)
        form.addRow(u"资产筛选：", self.asset_combo)
        form.addRow(u"版本选择：", self.version_combo)

        self.file_path_label = QtWidgets.QLabel("N/A"); self.file_path_label.setWordWrap(True)
        self.file_path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        form.addRow(u"工程文件路径：", self.file_path_label)

        self.publish_date_label = QtWidgets.QLabel("N/A"); self.publish_date_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        form.addRow(u"Publish日期:", self.publish_date_label)

        self.search_edit = QtWidgets.QLineEdit(); self.search_edit.setPlaceholderText(u"按名称过滤… (可空格分隔)")
        form.addRow(u"名称筛选：", self.search_edit)

        rp.addLayout(form)

        btns = QtWidgets.QHBoxLayout()
        self.btn_pick_disk_and_publish = QtWidgets.QPushButton(u"选择指定USD路径并发布…")
        self.btn_confirm_current = QtWidgets.QPushButton(u"确认当前选择并发布")
        btns.addWidget(self.btn_pick_disk_and_publish)
        btns.addWidget(self.btn_confirm_current)
        btns.addStretch(1)
        rp.addLayout(btns)

        tool2 = QtWidgets.QHBoxLayout()
        self.copy_btn = QtWidgets.QPushButton(u"复制路径")
        self.open_btn = QtWidgets.QPushButton(u"打开所在文件夹")
        tool2.addWidget(self.copy_btn); tool2.addWidget(self.open_btn); tool2.addStretch(1)
        rp.addLayout(tool2)

        rp.addStretch(1)
        self.splitter.addWidget(self.right); self.splitter.setSizes([820, 380])

    def _wire(self):
        self.size_slider.valueChanged.connect(self._on_thumb_size_changed_debounced)
        self.size_slider.sliderReleased.connect(self._rebuild_left_grid)
        self.search_edit.textChanged.connect(self._apply_filters_and_rebuild_grid)
        self.refresh_btn.clicked.connect(self._refresh_category)
        self.cancel_btn.clicked.connect(self._clear_selection)
        self.copy_btn.clicked.connect(self._copy_path)
        self.open_btn.clicked.connect(self._open_folder)

        self.format_combo.currentIndexChanged.connect(self._update_dependent_filters)
        self.asset_combo.currentIndexChanged.connect(self._update_dependent_filters)
        self.version_combo.currentIndexChanged.connect(self._update_final_details)

        self.btn_pick_disk_and_publish.clicked.connect(self._pick_from_disk_and_publish)
        self.btn_confirm_current.clicked.connect(self._confirm_current_and_publish)

    # ---------- 数据/过滤 ----------
    def _set_empty_left_panel(self):
        while self.grid.count():
            it = self.grid.takeAt(0); w = it.widget(); w.setParent(None); w.deleteLater()
        lab = QtWidgets.QLabel(u"请选择 Category，然后点击 [Refresh] 加载数据。"); lab.setAlignment(QtCore.Qt.AlignCenter)
        self.grid.addWidget(lab, 0, 0, 1, 1); self._clear_right_panel(); self._selected_thumb_widget = None

    def _refresh_category(self):
        if not sdm:
            QtWidgets.QMessageBox.warning(self, "提示", "未找到 shotgun_data_manager.py；可用『选择指定USD路径并发布…』。"); return
        cat = self.category_combo.currentText()
        if not cat or cat == "<请选择>": self._set_empty_left_panel(); return
        try:
            self.dm = self.dm or sdm.ShotgunDataManager()
            vs = self.dm.find_files(f"shd/{cat}", entity_type="Asset")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, u"ShotGrid 错误", u"查询失败：\n{}".format(e)); return

        for v in vs: v['display_name'] = v.get('entity', {}).get('name', '') or v.get('code', 'N/A')
        self.all_versions_for_category = sorted(vs, key=lambda x: x.get("code", "").lower())
        self.search_edit.clear(); self._apply_filters_and_rebuild_grid()
        self._clear_right_panel(); self._selected_thumb_widget = None

    def _apply_filters_and_rebuild_grid(self):
        tokens = [t for t in (self.search_edit.text() or "").strip().lower().split() if t]
        if not tokens: self.filtered_versions = list(self.all_versions_for_category)
        else:
            self.filtered_versions = [v for v in self.all_versions_for_category if all(t in (v.get("code", "") or "").lower() for t in tokens)]
        self._rebuild_left_grid()

    def _rebuild_left_grid(self):
        while self.grid.count():
            it = self.grid.takeAt(0); w = it.widget(); w.setParent(None); w.deleteLater()
        self._selected_thumb_widget = None
        if not self.filtered_versions:
            lab = QtWidgets.QLabel(u"无匹配项。"); lab.setAlignment(QtCore.Qt.AlignCenter)
            self.grid.addWidget(lab, 0, 0, 1, 1); return
        cols = max(1, self.left.width() // (self.thumb_size[0] + 15))
        for i, v in enumerate(self.filtered_versions):
            w = ThumbItem(v, thumb_size=self.thumb_size, parent=self); w.clicked.connect(self._on_thumb_clicked)
            w.mouseDoubleClickEvent = lambda e, vv=v: (self._populate_right_filters(vv), self._confirm_current_and_publish())
            self.grid.addWidget(w, i // cols, i % cols)

    def resizeEvent(self, e): super().resizeEvent(e); QtCore.QTimer.singleShot(50, self._rebuild_left_grid)
    def _on_thumb_size_changed_debounced(self, idx): self.thumb_size = self.THUMB_SIZES[idx]; self._rebuild_timer.start()

    def _on_thumb_clicked(self, version_data):
        if self._selected_thumb_widget:
            try: self._selected_thumb_widget.set_selected(False)
            except RuntimeError: pass
        sender = self.sender()
        if isinstance(sender, ThumbItem): sender.set_selected(True); self._selected_thumb_widget = sender
        self._populate_right_filters(version_data)

    def _get_version_history_for_asset(self, version_data):
        if not self.dm or not getattr(self.dm, 'sg', None): return []
        entity = version_data.get('entity')
        if not entity or 'id' not in entity or 'type' not in entity: return []
        try:
            project_entity = {'type': 'Project', 'id': self.dm.HAL_PROJECT_SGID}
            return self.dm.sg.find(
                'Version',
                [['project','is',project_entity], ['entity','is',entity], ['code','contains','_shd_']],
                ['id','code','sg_path_to_geometry','entity','user','created_at','image'],
                order=[{'field_name':'created_at','direction':'desc'}]
            )
        except Exception as e:
            print(f"Failed to get version history: {e}"); traceback.print_exc(); return []

    def _populate_right_filters(self, base_version):
        self.history_for_selected_asset = self._get_version_history_for_asset(base_version)
        if not self.history_for_selected_asset: self._clear_right_panel(); return

        # 右侧“格式筛选”仅 USD
        all_formats = set()
        for v in self.history_for_selected_asset:
            paths = _flatten_and_clean_paths(v.get('sg_path_to_geometry'))
            v['sg_path_to_geometry'] = paths
            for path in paths:
                if os.path.isdir(path):
                    if _find_files_with_ext_recursive(path, USD_EXTS): all_formats.update(USD_EXTS)
                else:
                    ext = _get_file_format(path)
                    if ext in USD_EXTS: all_formats.add(ext)

        self.format_combo.blockSignals(True); self.format_combo.clear()
        ordered = [x for x in ("usdc","usd","usda") if x in all_formats] or list(USD_EXTS)
        self.format_combo.addItems(ordered); self.format_combo.blockSignals(False)
        self._update_dependent_filters()

    def _update_dependent_filters(self):
        if not self.history_for_selected_asset: return
        selected_format = self.format_combo.currentText() or "usdc"

        versions_in_format = []
        for v in self.history_for_selected_asset:
            # 只挑 USD 路径
            p = None
            paths = v.get('sg_path_to_geometry') or []
            real = []
            for path in paths:
                if os.path.isdir(path):
                    real.extend(_find_files_with_ext_recursive(path, USD_EXTS))
                elif _get_file_format(path) in USD_EXTS:
                    real.append(path)
            if real:
                # 同一版本下，格式优先级
                cand = [f for f in real if _get_file_format(f) == selected_format] or real
                p = _best_file_match(cand, version_code=v.get('code',''))
            if p:
                v['__chosen_path__'] = p; versions_in_format.append(v)

        assets_in_format = sorted(list({v.get('entity',{}).get('name','') for v in versions_in_format if v.get('entity')}))
        self.asset_combo.blockSignals(True); self.asset_combo.clear()
        if assets_in_format:
            self.asset_combo.setEnabled(True); self.asset_combo.addItems(assets_in_format)
        else:
            self.asset_combo.setEnabled(False); self.asset_combo.addItem("(无子资产)")
        self.asset_combo.blockSignals(False)

        selected_asset = self.asset_combo.currentText() if self.asset_combo.isEnabled() else None
        final_versions = [v for v in versions_in_format if (not selected_asset or v.get('entity',{}).get('name','') == selected_asset)]

        self.version_combo.blockSignals(True); self.version_combo.clear()
        for v in final_versions:
            code = v.get('code','N/A')
            vp = v.get('__chosen_path__')
            vtag = _extract_version_from_path(vp) if vp else None
            disp = re.sub(r'_v\d+', f'_{vtag}' if vtag else r'\g<0>', code, 1)
            self.version_combo.addItem(disp, userData=v)
        self.version_combo.blockSignals(False)
        self._update_final_details()

    def _update_final_details(self):
        data = self.version_combo.currentData()
        if not data:
            self.publish_date_label.setText("N/A"); self._update_file_path_label(); return
        created_at = data.get('created_at')
        self.publish_date_label.setText(created_at.strftime("%Y-%m-%d %H:%M") if created_at else "N/A")
        self._update_file_path_label()

    def _update_file_path_label(self):
        data = self.version_combo.currentData()
        if not data:
            self.file_path_label.setText("N/A"); return
        path = data.get('__chosen_path__') or _choose_path_for_version(data)
        self.file_path_label.setText(_wrap_path_for_label(path))

    def _clear_right_panel(self):
        for cb in (self.format_combo, self.asset_combo, self.version_combo):
            cb.blockSignals(True); cb.clear(); cb.blockSignals(False)
        self.asset_combo.setEnabled(False); self.file_path_label.setText("N/A"); self.publish_date_label.setText("N/A")

    # ---------- 选择并发布（都会 emit + close） ----------
    def _pick_from_disk_and_publish(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 USD 文件", "",
            "USD Files (*.usd *.usdc *.usda);;All Files (*)"
        )
        if not fn: return
        self.pathSelected.emit(fn.replace("\\","/"))
        QtCore.QTimer.singleShot(0, self.close)

    def _confirm_current_and_publish(self):
        data = self.version_combo.currentData()
        if not data:
            QtWidgets.QMessageBox.information(self, "提示", "当前没有可用版本。"); return
        p = data.get('__chosen_path__') or _choose_path_for_version(data)
        if not (p and os.path.isfile(p) and _get_file_format(p) in USD_EXTS):
            QtWidgets.QMessageBox.warning(self, "无效路径", "该选择没有有效的 USD 路径。"); return
        self.pathSelected.emit(p.replace("\\","/"))
        QtCore.QTimer.singleShot(0, self.close)

    # ---------- 便捷 ----------
    def _clear_selection(self):
        if self._selected_thumb_widget:
            try: self._selected_thumb_widget.set_selected(False)
            except RuntimeError: pass
        self._selected_thumb_widget = None; self._clear_right_panel()

    def _copy_path(self):
        raw = self.file_path_label.text().replace("\u200b", "")
        if not raw or raw == "N/A":
            QtWidgets.QMessageBox.information(self, "提示", "当前无有效路径。"); return
        QtWidgets.QApplication.clipboard().setText(raw); QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), "已复制")

    def _open_folder(self):
        raw = self.file_path_label.text().replace("\u200b", "")
        if not raw or raw == "N/A":
            QtWidgets.QMessageBox.information(self, "提示", "当前无有效路径。"); return
        path_to_open = raw if not os.path.isfile(raw) else os.path.dirname(raw)
        if not os.path.isdir(path_to_open):
            QtWidgets.QMessageBox.warning(self, "警告", f"找不到文件夹：\n{path_to_open}"); return
        if sys.platform.startswith("win"): os.startfile(path_to_open)
        elif sys.platform == "darwin": import subprocess; subprocess.call(["open", path_to_open])
        else: import subprocess; subprocess.call(["xdg-open", path_to_open])

    def resizeEvent(self, e): super().resizeEvent(e); QtCore.QTimer.singleShot(50, self._rebuild_left_grid)
    def _on_thumb_size_changed_debounced(self, idx): self.thumb_size = self.THUMB_SIZES[idx]; self._rebuild_timer.start()


# -------------------- 公共入口（非阻塞） --------------------
def show_for_publish(parent=None, on_select=None):
    """外部入口：不 exec_，返回窗口对象；on_select(path) 会在用户选择后被调用。"""
    dlg = ShaderPublishMiniUI(parent or _maya_main_window())
    if on_select: dlg.pathSelected.connect(on_select)
    dlg.setWindowModality(QtCore.Qt.NonModal)
    dlg.setModal(False) if hasattr(dlg, "setModal") else None
    dlg.show(); dlg.raise_(); dlg.activateWindow()
    return dlg

# 兼容老名字
def show(parent=None, on_select_callback=None, **_):
    return show_for_publish(parent=parent, on_select=on_select_callback)


if __name__ == "__main__":
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    win = show_for_publish()
    if not _maya_main_window():
        sys.exit(app.exec_())
