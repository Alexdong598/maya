"""Command to load MM files with version browsing."""
import os
import re
import sys
import importlib
import subprocess
import maya.cmds as cmds
import maya.utils as utils
import maya.OpenMayaUI as omui
from PySide2 import QtWidgets, QtCore, QtGui
from PySide2.QtWidgets import QDialog, QMessageBox
from shiboken2 import wrapInstance

def maya_main_window():
    """Get Maya's main window as a parent widget."""
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)

class ImportTrackerFileDialog(QtWidgets.QDialog):
    _instance = None  # Singleton tracker

    def __init__(self, publish_path, parent=None):
        # Clean up existing instance completely
        if ImportTrackerFileDialog._instance:
            try:
                ImportTrackerFileDialog._instance.blockSignals(True)
                ImportTrackerFileDialog._instance.setParent(None)
                ImportTrackerFileDialog._instance.close()
                ImportTrackerFileDialog._instance.deleteLater()
                # Force Qt cleanup
                QtWidgets.QApplication.processEvents()  
            except Exception as e:
                print(f"Error cleaning up previous instance: {str(e)}")
            finally:
                ImportTrackerFileDialog._instance = None

        super().__init__(parent)
        ImportTrackerFileDialog._instance = self
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)

        # Window setup
        self.setWindowTitle("Import MM Files")
        self.setMinimumWidth(400)

        self.publish_path = publish_path
        self.all_files_data = self.get_sorted_files(self.publish_path)

        self.create_widgets()
        self.create_layouts()
        self.create_connections()
        self.update_file_list()

    def get_sorted_files(self, publish_path):
        """Get sorted list of MM files (newest first)"""
        if not os.path.isdir(publish_path):
            return []

        valid_exts = ('.abc', '.usd', '.usda', '.usdc')
        version_pattern = re.compile(r'v(\d{3,})', re.IGNORECASE)
        files_with_versions = []

        for filename in os.listdir(publish_path):
            full_path = os.path.join(publish_path, filename)
            if os.path.isfile(full_path):
                lower_name = filename.lower()
                matched_ext = next((ext for ext in valid_exts if lower_name.endswith(ext)), None)
                if matched_ext:
                    match = version_pattern.search(filename)
                    version_num = int(match.group(1)) if match else -1
                    file_type = "abc" if matched_ext == '.abc' else "usd"
                    files_with_versions.append((version_num, filename, file_type))

        files_with_versions.sort(key=lambda x: (-x[0], x[1].lower()))
        return files_with_versions

    def create_widgets(self):
        """Create UI widgets"""
        self.label = QtWidgets.QLabel("Select MM files to import:")
        self.format_combo = QtWidgets.QComboBox()
        self.format_combo.addItems(["abc", "usd"])
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list_widget.setMinimumSize(350, 200)
        self.import_button = QtWidgets.QPushButton("Import")
        self.cancel_button = QtWidgets.QPushButton("Cancel")

    def create_layouts(self):
        """Create UI layouts"""
        main_layout = QtWidgets.QVBoxLayout(self)
        top_layout = QtWidgets.QHBoxLayout()
        top_layout.addWidget(self.label)
        top_layout.addStretch()
        top_layout.addWidget(self.format_combo)
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.import_button)
        button_layout.addWidget(self.cancel_button)
        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.list_widget)
        main_layout.addLayout(button_layout)

    def create_connections(self):
        """Connect signals to slots"""
        self.format_combo.currentIndexChanged.connect(self.update_file_list)
        self.import_button.clicked.connect(self.import_selected_files)
        self.cancel_button.clicked.connect(self.reject)

    def update_file_list(self):
        """Update the file list based on selected format"""
        selected_format = self.format_combo.currentText()
        self.list_widget.clear()

        if not self.all_files_data:
            self.list_widget.addItem("No files found in publish directory.")
            self.list_widget.item(0).setEnabled(False)
            return

        found_files = False
        for version_num, filename, file_type in self.all_files_data:
            if file_type == selected_format:
                self.list_widget.addItem(filename)
                found_files = True

        if not found_files:
            self.list_widget.addItem(f"No '{selected_format}' files found.")
            self.list_widget.item(0).setEnabled(False)

    def import_selected_files(self):
        """Import the selected files"""
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return

        for item in selected_items:
            filename = item.text()
            full_path = os.path.join(self.publish_path, filename)
            try:
                if filename.lower().endswith('.abc'):
                    cmds.AbcImport(full_path, mode='import')
                elif filename.lower().endswith(('.usd', '.usda', '.usdc')):
                    if not cmds.pluginInfo("mayaUsdPlugin", q=True, loaded=True):
                        cmds.loadPlugin("mayaUsdPlugin", quiet=True)
                    cmds.file(full_path, i=True, type="USD Import")
            except Exception as e:
                print(f"Error importing {filename}: {str(e)}")

        self.accept()

    def closeEvent(self, event):
        """Clean up on window close"""
        try:
            self.blockSignals(True)
            self.setParent(None)
            ImportTrackerFileDialog._instance = None
            super().closeEvent(event)
            QtWidgets.QApplication.processEvents()
        except Exception as e:
            print(f"Error during window close: {str(e)}")

def get_command():
    """Return the current implementation of the command."""
    def _command():
        """Show import MM files dialog."""
        # Clean up existing instance
        if ImportTrackerFileDialog._instance:
            ImportTrackerFileDialog._instance.close()
            ImportTrackerFileDialog._instance.deleteLater()
        
        # Set up paths
        HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT")
        if not HAL_TASK_ROOT:
            cmds.warning("HAL_TASK_ROOT environment variable not set")
            return

        mm_dir = os.path.join(os.path.dirname(HAL_TASK_ROOT), "mm")
        publish_path = os.path.join(mm_dir, "_publish")

        if not os.path.isdir(publish_path):
            cmds.warning(f"Publish path does not exist: {publish_path}")
            return

        # Create and show dialog
        dialog = ImportTrackerFileDialog(publish_path)
        dialog.show()
    
    return _command

def execute():
    """Execute the command with reloading."""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()

if __name__ == '__main__':
    execute()
