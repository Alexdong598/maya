"""Command to open Maya scene with version browsing."""
import os
import re
import datetime
import maya.cmds as cmds
import maya.OpenMayaUI as omui
from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
from shiboken2 import wrapInstance
import importlib
import sys

def maya_main_window():
    """Get Maya's main window as a parent widget."""
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QWidget)

class OpenSceneWindow(QDialog):
    _instance = None  # Singleton tracker

    def __init__(self, parent=maya_main_window()):
        # Clean up existing instance completely
        if OpenSceneWindow._instance:
            try:
                OpenSceneWindow._instance.blockSignals(True)
                OpenSceneWindow._instance.setParent(None)
                OpenSceneWindow._instance.close()
                OpenSceneWindow._instance.deleteLater()
                # Force Qt cleanup
                QApplication.processEvents()  
            except Exception as e:
                print(f"Error cleaning up previous instance: {str(e)}")
            finally:
                OpenSceneWindow._instance = None

        super().__init__(parent)
        OpenSceneWindow._instance = self
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        # Window setup
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowFlags((self.windowFlags() | Qt.Dialog) & ~Qt.WindowStaysOnTopHint)
        self.setWindowModality(Qt.NonModal)
        self.setWindowTitle("Open existing scene")
        self.setMinimumSize(400, 300)

        # Environment variables
        self.HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT")
        self.HAL_PROJECT_ABBR = os.environ.get("HAL_PROJECT_ABBR") or "UNK"
        self.HAL_USER_ABBR = os.environ.get("HAL_USER_ABBR") or "user"

        # UI Components
        self.file_name_combo = QComboBox()
        self.file_info_text = QTextEdit()
        self.file_info_text.setPlaceholderText("--- file information will show here ---")
        self.file_info_text.setReadOnly(True)

        self.load_btn = QPushButton("Load Selected File")
        self.load_btn.clicked.connect(self.on_load_clicked)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)

        # Layout
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.load_btn)
        btn_layout.addWidget(self.cancel_btn)

        main_layout = QVBoxLayout()
        main_layout.addWidget(QLabel("Available .ma files:"))
        main_layout.addWidget(self.file_name_combo)
        main_layout.addWidget(QLabel("File info:"))
        main_layout.addWidget(self.file_info_text)
        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

        # Initialize
        self.update_file_list()
        self.file_name_combo.currentIndexChanged.connect(self.update_file_info)

    def get_existing_ma_files(self):
        """Get sorted list of .ma files (newest first) from all users"""
        ma_files = []
        if not self.HAL_TASK_ROOT or not os.path.isdir(self.HAL_TASK_ROOT):
            return ma_files

        for filename in os.listdir(self.HAL_TASK_ROOT):
            if filename.lower().endswith(".ma"):
                # Include all .ma files regardless of HAL_USER_ABBR
                ma_files.append(filename)
        
        # Sort by version (newest first)
        def version_sorter(f):
            match = re.search(r"v(\d+)", f)
            return int(match.group(1)) if match else 0
        return sorted(ma_files, key=version_sorter, reverse=True)

    def update_file_list(self):
        """Refresh file list in combo box"""
        self.file_name_combo.clear()
        ma_files = self.get_existing_ma_files()
        
        if not ma_files:
            self.file_name_combo.addItem("No .ma files found in HAL_TASK_ROOT")
            self.file_info_text.clear()
            return

        self.file_name_combo.addItems(ma_files)
        if ma_files:
            self.file_name_combo.setCurrentIndex(0)
            self.update_file_info()

    def update_file_info(self):
        """Show file details in text edit"""
        selected_file = self.file_name_combo.currentText()
        if "No .ma files found" in selected_file:
            self.file_info_text.clear()
            return

        file_path = os.path.join(self.HAL_TASK_ROOT, selected_file)
        if not os.path.isfile(file_path):
            self.file_info_text.clear()
            return

        try:
            file_stats = os.stat(file_path)
            modified_time = datetime.datetime.fromtimestamp(file_stats.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            
            info = [
                f"File: {selected_file}",
                f"Path: {file_path}",
                f"Size: {file_stats.st_size / 1024:.2f} KB",
                f"Modified: {modified_time}"
            ]
            
            version_match = re.search(r"v(\d+)", selected_file)
            if version_match:
                info.append(f"Version: {version_match.group(0)}")
            
            # Show original user who saved the file
            user_match = re.search(r"_([^_]+)\.ma$", selected_file)
            if user_match:
                info.append(f"Saved by: {user_match.group(1)}")
            
            self.file_info_text.setText("\n".join(info))
        except Exception as e:
            self.file_info_text.setText(f"Error reading file info: {str(e)}")

    def on_load_clicked(self):
        """Handle load button click"""
        if not self.HAL_TASK_ROOT:
            QMessageBox.warning(self, "Invalid Path", "HAL_TASK_ROOT environment variable is not set")
            return

        selected_file = self.file_name_combo.currentText()
        if "No .ma files found" in selected_file:
            return

        absolute_path = os.path.join(self.HAL_TASK_ROOT, selected_file)
        if not os.path.isfile(absolute_path):
            QMessageBox.warning(self, "File Not Found", f"File does not exist:\n{absolute_path}")
            return

        # --- REMOVED: Redundant newFile call ---
        # cmds.file(newFile=True, force=True) # This was already done in open_new_file()

        # --- Temporarily set environment variable to skip failed plugin loads ---
        # This can prevent crashes if the file uses plugins you don't have.
        original_skip_env = os.environ.get('MAYA_SKIP_FAILED_PLUGIN_LOAD', None)
        os.environ['MAYA_SKIP_FAILED_PLUGIN_LOAD'] = '1'

        # --- REMOVED/COMMENTED OUT: Suppressing warnings might hide diagnostics ---
        # cmds.scriptEditorInfo(suppressWarnings=True)
        # cmds.scriptEditorInfo(suppressInfo=True)

        try:
            # Open target file
            try:
                cmds.file(absolute_path, open=True, force=True)
                QMessageBox.information(self, "Success", "File opened successfully!")

                # After opening, check for unknown nodes (if any plugins were skipped)
                unknown_nodes = cmds.ls(type='unknown')
                if unknown_nodes:
                    # Instead of a message box, print to Script Editor and console
                    print(f"// Warning: File opened with {len(unknown_nodes)} unknown nodes. Missing plugins?")
                    # Optionally, list the unknown nodes for more detail
                    # print(f"// Unknown nodes found: {unknown_nodes}")

            except Exception as e:
                QMessageBox.critical(self, "Load Failed", f"Error opening file:\n{str(e)}\nCheck Script Editor for details.")
                # raise # Consider re-raising if needed

        finally:
            # --- Restore original environment variable state ---
            if original_skip_env is not None:
                os.environ['MAYA_SKIP_FAILED_PLUGIN_LOAD'] = original_skip_env
            else:
                del os.environ['MAYA_SKIP_FAILED_PLUGIN_LOAD']

            # --- Keep these commented out unless you explicitly want to suppress ALL warnings/info ---
            # cmds.scriptEditorInfo(suppressWarnings=False)
            # cmds.scriptEditorInfo(suppressInfo=False)

            self.close()




    def on_cancel_clicked(self):
        """Handle cancel button click"""
        self.close()

    def closeEvent(self, event):
        """Clean up singleton reference and Qt resources"""
        try:
            self.blockSignals(True)
            self.setParent(None)
            OpenSceneWindow._instance = None
            super().closeEvent(event)
            # Force Qt cleanup
            QApplication.processEvents()
        except Exception as e:
            print(f"Error during window close: {str(e)}")

def open_new_file():
    """Handle unsaved changes and create new scene"""
    if cmds.file(query=True, modified=True):
        result = cmds.confirmDialog(
            title='Unsaved Changes',
            message='Do you want to save the current scene?',
            button=['Save', 'Discard', 'Cancel'],
            defaultButton='Save',
            cancelButton='Cancel',
            dismissString='Cancel'
        )

        if result == 'Save':
            current_file = cmds.file(query=True, sceneName=True)
            if not current_file:
                save_path = cmds.fileDialog2(
                    fileFilter="Maya ASCII (*.ma);;Maya Binary (*.mb)",
                    dialogStyle=2,
                    fileMode=0,
                    caption="Save As"
                )
                if not save_path:
                    return False
                cmds.file(rename=save_path[0])
                file_type = 'mayaBinary' if save_path[0].endswith('.mb') else 'mayaAscii'
                if not cmds.file(save=True, type=file_type):
                    return False
            else:
                if not cmds.file(save=True):
                    return False
        elif result == 'Cancel':
            return False

    # Suppress warnings during new file creation
    cmds.scriptEditorInfo(suppressWarnings=True)
    cmds.scriptEditorInfo(suppressInfo=True)
    
    try:
        cmds.file(newFile=True, force=True)
        return True
    except Exception as e:
        print(f"Error creating new scene: {str(e)}")
        return False
    finally:
        cmds.scriptEditorInfo(suppressWarnings=False)
        cmds.scriptEditorInfo(suppressInfo=False)

def get_command():
    """Return the current implementation of the command."""
    def _command():
        """Show open scene dialog."""
        # First handle current scene state
        if not open_new_file():
            return
            
        # Clean up existing instance
        if OpenSceneWindow._instance:
            OpenSceneWindow._instance.close()
            OpenSceneWindow._instance.deleteLater()
        
        # Create and show new window
        window = OpenSceneWindow()
        window.show()
    return _command

def execute():
    """Execute the command with reloading."""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()
