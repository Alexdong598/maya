"""Asset publishing tool with Qt UI for Maya."""
import os
import sys
import importlib
import subprocess
import re
import shutil  # 导入 shutil 用于文件复制
import maya.cmds as cmds
import maya.utils as utils
import maya.mel as mel
import maya.OpenMayaUI as omui
from PySide2 import QtWidgets, QtCore, QtUiTools
from PySide2.QtWidgets import QMainWindow, QMessageBox, QWidget
from shiboken2 import wrapInstance

from ..utils import camThumbnail
from ..utils.SGlogin import ShotgunDataManager

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
        self.resize(430, 946)
        self.setWindowTitle("Asset Publish Tool")

        # Load UI file
        script_dir = os.path.dirname(os.path.abspath(__file__))
        maya_menu_dir = os.path.dirname(script_dir)  # Go up to mayaMenuBar
        ui_file = os.path.join(maya_menu_dir, "QtWindows", "asset_publish_tool.ui")
        
        if not os.path.exists(ui_file):
            raise RuntimeError(f"UI file not found at: {ui_file}")
            
        self.ui = load_ui(ui_file)
        self.setCentralWidget(self.ui)

        # Set default publish options
        self.ui.USDCTag.setChecked(True)
        self.ui.AlembicTag.setChecked(True)
        
        # Connect menu actions
        self.ui.actionOpen_Project_Folder.triggered.connect(self.open_project_folder)
        self.ui.actionReset_Options.triggered.connect(self.reset_publish_options)

        # Connect all buttons
        self.ui.AboveToGridButton.clicked.connect(self.move_above_ground)
        self.ui.OriginalPivotButton.clicked.connect(self.original_pivot)
        self.ui.CleanHistoryButton.clicked.connect(self.clean_history_and_transform)
        self.ui.UnusedShadeButton.clicked.connect(self.remove_unused_shade)
        
        # Connect model check buttons
        from ..utils.NgonAndManifold import execute as check_ngon_manifold
        self.ui.NgonAndManifold.clicked.connect(check_ngon_manifold)
        
        # Connect UV check buttons
        from ..utils.checkUVOverlap import execute as check_uv_overlap
        from ..utils.checkUVFlip import execute as check_uv_flip
        from ..utils.UVCrossAndNegative import execute as check_uv_cross_negative
        from ..utils.openHoudiniTool import execute as open_houdini
        from ..utils.openMayaTool import execute as open_maya
        
        self.ui.UVOverlap.clicked.connect(check_uv_overlap)
        self.ui.UVFlip.clicked.connect(check_uv_flip)
        self.ui.UVCross.clicked.connect(check_uv_cross_negative)
        self.ui.NameSpaceButton.clicked.connect(self.name_space_checking)
        self.ui.PublishInfoButton.clicked.connect(self.publish)
        self.ui.OpenHoudiniButton.clicked.connect(open_houdini)
        self.ui.OpenMayaButton.clicked.connect(open_maya)

    def open_project_folder(self):
        """Open Windows Explorer at specified project path"""
        HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
        project_path = HAL_TASK_ROOT
        try:
            subprocess.Popen(f'explorer "{project_path}"')
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open folder:\n{str(e)}")

    def reset_publish_options(self):
        """Reset publish options to default (USDC and Alembic checked)"""
        self.ui.USDCTag.setChecked(True)
        self.ui.USDATag.setChecked(False)
        self.ui.AlembicTag.setChecked(True)
        self.ui.OBJTag.setChecked(False)

    def original_pivot(self):
        selected = cmds.ls(sl=True)
        if not selected:
            cmds.warning("Please select top group")
            return
            
        processed = 0
        for top_obj in selected:
            all_objs = cmds.listRelatives(top_obj, allDescendents=True, fullPath=True) or []
            all_objs.append(top_obj)
            
            for obj in all_objs:
                if cmds.objectType(obj) == 'transform':
                    cmds.xform(obj, a=True, rp=(0, 0, 0), sp=(0, 0, 0), ws=True)
                    processed += 1
                    
        cmds.inViewMessage(
            msg=f"Pivot reset complete ({processed} objects)", 
            pos="topLeft", 
            fade=True
        )

    def clean_history_and_transform(self):
        selected = cmds.ls(sl=True)
        if not selected:
            cmds.warning("Please select top group")
            return
        for obj in selected:
            cmds.delete(obj, constructionHistory=True)
            cmds.makeIdentity(obj, apply=True, translate=True, rotate=True, scale=True)
        cmds.inViewMessage(msg="History cleanup complete", pos="topLeft", fade=True)

    def remove_unused_shade(self):
        mel.eval('hyperShadePanelMenuCommand "hyperShadePanel1" "deleteUnusedNodes";')
        cmds.inViewMessage(msg="Unused shaders removed", pos="topLeft", fade=True)

    def move_above_ground(self):
        selected = cmds.ls(sl=True)
        if not selected or len(selected) > 1:
            cmds.warning("Please select exactly one top group")
            return
            
        top_obj = selected[0]
        
        try:
            bb = cmds.xform(top_obj, q=True, bb=True, ws=True)
            if not bb:
                raise RuntimeError("Could not get bounding box")
                
            center_x = (bb[0] + bb[3]) / 2
            center_z = (bb[2] + bb[5]) / 2
            
            current_x = cmds.getAttr(f"{top_obj}.translateX")
            current_z = cmds.getAttr(f"{top_obj}.translateZ")
            current_y = cmds.getAttr(f"{top_obj}.translateY")
            
            new_x = current_x - center_x
            new_z = current_z - center_z
            new_y = current_y - bb[1]
            
            cmds.setAttr(f"{top_obj}.translateX", new_x)
            cmds.setAttr(f"{top_obj}.translateZ", new_z)
            cmds.setAttr(f"{top_obj}.translateY", new_y)
            
            cmds.inViewMessage(
                msg=f"Centered {top_obj} and moved to ground.", 
                pos="topLeft", 
                fade=True
            )
        except Exception as e:
            cmds.warning(f"Failed to adjust group position: {str(e)}")

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

    def auto_save_scene(self):
        try:
            current_file = cmds.file(q=True, sn=True)
            if not current_file:
                # 如果文件从未保存过，给它一个临时名字并保存
                temp_dir = cmds.internalVar(userTmpDir=True)
                temp_path = os.path.join(temp_dir, "temp_publish_scene.ma")
                cmds.file(rename=temp_path)
            cmds.file(save=True, type='mayaAscii')
            return True
        except Exception as e:
            cmds.error(f"Auto save failed: {str(e)}")
            return False

    def publish(self):
        if not self.auto_save_scene():
            return
            
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
        if self.ui.USDCTag.isChecked():
            selected_formats.append("usdc")
        if self.ui.USDATag.isChecked():
            selected_formats.append("usda") 
        if self.ui.AlembicTag.isChecked():
            selected_formats.append("abc")
        if self.ui.OBJTag.isChecked():
            selected_formats.append("obj")

        try:
            next_version = self.get_next_version()
            
            representative_fmt = selected_formats[0] if selected_formats else "ma"
            representative_path = self.get_publish_path(representative_fmt, next_version)
            thumbnail_path = self._create_publish_thumbnail(representative_path)
            
            if not thumbnail_path:
                raise RuntimeError("Thumbnail generation failed. Aborting publish.")

            # 1. Loop through user-selected formats
            for fmt in selected_formats:
                cmds.select(original_selection, replace=True)
                export_path = self.get_publish_path(fmt, next_version)
                
                print(f"Exporting format: {fmt.upper()} to {export_path}")
                self.export_file(fmt, export_path)
                
                print(f"Submitting {fmt.upper()} as a new version to Shotgun...")
                self.submit_to_shotgun(export_path.replace(os.sep, "/"), thumbnail_path)

            # 2. Mandatory Maya scene (.ma) publish
            print("\nProceeding with mandatory Maya scene (.ma) publish...")
            
            current_scene_path = cmds.file(q=True, sn=True)
            if not current_scene_path or not os.path.exists(current_scene_path):
                raise RuntimeError("The scene has not been saved yet. Cannot publish .ma file.")
                
            ma_publish_path = self.get_publish_path("ma", next_version)
            
            print(f"Copying current scene to publish location: {ma_publish_path}")
            shutil.copy2(current_scene_path, ma_publish_path)

            print("Submitting .ma file as a new version to Shotgun...")
            self.submit_to_shotgun(ma_publish_path.replace(os.sep, "/"), thumbnail_path)

            # Update success message to include 'ma'
            final_formats = selected_formats + ["ma"]
            QMessageBox.information(
                self,
                "Publish Success", 
                f"Successfully published formats: {', '.join(final_formats)}\nVersion: {next_version}"
            )

        except Exception as e:
            QMessageBox.critical(self, "Publish Failed", f"An error occurred during publish:\n{str(e)}")

    def get_next_version(self):
        publish_path = os.path.join(os.environ.get("HAL_TASK_ROOT", ""), "_publish")
        if not os.path.exists(publish_path):
            os.makedirs(publish_path)
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

        # 确保 _publish 目录存在
        publish_dir = os.path.join(HAL_TASK_ROOT, publish_folder)
        if not os.path.exists(publish_dir):
            os.makedirs(publish_dir)

        path_segments = re.split(r"[\\/]", HAL_TASK_ROOT)
        if "_library" in path_segments:
            file_name = f"{HAL_PROJECT_ABBR}_{HAL_ASSET}_{HAL_TASK}_{version}_{HAL_USER_ABBR}.{fmt}"
        else:
            file_name = f"{HAL_PROJECT_ABBR}_{HAL_SEQUENCE}_{HAL_SHOT}_{HAL_TASK}_{version}_{HAL_USER_ABBR}.{fmt}"
        
        return os.path.join(publish_dir, file_name)

    def export_file(self, fmt, path):
            # For asset publishing, there is no frame range, so we don't pass it.
            if fmt == "usdc":
                cmds.mayaUSDExport(
                    f=path,
                    selection=True,
                    defaultUSDFormat="usdc",
                    shadingMode="none",
                    defaultMeshScheme="none",
                    # NEW ARGS BELOW:
                    mergeTransformAndShape=False,  # Prevents merging shape and transform nodes
                    stripNamespaces=True           # Removes namespaces from exported objects
                )
            elif fmt == "usda":
                cmds.mayaUSDExport(
                    f=path,
                    selection=True,
                    defaultUSDFormat="usda",
                    shadingMode="none",
                    defaultMeshScheme="none",
                    # NEW ARGS BELOW:
                    mergeTransformAndShape=False,  # Prevents merging shape and transform nodes
                    stripNamespaces=True           # Removes namespaces from exported objects
                )
            elif fmt == "abc":
                current_frame = cmds.currentTime(q=True)
                print(f"Calling Alembic exporter for static asset at frame: {current_frame}")
                export_abc(path, current_frame, current_frame)
            elif fmt == "obj":
                cmds.file(path, force=True, options="groups=1;ptgroups=1;materials=1;smoothing=1;normals=1", 
                        type="OBJexport", exportSelected=True)

    def _create_publish_thumbnail(self, representative_path):
        """Generates a single playblast thumbnail and returns its path."""
        camera = None
        try:
            print("\n=== Starting thumbnail generation process ===")
            
            print("Creating camera and framing objects...")
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
                filename=thumb_path,
                startTime=1001, endTime=1001,
                format='image', compression='png',
                quality=100, percent=100, widthHeight=(1920, 1080),
                showOrnaments=False, forceOverwrite=True,
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
        """Submits a single asset file to Shotgun using a pre-generated thumbnail."""
        try:
            print(f"Creating Shotgun version for: {os.path.basename(asset_path)}")
            sg_manager = ShotgunDataManager()
            sg_manager.Create_SG_Version(thumbnail_path, asset_path)
            print("Successfully created Shotgun version.")
        except Exception as e:
            raise RuntimeError(f"Failed to submit {os.path.basename(asset_path)} to Shotgun: {e}")

def get_command():
    def _command():
        try:
            # It's good practice to reload all dependencies
            importlib.reload(sys.modules['mayaMenuBar.utils.exportABC'])
            importlib.reload(sys.modules['mayaMenuBar.utils.camThumbnail'])
            importlib.reload(sys.modules['mayaMenuBar.utils.SGlogin'])
            importlib.reload(sys.modules[__name__])
        except Exception as e:
            print(f"Could not reload modules: {e}")
            
        window = PublishToolWindow(parent=maya_main_window())
        window.show()
    return _command

def execute():
    # This entry point ensures the module is fresh every time
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()