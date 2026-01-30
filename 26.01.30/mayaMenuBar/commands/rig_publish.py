"""Rig publishing tool with Qt UI for Maya."""
import os
import sys
import re
import importlib
import subprocess
import maya.cmds as cmds
import maya.OpenMayaUI as omui
from PySide2 import QtWidgets, QtCore, QtUiTools
from PySide2.QtWidgets import QMainWindow, QMessageBox, QWidget
from shiboken2 import wrapInstance

from ..utils.exportABC import export_abc
from ..utils import camThumbnail
from ..utils.SGlogin import ShotgunDataManager


def maya_main_window():
    """Get Maya's main window as a parent widget."""
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QWidget)

def load_ui(ui_file):
    """Load UI file with error handling"""
    loader = QtUiTools.QUiLoader()
    file = QtCore.QFile(ui_file)
    if not file.open(QtCore.QFile.ReadOnly):
        raise RuntimeError(f"Cannot open UI file: {ui_file} (check path)")
    ui = loader.load(file)
    file.close()
    return ui

class RigPublishToolWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(420, 650)
        self.setWindowTitle("Rig Publish Tool")

        # Load UI file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        maya_menu_dir = os.path.dirname(script_dir)  # Go up to mayaMenuBar
        ui_file = os.path.join(maya_menu_dir, "QtWindows", "rig_publish_tool.ui")
        
        if not os.path.exists(ui_file):
            raise RuntimeError(f"UI file not found at: {ui_file}")
            
        self.ui = load_ui(ui_file)
        self.setCentralWidget(self.ui)

        # Set default publish options
        # Note: The UI might have USDCTag/USDATag, but the code maps them to ma/mb.
        # We assume the primary export for a rig is the Maya file itself.
        self.ui.USDATag.setChecked(True)
        
        # Connect menu actions
        self.ui.actionOpen_Project_Folder.triggered.connect(self.open_project_folder)
        self.ui.actionReset_Options.triggered.connect(self.reset_publish_options)

        # Connect all buttons
        self.ui.FreezeTransformButton.clicked.connect(self.check_freeze_transform)
        self.ui.NonDeformerHistoryButton.clicked.connect(self.check_non_deformer_history)
        self.ui.NameSpaceButton.clicked.connect(self.name_space_checking)
        self.ui.PublishInfoButton.clicked.connect(self.publish)

    def open_project_folder(self):
        """Open Windows Explorer at specified project path"""
        HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
        project_path = HAL_TASK_ROOT
        if not project_path:
            QMessageBox.warning(self, "Error", "HAL_TASK_ROOT environment variable not set.")
            return

        try:
            subprocess.Popen(f'explorer "{project_path}"')
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open folder:\n{str(e)}")

    def reset_publish_options(self):
        """Reset publish options to default"""
        self.ui.USDATag.setChecked(True)
        self.ui.USDCTag.setChecked(False)
        # If an Alembic checkbox exists in the UI, you can set its default here
        if hasattr(self.ui, 'AlembicTag'):
            self.ui.AlembicTag.setChecked(False)


    def check_freeze_transform(self):
        """Check if controllers and their children have frozen transforms"""
        selected = cmds.ls(sl=True)
        if not selected:
            cmds.warning("Please select controllers")
            return
            
        unfrozen = []
        for top_node in selected:
            all_nodes = cmds.listRelatives(top_node, allDescendents=True, fullPath=True) or []
            all_nodes.append(top_node)
            
            for node in all_nodes:
                if not cmds.objectType(node) == 'transform':
                    continue
                    
                translate = cmds.getAttr(f"{node}.translate")[0]
                rotate = cmds.getAttr(f"{node}.rotate")[0]
                scale = cmds.getAttr(f"{node}.scale")[0]
                
                if (any(abs(t) > 0.001 for t in translate) or 
                    any(abs(r) > 0.001 for r in rotate) or 
                    any(abs(s-1) > 0.001 for s in scale)):
                    unfrozen.append(node)
            
        if not unfrozen:
            QMessageBox.information(self, '冻结变换检查', '没有发现未冻结变换的节点')
            return
            
        print("Nodes with unfrozen transforms:")
        for node in unfrozen:
            print(f" - {node}")
            
        reply = QMessageBox.question(self, '冻结变换检查',
                                     f'已发现{len(unfrozen)}个未冻结变换的节点，是否要冻结它们?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            for node in unfrozen:
                cmds.makeIdentity(node, apply=True, t=1, r=1, s=1, n=0)
            cmds.inViewMessage(msg=f"已冻结{len(unfrozen)}个节点的变换", pos="topLeft", fade=True)

    def check_non_deformer_history(self):
        """Check for non-deformer history by examining input connections"""
        selected = cmds.ls(sl=True)
        if not selected:
            cmds.warning("Please select objects")
            return
            
        has_history = []
        for top_node in selected:
            all_nodes = cmds.listRelatives(top_node, allDescendents=True, fullPath=True, type="shape") or []
            
            for node in all_nodes:
                inputs = cmds.listHistory(node, pruneDagObjects=True)
                if inputs:
                    non_deformers = []
                    for input_node in inputs:
                        node_type = cmds.nodeType(input_node)
                        # Check if it's a deformer
                        is_deformer = cmds.nodeType(input_node, inherited=True)
                        if 'geometryFilter' not in is_deformer:
                             non_deformers.append(input_node)
                    
                    if non_deformers:
                        has_history.append((node, non_deformers))
            
        if not has_history:
            QMessageBox.information(self, '非变形历史检查', '没有发现非变形历史节点')
            return
            
        print("Nodes with non-deformer inputs:")
        for node, inputs in has_history:
            print(f" - {node}: {[cmds.nodeType(n) for n in inputs]}")
                
        reply = QMessageBox.question(self, '非变形历史检查',
                                     f'已发现{len(has_history)}个有非变形历史的节点，是否要清理它们?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            for node, inputs in has_history:
                cmds.delete(node, constructionHistory=True)
            cmds.inViewMessage(msg=f"已清理{len(has_history)}个节点的非变形历史", pos="topLeft", fade=True)

    def name_space_checking(self):
        """Check and clean namespaces"""
        selected = cmds.ls(sl=True)
        if not selected:
            cmds.warning("Please select top group")
            return
            
        has_namespace = False
        for top_grp in selected:
            all_objs = cmds.listRelatives(top_grp, allDescendents=True, fullPath=True) or []
            all_objs.append(top_grp)
            for obj in all_objs:
                if ':' in obj.split('|')[-1]:
                    has_namespace = True
                    break
            if has_namespace:
                break
                
        if not has_namespace:
            cmds.inViewMessage(msg="No namespaces found", pos="topLeft", fade=True)
            return
            
        cleaned = 0
        for obj in selected:
            if ':' in obj.split('|')[-1]:
                _, _, clean_name = obj.rpartition(':')
                cmds.rename(obj, clean_name)
                cleaned += 1
                obj = clean_name
                
            children = cmds.listRelatives(obj, allDescendents=True, fullPath=True) or []
            for child in children:
                if ':' in child.split('|')[-1]:
                    _, _, clean_child = child.rpartition(':')
                    cmds.rename(child, clean_child)
                    cleaned += 1
                    
        cmds.inViewMessage(msg=f"Cleaned {cleaned} namespaces", pos="topLeft", fade=True)

    def auto_save_scene(self):
        """Auto save the current scene"""
        try:
            current_file = cmds.file(q=True, sn=True)
            if not current_file:
                temp_dir = os.environ.get("TEMP", "/tmp")
                temp_file_path = os.path.join(temp_dir, "untitled_rig_publish_temp.ma")
                cmds.file(rename=temp_file_path)
                cmds.warning(f"Scene was unsaved, auto-saved to: {temp_file_path}")
            cmds.file(save=True, type='mayaAscii')
            return True
        except Exception as e:
            cmds.error(f"Auto save failed: {str(e)}")
            return False

    def publish(self):
        """Publish the rig"""
        if not self.auto_save_scene():
            return
            
        # Store original selection to restore before export
        original_selection = cmds.ls(sl=True, long=True)
        if not original_selection:
            QMessageBox.warning(self, "Publish Warning", "Please select top-level groups to publish!")
            return

        for obj in original_selection:
            if not cmds.objectType(obj) == 'transform':
                QMessageBox.warning(self, "Publish Warning", f"Selected object '{obj}' is not a group (transform)")
                return
            if cmds.listRelatives(obj, parent=True):
                QMessageBox.warning(self, "Publish Warning", f"Selected object '{obj}' is not top-level (has parent)")
                return

        selected_formats = []
        # NOTE: The UI element names (USDCTag, USDATag) might not match the format.
        # The code below determines the actual format exported.
        if self.ui.USDCTag.isChecked():
            selected_formats.append("ma")
        if self.ui.USDATag.isChecked():
            selected_formats.append("mb")
        # Add a check for an Alembic option if it exists in the UI
        if hasattr(self.ui, 'AlembicTag') and self.ui.AlembicTag.isChecked():
            selected_formats.append("abc")

        if not selected_formats:
            cmds.warning("Please select at least one format")
            return

        try:
            next_version = self.get_next_version()
            for fmt in selected_formats:
                # Restore original selection before each export
                cmds.select(original_selection, replace=True)
                self.export_path = self.get_publish_path(fmt, next_version)
                self.export_file(fmt, self.export_path)
            
            QMessageBox.information(
                self,
                "Publish Success",
                f"Published formats: {', '.join(selected_formats)}\nVersion: {next_version}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Publish Failed", f"Error during publish: {str(e)}")

    def get_next_version(self):
        """Get next version number for publishing"""
        publish_path = os.path.join(os.environ.get("HAL_TASK_ROOT", ""), "_publish")
        if not os.path.exists(publish_path):
            os.makedirs(publish_path, exist_ok=True)
            return "v001"

        files = [f for f in os.listdir(publish_path) 
                 if os.path.isfile(os.path.join(publish_path, f))]

        version_pattern = re.compile(r'v(\d{3,})', re.IGNORECASE)
        max_version = 0

        for filename in files:
            base_name = os.path.splitext(filename)[0]
            match = version_pattern.search(base_name)
            if match:
                version_num = int(match.group(1))
                if version_num > max_version:
                    max_version = version_num

        next_version = max_version + 1
        return f"v{next_version:03d}"

    def get_publish_path(self, fmt, version):
        """Get publish path for the rig"""
        publish_folder = "_publish"
        HAL_ASSET = os.environ.get("HAL_ASSET", "unknown_asset")
        HAL_TASK = os.environ.get("HAL_TASK", "unknown_task")
        HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
        HAL_PROJECT_ABBR = os.environ.get("HAL_PROJECT_ABBR", "UNK")
        HAL_USER_ABBR = os.environ.get("HAL_USER_ABBR", "User")

        if not HAL_TASK_ROOT:
            raise RuntimeError("HAL_TASK_ROOT environment variable not set or empty.")

        return os.path.join(
            HAL_TASK_ROOT,
            publish_folder,
            f"{HAL_PROJECT_ABBR}_{HAL_ASSET}_{HAL_TASK}_{version}_{HAL_USER_ABBR}.{fmt}"
        )

    def export_file(self, fmt, path):
        """Export the file in the specified format"""
        if fmt == "ma":
            cmds.file(path, force=True, type='mayaAscii', exportSelected=True)
        elif fmt == "mb":
            cmds.file(path, force=True, type='mayaBinary', exportSelected=True)
        # ======================================================================
        # FIXED: Added logic to call the Alembic exporter for a single, static frame.
        # ======================================================================
        elif fmt == "abc":
            # For a static rig, export only the current frame.
            current_frame = cmds.currentTime(q=True)
            print(f"Calling Alembic exporter for static rig at frame: {current_frame}")
            # The 'export_abc' function is now imported at the top of the file.
            export_abc(path, current_frame, current_frame)
        # ======================================================================

        # Submit playblast to Shotgun after the main file export
        self.create_and_submit_playblast(path)

    def create_and_submit_playblast(self, rig_path):
        """Create playblast and submit to Shotgun"""
        try:
            camera = None
            print("\n=== Starting playblast submission process ===")
            
            camera = camThumbnail.frame_all_top_level_objects_in_maya(spin_offset=45, pitch_offset=-20)
            if not camera or not cmds.objExists(camera):
                raise RuntimeError(f"Failed to create or find camera: {camera}")
            print(f"Created camera: {camera}")

            HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
            if not HAL_TASK_ROOT:
                cmds.warning("HAL_TASK_ROOT not set. Skipping playblast submission.")
                return

            basename = os.path.basename(rig_path)
            version_match = re.search(r'v(\d{3,})', basename, re.IGNORECASE)
            version = version_match.group(0) if version_match else "v001"

            thumb_dir = os.path.join(HAL_TASK_ROOT, "_publish", "_SGthumbnail")
            os.makedirs(thumb_dir, exist_ok=True)
            
            thumb_name = os.path.splitext(basename)[0] + "_temp"
            thumb_path = os.path.join(thumb_dir, thumb_name).replace("\\", "/")
            
            cmds.lookThru(camera)
            cmds.playblast(
                filename=thumb_path, startTime=1001, endTime=1001, format='image',
                compression='png', quality=100, percent=100, widthHeight=(1920, 1080),
                showOrnaments=False, forceOverwrite=True, viewer=False, framePadding=4
            )
            
            final_path = thumb_path + ".1001.png"
            if not os.path.exists(final_path):
                raise RuntimeError(f"Playblast file was not created at {final_path}")
            print(f"Successfully created playblast at: {final_path}")

            sg_manager = ShotgunDataManager()
            # Convert path to string representation for Shotgun API
            publish_path = str(self.export_path.replace(os.sep,"/"))
            sg_manager.Create_SG_Version(final_path, publish_path)
            
        except Exception as e:
            QMessageBox.warning(self, "Playblast/Shotgun Error", f"Could not create/submit playblast:\n{e}")
        finally:
            cameras = cmds.ls("defaultFramedCamera*", type='transform')
            if cameras:
                cmds.delete(cameras)
            print("=== Playblast submission process completed ===")

def get_command():
    """Return command implementation"""
    def _command():
        # Reload modules for development purposes
        try:
            importlib.reload(sys.modules['mayaMenuBar.utils.exportABC'])
            importlib.reload(sys.modules['mayaMenuBar.utils.camThumbnail'])
            importlib.reload(sys.modules[__name__])
        except Exception as e:
            print(f"Could not reload modules: {e}")
            
        window = RigPublishToolWindow(parent=maya_main_window())
        window.show()
    return _command

def execute():
    """Execute with reloading"""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()

if __name__ == "__main__":
    execute()
