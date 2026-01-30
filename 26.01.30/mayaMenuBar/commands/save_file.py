import os
import re
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

class SaveSceneWindow(QDialog):
    def __init__(self, parent=maya_main_window()):
        super(SaveSceneWindow, self).__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("Save current scene")
        self.setMinimumSize(400, 300)

        # Get environment variables
        self.HAL_ASSET = os.environ.get("HAL_ASSET")
        self.HAL_SEQUENCE = os.environ.get("HAL_SEQUENCE")
        self.HAL_SHOT = os.environ.get("HAL_SHOT")
        self.HAL_TASK = os.environ.get("HAL_TASK")
        self.HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT")
        self.HAL_PROJECT_ABBR = os.environ.get("HAL_PROJECT_ABBR") or "UNK"
        self.HAL_USER_ABBR = os.environ.get("HAL_USER_ABBR") or "user"

        # UI components
        self.file_name_combo = QComboBox()
        self.comment_text = QTextEdit()
        self.comment_text.setPlaceholderText("--- insert comments in here ---")

        # Buttons
        self.save_btn = QPushButton("save new version")
        self.save_btn.clicked.connect(self.on_save_clicked)
        self.cancel_btn = QPushButton("cancel")
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)

        # Layout
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.file_name_combo)
        main_layout.addWidget(self.comment_text)
        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

        self.update_version_combo()

    def get_highest_version(self):
        """Get highest version number from existing .ma files"""
        if not self.HAL_TASK_ROOT:
            return 0

        max_version = 0
        path_parts = re.split(r"[\\/]", self.HAL_TASK_ROOT)
        is_library = "_library" in path_parts

        # Build pattern parts
        base_pattern = f"^{re.escape(self.HAL_PROJECT_ABBR)}_"
        asset_part = r"[\w-]+_"
        shot_part = r"[\w-]+_" if not is_library else ""
        task_part = f"{re.escape(self.HAL_TASK)}_"
        version_part = r"v(\d+)_"
        user_part = f"{re.escape(self.HAL_USER_ABBR)}\.ma$"
        
        # Combine into full pattern (removed user_part to find all versions regardless of user)
        full_pattern = base_pattern + asset_part + shot_part + task_part + version_part + r"[\w]+\.ma$"
        pattern = re.compile(full_pattern, re.IGNORECASE)

        if os.path.isdir(self.HAL_TASK_ROOT):
            for filename in os.listdir(self.HAL_TASK_ROOT):
                if filename.lower().endswith(".ma"):
                    match = pattern.match(filename)
                    if match:
                        try:
                            version = int(match.group(1))
                            if version > max_version:
                                max_version = version
                        except (ValueError, IndexError):
                            continue
        return max_version

    def update_version_combo(self):
        """Update combo with next available version"""
        self.file_name_combo.clear()
        highest_version = self.get_highest_version()
        next_version = highest_version + 1
        version_str = f"v{next_version:03d}"

        path_parts = re.split(r"[\\/]", self.HAL_TASK_ROOT)
        is_library = "_library" in path_parts

        if is_library:
            asset = self.HAL_ASSET or "asset"
            new_filename = f"{self.HAL_PROJECT_ABBR}_{asset}_{self.HAL_TASK}_{version_str}_{self.HAL_USER_ABBR}.ma"
        else:
            sequence = self.HAL_SEQUENCE or "seq"
            shot = self.HAL_SHOT or "shot"
            new_filename = f"{self.HAL_PROJECT_ABBR}_{sequence}_{shot}_{self.HAL_TASK}_{version_str}_{self.HAL_USER_ABBR}.ma"

        self.file_name_combo.addItem(new_filename)

    def on_save_clicked(self):
        """Handle save button click. Ensures project structure exists on every save."""
        if not self.HAL_TASK_ROOT:
            QMessageBox.warning(self, "Invalid Path", "HAL_TASK_ROOT environment variable is not set.")
            return

        target_filename = self.file_name_combo.currentText()
        absolute_path = os.path.join(self.HAL_TASK_ROOT, target_filename)
        project_dir = self.HAL_TASK_ROOT

        # --- Start of Modified Block ---
        # On every save, ensure the project directory structure exists.
        try:
            # Define primary folders and cache subfolders
            primary_folders = ["_workarea", "_sculpts", "cache", "geo", "scene"]
            cache_subfolders = ["alembic", "nCache", "particles"]

            # Create primary project folders
            for folder in primary_folders:
                folder_path = os.path.join(project_dir, folder)
                os.makedirs(folder_path, exist_ok=True)

            # Create subfolders inside the 'cache' directory
            cache_path = os.path.join(project_dir, "cache")
            for subfolder in cache_subfolders:
                subfolder_path = os.path.join(cache_path, subfolder)
                os.makedirs(subfolder_path, exist_ok=True)
                
            # Set the Maya workspace to the task root directory
            cmds.workspace(project_dir, o=True)

        except Exception as e:
            QMessageBox.critical(self, "Folder Creation Failed", 
                                 f"Could not create project directories in:\n{project_dir}\n\nError: {str(e)}")
            return
        # --- End of Modified Block ---

        # Save confirmation dialog
        confirm = QMessageBox.question(
            self,
            "Confirm Save",
            f"Are you sure you want to save the Maya file to:\n{absolute_path}",
            QMessageBox.Yes | QMessageBox.No
        )

        if confirm == QMessageBox.Yes:
            try:
                # Rename the current scene path and then save it
                cmds.file(rename=absolute_path)
                cmds.file(save=True, type="mayaAscii", force=True)
                QMessageBox.information(self, "Success", "File saved successfully!")
                self.close()
            except Exception as e:
                QMessageBox.critical(self, "Save Failed", f"Error saving file:\n{str(e)}")

    def on_cancel_clicked(self):
        """Handle cancel button click"""
        self.close()

def get_command():
    """Return the current implementation of the command."""
    def _command():
        """Show save scene dialog."""
        main_window = maya_main_window()
        # Clean up any existing windows
        existing_windows = main_window.findChildren(SaveSceneWindow)
        for window in existing_windows:
            window.close()
            window.deleteLater()
        
        # Create and show new window
        window = SaveSceneWindow()
        window.show()
    return _command

def execute():
    """Execute the command with reloading."""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()