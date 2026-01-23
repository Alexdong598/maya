"""Match Move publishing tool with Qt UI for Maya."""
import os
import sys
import importlib
import subprocess
import re
import maya.cmds as cmds
import maya.utils as utils
import maya.mel as mel
import maya.OpenMayaUI as omui
from PySide2 import QtWidgets, QtCore, QtUiTools
from PySide2.QtWidgets import QMainWindow, QMessageBox, QWidget
from shiboken2 import wrapInstance

# Import ShotgunDataManager class
from ..utils.SGlogin import ShotgunDataManager

# ==============================================================================
# Import modified Alembic export function
# ==============================================================================
from ..utils.exportABC import export_abc


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

class PublishToolWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(680, 400)
        self.setWindowTitle("Match Move Publish Tool")

        # Load UI file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        maya_menu_dir = os.path.dirname(script_dir)  # Go up to mayaMenuBar
        ui_file = os.path.join(maya_menu_dir, "QtWindows", "mm_publish_tool.ui")
        
        if not os.path.exists(ui_file):
            raise RuntimeError(f"UI file not found at: {ui_file}")
            
        self.ui = load_ui(ui_file)
        self.setCentralWidget(self.ui)

        # Connect menu actions
        self.ui.actionOpen_Project_Folder.triggered.connect(self.open_project_folder)
        self.ui.actionOpen_Playblast_Folder.triggered.connect(self.Open_Playblast_Folder)
        self.ui.actionReset_Options.triggered.connect(self.reset_publish_options)

        # Connect all buttons
        self.ui.UnusedShadeButton.clicked.connect(self.remove_unused_shade)
        self.ui.NameSpaceButton.clicked.connect(self.name_space_checking)
        self.ui.currentStartFrame.clicked.connect(self.set_current_start_frame)
        self.ui.currentEndFrame.clicked.connect(self.set_current_end_frame)
        self.ui.PublishInfoButton.clicked.connect(self.publish)
        self.ui.SGframeImport.clicked.connect(self.set_sg_frame_range)

        # --- ShotgunDataManager Initialization ---
        try:
            self.sg_manager = ShotgunDataManager()
        except Exception as e:
            QMessageBox.critical(self, "Shotgun Connection Error", 
                                 f"Failed to initialize Shotgun Data Manager: {str(e)}\n"
                                 "Publishing to Shotgun may not work correctly.")
            self.sg_manager = None
        # --- End ShotgunDataManager Initialization ---

    def open_project_folder(self):
        """Open Windows Explorer at specified project path"""
        HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
        project_path = HAL_TASK_ROOT
        try:
            subprocess.Popen(f'explorer "{project_path}"')
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open folder:\n{str(e)}")

    def Open_Playblast_Folder(self):
        """Open Windows Explorer at specified project path"""
        HAL_TASK_OUTPUT_ROOT = os.environ.get("HAL_TASK_OUTPUT_ROOT", "")
        project_path = f"{HAL_TASK_OUTPUT_ROOT}\\playblast"
        try:
            subprocess.Popen(f'explorer "{project_path}"')
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open folder:\n{str(e)}")

    def reset_publish_options(self):
        """Reset publish options"""
        pass  # No format options to reset for match move

    def remove_unused_shade(self):
        mel.eval('hyperShadePanelMenuCommand "hyperShadePanel1" "deleteUnusedNodes";')
        cmds.inViewMessage(msg="Unused shaders removed", pos="topLeft", fade=True)

    def name_space_checking(self):
        selected = cmds.ls(sl=True)
        if not selected:
            cmds.warning("Please select top group")
            return
            
        has_namespace = False
        for top_grp in selected:
            all_objs = cmds.listRelatives(top_grp, allDescendents=True, fullPath=True) or []
            all_objs.append(top_grp)
            for obj in all_objs:
                if ':' in obj:
                    has_namespace = True
                    break
            if has_namespace:
                break
                
        if not has_namespace:
            cmds.inViewMessage(msg="No namespaces found", pos="topLeft", fade=True)
            return
            
        cleaned = 0
        for obj in selected:
            if ':' in obj:
                _, _, clean_name = obj.rpartition(':')
                cmds.rename(obj, clean_name)
                cleaned += 1
                obj = clean_name
                
            children = cmds.listRelatives(obj, allDescendents=True, fullPath=True) or []
            for child in children:
                if ':' in child:
                    _, _, clean_child = child.rpartition(':')
                    cmds.rename(child, clean_child)
                    cleaned += 1
                    
        cmds.inViewMessage(msg=f"Cleaned {cleaned} namespaces", pos="topLeft", fade=True)

    def set_current_start_frame(self):
        """Set start frame from time slider"""
        start_frame = cmds.playbackOptions(q=True, min=True)
        self.ui.startFrameEdit.setText(str(int(start_frame)))

    def set_sg_frame_range(self):
        if self.sg_manager is None:
            QMessageBox.warning(self, "Shotgun Error", "Shotgun connection not established. Cannot import frame data.")
            return

        SHOTID = int(self.sg_manager.HAL_SHOT_SGID)
        frame_data = self.sg_manager.getSGData("Shot", SHOTID)
        sg_head_in = frame_data[0].get('sg_head_in', 'Not set')
        sg_tail_out = frame_data[0].get('sg_tail_out', 'Not set')
        sg_cut_in = frame_data[0].get('sg_cut_in', 'Not set')
        sg_cut_out = frame_data[0].get('sg_cut_out', 'Not set')

        if sg_head_in is not None:
            self.ui.startFrameEdit.setText(str(sg_head_in))
        elif sg_cut_in is not None:
            self.ui.startFrameEdit.setText(str(int(sg_cut_in)-8))
        else:
            self.ui.startFrameEdit.setText("None")

        if sg_tail_out is not None:
            self.ui.endFrameEdit_2.setText(str(sg_tail_out))
        elif sg_cut_out is not None:
            self.ui.endFrameEdit_2.setText(str(int(sg_cut_out)+8))
        else:
            self.ui.endFrameEdit_2.setText("None")

    def set_current_end_frame(self):
        """Set end frame from time slider"""
        end_frame = cmds.playbackOptions(q=True, max=True)
        self.ui.endFrameEdit_2.setText(str(int(end_frame)))

    def validate_frame_range(self):
        """Validate frame range inputs"""
        start_text = self.ui.startFrameEdit.text()
        end_text = self.ui.endFrameEdit_2.text()
        
        if not start_text or not end_text:
            QMessageBox.warning(self, "Error", "Please enter both start and end frame values")
            return False
            
        try:
            start_frame = int(start_text)
            end_frame = int(end_text)
        except ValueError:
            QMessageBox.warning(self, "Error", "Frame values must be integers")
            return False
            
        if start_frame >= end_frame:
            QMessageBox.warning(self, "Error", "End frame must be greater than start frame")
            return False
            
        return True

    def validate_camera_selection(self):
        """Validate that at least one camera is selected"""
        selected = cmds.ls(sl=True) or []
        cameras = [obj for obj in selected if cmds.objectType(obj) == 'camera' or 
                 cmds.listRelatives(obj, allDescendents=True, type='camera')]
        if not cameras:
            QMessageBox.warning(self, "Error", "Please select at least one camera for match move export")
            return False
        return True

    def auto_save_scene(self):
        try:
            current_file = cmds.file(q=True, sn=True)
            if not current_file:
                cmds.file(rename="untitled.ma")
            cmds.file(save=True, type='mayaAscii')
            return True
        except Exception as e:
            cmds.error(f"Auto save failed: {str(e)}")
            return False

    def publish(self):
        if not self.auto_save_scene():
            return
            
        if not self.validate_frame_range():
            return
            
        # Store original selection to restore before export
        original_selection = cmds.ls(sl=True, long=True)
        if not original_selection:
            QMessageBox.warning(self, "Publish Warning", "Please select top-level groups to publish!")
            return

        if not self.validate_camera_selection():
            return
            
        for obj in original_selection:
            if cmds.listRelatives(obj, parent=True):
                QMessageBox.warning(self, "Publish Warning", f"Selected object '{obj}' is not top-level (has parent)")
                return

        try:
            start_frame = int(self.ui.startFrameEdit.text())
            end_frame = int(self.ui.endFrameEdit_2.text())
            next_version = self.get_next_version()
            
            # Restore original selection before export
            cmds.select(original_selection, replace=True)
            export_path = self.get_publish_path("abc", next_version).replace(os.sep,"/")
            self.export_file(export_path, start_frame, end_frame)
            
            self.create_and_submit_thumbnail(start_frame, next_version)
            
            QMessageBox.information(
                self, 
                "Publish Success", 
                f"Published match move data as ABC\nVersion: {next_version}\nFrame range: {start_frame}-{end_frame}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Publish Failed", f"Error during publish: {str(e)}")

    def get_next_version(self):
        publish_path = os.path.join(os.environ.get("HAL_TASK_ROOT", ""), "_publish")
        if not os.path.exists(publish_path):
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
        publish_folder = "_publish"
        HAL_ASSET = os.environ.get("HAL_ASSET", "")
        HAL_SEQUENCE = os.environ.get("HAL_SEQUENCE", "")
        HAL_SHOT = os.environ.get("HAL_SHOT", "")
        HAL_TASK = os.environ.get("HAL_TASK", "")
        HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
        HAL_PROJECT_ABBR = os.environ.get("HAL_PROJECT_ABBR", "")
        HAL_USER_ABBR = os.environ.get("HAL_USER_ABBR", "")

        if not HAL_TASK_ROOT:
            raise RuntimeError("HAL_TASK_ROOT environment variable not set")

        path_segments = re.split(r"[\\/]", HAL_TASK_ROOT)
        if "_library" in path_segments:
            return os.path.join(
                HAL_TASK_ROOT,
                publish_folder,
                f"{HAL_PROJECT_ABBR}_{HAL_ASSET}_{HAL_TASK}_{version}_{HAL_USER_ABBR}.{fmt}"
            )
        else:
            return os.path.join(
                HAL_TASK_ROOT,
                publish_folder,
                f"{HAL_PROJECT_ABBR}_{HAL_SEQUENCE}_{HAL_SHOT}_{HAL_TASK}_{version}_{HAL_USER_ABBR}.{fmt}"
            )

    def create_and_submit_thumbnail(self, start_frame, version):
        """Create thumbnail and submit to ShotGrid"""
        if self.sg_manager is None:
            QMessageBox.warning(self, "Shotgun Error", "Shotgun connection not established. Cannot submit thumbnail.")
            return

        try:
            HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
            if not HAL_TASK_ROOT:
                QMessageBox.warning(self, "Error", "HAL_TASK_ROOT environment variable not set")
                return
            
            HAL_PROJECT_ABBR = os.environ.get("HAL_PROJECT_ABBR", "")
            HAL_SEQUENCE = os.environ.get("HAL_SEQUENCE", "")
            HAL_SHOT = os.environ.get("HAL_SHOT", "")
            HAL_TASK = os.environ.get("HAL_TASK", "")
            HAL_USER_ABBR = os.environ.get("HAL_USER_ABBR", "")

            thumb_dir = os.path.join(HAL_TASK_ROOT, "_publish", "_SGthumbnail")
            os.makedirs(thumb_dir, exist_ok=True)
            
            thumb_name = f"{HAL_PROJECT_ABBR}_{HAL_SEQUENCE}_{HAL_SHOT}_{HAL_TASK}_{version}_{HAL_USER_ABBR}_temp"
            thumb_path = os.path.join(thumb_dir, thumb_name).replace("\\", "/")
            
            cmds.playblast(
                filename=thumb_path,
                startTime=start_frame,
                endTime=start_frame,
                format='image',
                compression='png',
                quality=100,
                percent=100,
                widthHeight=(1920, 1080),
                showOrnaments=False,
                forceOverwrite=True,
                viewer=False,
                framePadding=4
            )
            
            final_path = f"{thumb_path}.{str(start_frame).zfill(4)}.png"
            
            # Convert path to string representation for Shotgun API
            fileExportPath = str(self.get_publish_path("abc", version).replace(os.sep,"/"))
            end_frame = int(self.ui.endFrameEdit_2.text())
            self.sg_manager.Create_SG_Version(final_path, fileExportPath, start_frame, end_frame)
            
        except Exception as e:
            QMessageBox.warning(self, "Thumbnail Warning", f"Could not create/submit thumbnail:\n{str(e)}")

    def export_file(self, path, start_frame, end_frame):
        """Export match move data as ABC"""
        print(f"Calling Alembic exporter for path: {path} with frame range: {start_frame}-{end_frame}")
        export_abc(path, start_frame, end_frame)

def get_command():
    def _command():
        try:
            importlib.reload(sys.modules['mayaMenuBar.utils.exportABC'])
            importlib.reload(sys.modules[__name__])
        except Exception as e:
            print(f"Could not reload modules: {e}")
            
        window = PublishToolWindow(parent=maya_main_window())
        window.show()
    return _command

def execute():
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()
