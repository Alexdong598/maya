# -*- coding: utf-8 -*-
import maya.cmds as cmds
import os
import shutil
import re
from PySide2 import QtWidgets, QtCore, QtGui

class PipelineTextureTool(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(PipelineTextureTool, self).__init__(parent)
        self.setWindowTitle("贴图一键归档工具dy (Auto Texture Repath) v3.0 [Debug Mode]")
        self.resize(500, 350)
        
        # Professional Dark Theme
        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; color: #e0e0e0; }
            QLabel { font-size: 14px; line-height: 140%; }
            QPushButton { 
                background-color: #5D8AA8; 
                color: white; 
                border-radius: 4px; 
                padding: 10px; 
                font-size: 15px; 
                font-weight: bold;
            }
            QPushButton:hover { background-color: #729fcf; }
            QPushButton#cancel_btn { background-color: #505050; }
            QPushButton#cancel_btn:hover { background-color: #606060; }
        """)
        
        self.create_ui()

    def create_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        title_label = QtWidgets.QLabel("一键整理贴图 (Auto Texture Repath)")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title_label)

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        line.setStyleSheet("color: #444;")
        layout.addWidget(line)

        intro_text = (
            "此工具会将模型贴图（含 UDIM 序列）整理到项目标准目录。\n"
            "(Moves textures & UDIM sequences to project folder.)\n\n"
            "执行步骤 (Steps)：\n"
            "1. 📦 **Deep Search**: Scans source folder using `os.listdir`.\n"
            "2. 🔍 **Regex Pattern**: Auto-detects 1001/1002 sequences.\n"
            "3. 📝 **Logging**: Detailed logs will appear in Script Editor.\n\n"
            "请选中模型，然后点击下方按钮。"
        )
        
        info_label = QtWidgets.QLabel(intro_text)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #cccccc;") 
        layout.addWidget(info_label)

        layout.addStretch()

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setSpacing(15)
        
        self.btn_cancel = QtWidgets.QPushButton("取消 (Cancel)")
        self.btn_cancel.setObjectName("cancel_btn")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_run = QtWidgets.QPushButton("开始整理 (Start)")
        self.btn_run.clicked.connect(self.run_pipeline_logic)
        
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_run)
        
        layout.addLayout(btn_layout)

    def run_pipeline_logic(self):
        self.accept()
        
        print("\n" + "="*60)
        print("STARTING TEXTURE PIPELINE PROCESS")
        print("="*60)

        # --- ENV CHECK ---
        asset_root = os.environ.get('HAL_ASSET_ROOT')
        if not asset_root:
            print("!! Error: HAL_ASSET_ROOT not set.")
            QtWidgets.QMessageBox.critical(None, 'Pipeline Error', '错误：环境变量 HAL_ASSET_ROOT 缺失。')
            return

        target_dir = os.path.join(asset_root, 'txt').replace('\\', '/')
        print(f"Target Directory: {target_dir}")

        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir)
                print(f"Created Target Directory: {target_dir}")
            except OSError as e:
                print(f"!! Error creating directory: {e}")
                QtWidgets.QMessageBox.critical(None, 'Error', f'无法创建文件夹:\n{e}')
                return

        # --- SELECTION & TRAVERSAL ---
        selection = cmds.ls(selection=True, long=True)
        if not selection:
            print("!! Nothing selected.")
            QtWidgets.QMessageBox.warning(None, '提示', '请先选择模型 (Please select objects).')
            return

        # Improved Traversal Logic (Mesh -> Shape -> ShadingEngine -> Shader -> File)
        unique_files = set()
        
        # 1. Get Shapes from selection
        shapes = cmds.listRelatives(selection, allDescendents=True, type='shape', fullPath=True) or []
        for sel in selection:
            # Handle if user selected the shape directly or a transform
            if cmds.nodeType(sel) == 'mesh':
                shapes.append(sel)
            child_shapes = cmds.listRelatives(sel, shapes=True, fullPath=True) or []
            shapes.extend(child_shapes)
            
        shapes = list(set(shapes))
        
        if not shapes:
            print("!! No shapes found in selection.")
            QtWidgets.QMessageBox.information(None, '提示', 'No mesh shapes found.')
            return

        # 2. Get Shading Engines
        sgs = cmds.listConnections(shapes, type='shadingEngine') or []
        sgs = list(set(sgs))

        # 3. Get Files from Shading Engines History
        if sgs:
            history = cmds.listHistory(sgs)
            files = cmds.ls(history, type=['file', 'aiImage'])
            for f in files:
                unique_files.add(f)
        
        if not unique_files:
            print("!! No file nodes found connected to materials.")
            QtWidgets.QMessageBox.information(None, '提示', '未找到贴图节点 (No textures found).')
            return

        print(f"Found {len(unique_files)} unique file nodes to process.")

        # --- PROCESSING ---
        cmds.waitCursor(state=True)
        
        processed_count = 0
        stats = {'copy': 0, 'error': 0, 'skip': 0, 'relink': 0}

        try:
            for node in unique_files:
                print(f"\n--- Inspecting Node: {node} ---")
                
                # 1. Get Path
                node_type = cmds.nodeType(node)
                attr_name = "fileTextureName" if node_type == 'file' else "filename"
                full_attr = f"{node}.{attr_name}"
                
                raw_path = cmds.getAttr(full_attr)
                # Expand env vars immediately
                source_path = os.path.expandvars(raw_path).replace('\\', '/')

                print(f"Raw Path: {raw_path}")
                print(f"Resolved Path: {source_path}")

                if not source_path:
                    print("!! Path is empty. Skipping.")
                    continue

                source_dir = os.path.dirname(source_path)
                filename = os.path.basename(source_path)

                # 2. Scan Source Directory
                if not os.path.exists(source_dir):
                    print(f"!! Source directory missing: {source_dir}")
                    stats['error'] += 1
                    continue

                try:
                    all_source_files = os.listdir(source_dir)
                    print(f"[DEBUG] Scanning Source Dir. Found {len(all_source_files)} files.")
                except Exception as e:
                    print(f"!! Error listing source directory: {e}")
                    stats['error'] += 1
                    continue

                # 3. Identify UDIM Sequence using Regex
                # Pattern: Looks for .1001. or _1001_ or similar
                match = re.search(r'[._](\d{4})[._]', filename)
                files_to_copy = []

                if match:
                    udim_number = match.group(1) # e.g. "1001"
                    escaped_name = re.escape(filename)
                    # Replace 1001 with \d{4} to match siblings
                    pattern_str = escaped_name.replace(udim_number, r'\d{4}')
                    pattern = re.compile(pattern_str, re.IGNORECASE)
                    
                    print(f"[LOGIC] UDIM Detected. Pattern: {pattern_str}")
                    
                    for f in all_source_files:
                        if pattern.search(f):
                            files_to_copy.append(f)
                else:
                    # No sequence, check for single file
                    print("[LOGIC] Single file (No UDIM pattern).")
                    if filename in all_source_files:
                        files_to_copy.append(filename)

                if not files_to_copy:
                    print("!! No matching files found in source folder.")
                    stats['error'] += 1
                    continue

                print(f"[ACTION] Found {len(files_to_copy)} files to copy.")

                # 4. Copy Files
                for fname in files_to_copy:
                    src_full = os.path.join(source_dir, fname)
                    dst_full = os.path.join(target_dir, fname)
                    
                    # Log the copy attempt
                    print(f"   -> Copying: {fname}")
                    
                    try:
                        shutil.copy2(src_full, dst_full)
                        stats['copy'] += 1
                    except Exception as e:
                        print(f"   !! FAILED: {e}")
                        stats['error'] += 1

                # 5. Relink Maya Node
                # We always point the Maya node to the file in the new directory.
                # Usually we point it to the '1001' version or the original filename version.
                new_path = os.path.join(target_dir, filename).replace('\\', '/')
                
                if raw_path != new_path:
                    try:
                        cmds.setAttr(full_attr, new_path, type="string")
                        stats['relink'] += 1
                        print(f"   [RELINK] Updated node path to: {new_path}")
                    except Exception as e:
                        print(f"   !! Relink failed: {e}")

        except Exception as final_e:
            cmds.waitCursor(state=False)
            print(f"CRITICAL ERROR: {final_e}")
            QtWidgets.QMessageBox.critical(None, 'Critical Error', str(final_e))
            return
            
        cmds.waitCursor(state=False)

        # Final Scan of Destination
        print("\n" + "="*60)
        print("FINAL VERIFICATION")
        try:
            dest_content = os.listdir(target_dir)
            print(f"Destination now contains {len(dest_content)} files.")
            # print(f"Files: {dest_content}") # Uncomment if you want a huge list
        except:
            pass
        print("="*60 + "\n")

        msg = (
            f"✅ Process Complete!\n\n"
            f"Files Copied: {stats['copy']}\n"
            f"Nodes Relinked: {stats['relink']}\n"
            f"Errors: {stats['error']}\n\n"
            f"Check Script Editor for detailed logs."
        )

        QtWidgets.QMessageBox.information(None, 'Result', msg)

def get_maya_window():
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() == 'MayaWindow': return widget
    return None

def execute():
    if cmds.window("pipelineTexToolWin", exists=True):
        cmds.deleteUI("pipelineTexToolWin")
    global tool_ui 
    tool_ui = PipelineTextureTool(parent=get_maya_window())
    tool_ui.setObjectName("pipelineTexToolWin")
    tool_ui.show()

# # Run
# execute()