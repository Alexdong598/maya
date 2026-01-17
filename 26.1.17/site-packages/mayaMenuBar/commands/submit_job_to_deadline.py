from PySide2 import QtWidgets, QtCore, QtGui
import maya.app.renderSetup.model.renderSetup as renderSetup
import maya.OpenMayaUI as omui
import maya.api.OpenMaya as om # Import API 2.0 for callbacks
import maya.cmds as cmds
import maya.mel as mel
import shiboken2
import importlib
import sys
import os
import re

# Import deadline_submit_tasks with fallback
try:
    from utils import deadline_submit_tasks
except ImportError:
    try:
        from ..utils import deadline_submit_tasks
    except ImportError:
        print("Warning: 'deadline_submit_tasks' module not found. Submission logic will run in simulation mode.")
        deadline_submit_tasks = None

# Global variable to store the window instance
deadline_tool = None

def get_maya_window():
    """Retrieve the Maya main window as a QWidget instance."""
    main_window_ptr = omui.MQtUtil.mainWindow()
    return shiboken2.wrapInstance(int(main_window_ptr), QtWidgets.QWidget)

class CollapsibleBox(QtWidgets.QWidget):
    """A custom widget that provides a collapsible header and a content area."""
    def __init__(self, title="", parent=None):
        super(CollapsibleBox, self).__init__(parent)

        self.toggle_button = QtWidgets.QToolButton(text=title, checkable=True, checked=True)
        self.toggle_button.setStyleSheet("""
            QToolButton { 
                background-color: #5E5E5E; 
                color: #FFFFFF; 
                border: 1px solid #707070; 
                border-radius: 2px;
                font-weight: bold; 
                padding: 1px; 
                text-align: left; 
            }
            QToolButton:hover {
                background-color: #6E6E6E;
            }
        """)
        self.toggle_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(QtCore.Qt.DownArrow)
        self.toggle_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.toggle_button.clicked.connect(self.on_pressed)

        self.content_area = QtWidgets.QWidget()
        self.content_area.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.toggle_button)
        self.main_layout.addWidget(self.content_area)

    def on_pressed(self):
        checked = self.toggle_button.isChecked()
        self.toggle_button.setArrowType(QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow)
        self.content_area.setVisible(checked)

    def set_content_layout(self, layout):
        self.content_area.setLayout(layout)


class DeadlineSubmitTool(QtWidgets.QWidget):
    def __init__(self, parent=None):
        if parent is None:
            parent = get_maya_window()
            
        super(DeadlineSubmitTool, self).__init__(parent)
        
        # 1. Window Settings
        self.setWindowTitle("Deadline Submit Tool")
        self.setWindowFlags(QtCore.Qt.Window)
        self.resize(1000, 900)
        
        # Store callback IDs to remove them later
        self.callback_ids = []
        
        # 2. Force Arnold on Init
        self.force_arnold()

        # 3. Setup UI
        self.create_widgets()
        self.create_layout()
        self.create_connections()
        
        # 4. Register Maya Callbacks
        self.register_callbacks()
        
        # 5. Initial Sync (Push initial UI state to Maya)
        self.sync_all_to_maya()
        
        # 6. Populate Render Data (Initial)
        self.refresh_render_data()
        
        # 7. Setup Auto-Refresh Timer for Render Data (1 second interval)
        self.data_timer = QtCore.QTimer(self)
        self.data_timer.timeout.connect(self.refresh_render_data)
        self.data_timer.start(1000)

    def force_arnold(self):
        """Forces Maya to load MtoA and set Arnold as the current renderer."""
        try:
            if not cmds.pluginInfo("mtoa", query=True, loaded=True):
                cmds.loadPlugin("mtoa")
            
            # Set current renderer to Arnold
            cmds.setAttr("defaultRenderGlobals.ren", "arnold", type="string")
            cmds.setAttr("defaultRenderGlobals.animation", True)
            cmds.setAttr("defaultRenderGlobals.outFormatControl", 2)
            
            print("Deadline Tool: Forced Arnold Render Engine.")
        except Exception as e:
            print(f"Error forcing Arnold: {e}")

    def get_active_arnold_aovs(self):
        options_node = "defaultArnoldRenderOptions"
        
        if not cmds.objExists(options_node):
            print("Arnold Render Options node not found. Verify Arnold is loaded.")
            return []
        active_aovs = cmds.listConnections(options_node + ".aovList", source=True, destination=False) or []
        active_aov_nodes = [aov for aov in active_aovs if cmds.nodeType(aov) == 'aiAOV']
        aovs = []
        for aov in active_aov_nodes:
            pass_name = cmds.getAttr(aov + ".name")
            aovs.append(pass_name)
        return aovs

    def register_callbacks(self):
        """Register callbacks to detect scene changes."""
        # Callback for when scene is saved
        cb_save = om.MSceneMessage.addCallback(om.MSceneMessage.kAfterSave, self.on_scene_changed)
        self.callback_ids.append(cb_save)
        
        # Callback for when a new scene is opened
        cb_open = om.MSceneMessage.addCallback(om.MSceneMessage.kAfterOpen, self.on_scene_changed)
        self.callback_ids.append(cb_open)

    def remove_callbacks(self):
        """Remove callbacks when closing the tool."""
        for cb_id in self.callback_ids:
            try:
                om.MMessage.removeCallback(cb_id)
            except:
                pass
        self.callback_ids = []

    def closeEvent(self, event):
        """Override close event to clean up callbacks and timer."""
        self.remove_callbacks()
        if self.data_timer.isActive():
            self.data_timer.stop()
        super(DeadlineSubmitTool, self).closeEvent(event)

    def on_scene_changed(self, *args):
        """Slot called when Maya scene is saved or opened."""
        new_name = self.get_scene_name()
        
        # Update Job Name
        if self.le_job_name:
            self.le_job_name.setText(new_name)
            print(f"Deadline Tool: Job Name updated to '{new_name}'")
            
        # Update Versioning logic since filename changed
        self.refresh_versioning()
        # Update Render Data as scene changed
        self.refresh_render_data()

    def getCurrentLayer(self):
        rs = renderSetup.instance()
        current_layer = rs.getVisibleRenderLayer()
        return current_layer.name()

    def getStartEndFrame(self):
        try:
            # Placeholder for SG Login logic if available
            # from ..utils.SGlogin import ShotgunDataManager
            # ... logic here ...
            
            # Fallback to current Maya timeline for this standalone version
            startFrame = int(cmds.playbackOptions(q=True, min=True))
            endFrame = int(cmds.playbackOptions(q=True, max=True))
        except Exception as e:
            print(f"Warning: Error fetching frame range: {e}")
            startFrame = 1001
            endFrame = 1100

        return startFrame, endFrame
    
    def get_resolution(self):
        """Helper to fetch resolution from Maya globals."""
        try:
            w = cmds.getAttr("defaultResolution.width")
            h = cmds.getAttr("defaultResolution.height")
            return int(w), int(h)
        except:
            return 1920, 1080

    def get_version_from_scene(self):
        """Extracts version string (e.g., v001) from the current Maya scene filename."""
        scene_path = cmds.file(q=True, sn=True)
        if not scene_path:
            return "unSavedVersion"
            
        filename = os.path.basename(scene_path)
        match = re.search(r'[vV](\d{3,})', filename)
        
        if match:
            return match.group(0).lower() 
        else:
            return "unSavedVersion"

    def get_scene_name(self):
        scene_name = cmds.file(q=True, sn=True, shn=True)
        if not scene_name:
            default_name = "untitled"
        else:
            default_name = os.path.splitext(scene_name)[0]
        return default_name

    def get_render_output_dir(self):
        HAL_TASK_ROOT = os.environ.get("HAL_TASK_ROOT", "")
        HAL_TASK_OUTPUT_ROOT = os.environ.get("HAL_TASK_OUTPUT_ROOT", "")
        return HAL_TASK_ROOT, HAL_TASK_OUTPUT_ROOT

    def get_custom_prefix(self, output_dir):
        HAL_USER_ABBR = os.environ.get("HAL_USER_ABBR", "user")
        HAL_PROJECT_ABBR = os.environ.get("HAL_PROJECT_ABBR", "proj")
        HAL_SEQUENCE = os.environ.get("HAL_SEQUENCE", "seq")
        HAL_SHOT = os.environ.get("HAL_SHOT", "shot")
        HAL_TASK = os.environ.get("HAL_TASK", "task")

        # Get version dynamically from the scene filename
        version = self.get_version_from_scene()

        custom_prefix = f"<RenderLayer>/{version}/fullres/<RenderPass>/{HAL_PROJECT_ABBR}_{HAL_SEQUENCE}_{HAL_SHOT}_{HAL_TASK}_<RenderLayer>_{version}_{HAL_USER_ABBR}.<RenderPass>"
        return custom_prefix

    def getFinalOutputPath(self,frame="####"):
        renderLayer = str(self.getCurrentLayer())
        if renderLayer == "defaultRenderLayer":
            renderLayer = "masterLayer"
            
        img_fmt = "exr"
        if hasattr(self, 'cmb_image_format'):
            img_fmt = self.cmb_image_format.currentText()

        output_dir = self.le_output_path.text()
        prefix = self.le_file_name_prefix.text()
        # startFrame = str(self.spin_start_frame.value())
        startFrame = frame

        outputPath = f"{output_dir}/{prefix}.{startFrame}.{img_fmt}"
        outputPath = outputPath.replace(os.sep, "/")
        return outputPath

    def refresh_versioning(self):
        """Dynamically recalculates the prefix and pushes it to Maya."""
        current_path = self.le_output_path.text()
        new_prefix = self.get_custom_prefix(current_path)
        self.le_file_name_prefix.setText(new_prefix)
        # Note: setText will trigger update_maya_prefix via the textChanged signal

    def refresh_cameras(self):
        """Helper to fetch cameras from Maya."""
        self.cmb_camera.clear()
        try:
            # Get camera shapes, then their parents (transforms)
            cam_shapes = cmds.ls(type='camera') or []
            cam_transforms = []
            for shape in cam_shapes:
                parent = cmds.listRelatives(shape, parent=True)
                if parent:
                    cam_transforms.append(parent[0])
            
            # Sort and add to combo
            cam_transforms.sort()
            self.cmb_camera.addItems(cam_transforms)
            
            # Default to persp if available
            self.set_combo_default(self.cmb_camera, "persp")
        except:
            # Fallback if running outside Maya or error
            self.cmb_camera.addItems(["persp", "top", "front", "side"])

    # --- Render Data Helper Methods ---
    def get_render_debug_data(self):
        """Collects useful Arnold render data for debugging."""
        data = []
        
        # 1. Render Layers
        try:
            rs = renderSetup.instance()
            layers = rs.getRenderLayers()
            active_layers = []

            # Check Default/Master Layer
            default_layer = rs.getDefaultRenderLayer()
            # Check if Master Layer is renderable
            if default_layer and default_layer.isRenderable():
                 active_layers.append(f"{default_layer.name()} (Master)")

            # Check Setup Layers
            for layer in layers:
                if layer.isRenderable():
                    active_layers.append(layer.name())
            
            data.append("--- Active Render Layers ---")
            if active_layers:
                for name in active_layers:
                    data.append(f"  [ON] {name}")
            else:
                data.append("  (No Render Layers enabled)")
        except Exception as e:
            data.append(f"Error reading Render Layers: {e}")
            
        data.append("")

        # 2. AOVs
        try:
            data.append("--- Active Arnold AOVs ---")
            aovs = cmds.ls(type='aiAOV')
            active_aovs = []
            if aovs:
                for aov in aovs:
                    if cmds.getAttr(f"{aov}.enabled"):
                        active_aovs.append(aov)
            
            if active_aovs:
                for aov in active_aovs:
                    data.append(f"  [ON] {aov}")
            else:
                data.append("  (No Active AOVs)")
        except Exception as e:
            data.append(f"Error reading AOVs: {e}")

        data.append("")

        # 3. Sampling
        try:
            data.append("--- Arnold Sampling ---")
            if cmds.objExists("defaultArnoldRenderOptions"):
                aa = cmds.getAttr("defaultArnoldRenderOptions.AASamples")
                diff = cmds.getAttr("defaultArnoldRenderOptions.GIDiffuseSamples")
                spec = cmds.getAttr("defaultArnoldRenderOptions.GISpecularSamples")
                trans = cmds.getAttr("defaultArnoldRenderOptions.GITransmissionSamples")
                sss = cmds.getAttr("defaultArnoldRenderOptions.GISssSamples")
                vol = cmds.getAttr("defaultArnoldRenderOptions.GIVolumeSamples")
                
                data.append(f"  Camera (AA): {aa}")
                data.append(f"  Diffuse: {diff}")
                data.append(f"  Specular: {spec}")
                data.append(f"  Transmission: {trans}")
                data.append(f"  SSS: {sss}")
                data.append(f"  Volume Indirect: {vol}")
            else:
                data.append("  (defaultArnoldRenderOptions node not found)")
        except Exception as e:
            data.append(f"Error reading Sampling: {e}")

        return "\n".join(data)

    def refresh_render_data(self):
        """Updates the render data text area without resetting scroll position."""
        if hasattr(self, 'txt_render_data') and self.isVisible():
            # Save current scroll position to prevent jumping
            scrollbar = self.txt_render_data.verticalScrollBar()
            current_scroll = scrollbar.value()
            
            info = self.get_render_debug_data()
            self.txt_render_data.setText(info)
            
            # Restore scroll position
            scrollbar.setValue(current_scroll)

    # --- Dynamic Maya Update Methods ---

    def update_notice_label(self):
        """Refreshes the notice label."""
        self.label_filename_notice.setText(f"{self.getFinalOutputPath(str(self.spin_start_frame.value()))}")

    def update_maya_frame_range(self):
        """Updates Maya start/end frames when UI spinners change."""
        start = self.spin_start_frame.value()
        end = self.spin_end_frame.value()
        try:
            cmds.setAttr("defaultRenderGlobals.startFrame", start)
            cmds.setAttr("defaultRenderGlobals.endFrame", end)
        except Exception as e:
            print(f"Sync Error (Frames): {e}")
        self.update_notice_label()

    def update_maya_image_format(self):
        """Updates Arnold driver translator when UI combo changes."""
        img_fmt = self.cmb_image_format.currentText()
        driver_format = img_fmt 
        try:
            cmds.setAttr("defaultArnoldDriver.ai_translator", driver_format, type="string")
        except Exception as e:
            print(f"Sync Error (Format): {e}")
        self.update_notice_label()

    def update_maya_camera(self):
        """Sets the selected camera to renderable in Maya, disabling others."""
        selected_cam_transform = self.cmb_camera.currentText()
        try:
            all_cameras = cmds.ls(type='camera') or []
            for cam_shape in all_cameras:
                if cmds.attributeQuery("renderable", node=cam_shape, exists=True):
                    try:
                        cmds.setAttr(f"{cam_shape}.renderable", 0)
                    except:
                        pass

            cam_shapes = cmds.listRelatives(selected_cam_transform, shapes=True, type='camera')
            if not cam_shapes: return
            
            target_shape = cam_shapes[0]
            cmds.setAttr(f"{target_shape}.renderable", 1)
            print(f"Synced Camera: Set '{selected_cam_transform}' as the SINGLE renderable camera.")
        except Exception as e:
            print(f"Sync Error (Camera): {e}")

    def update_maya_prefix(self):
        """Updates the image file prefix in Maya Render Globals."""
        prefix = self.le_file_name_prefix.text()
        try:
            cmds.setAttr("defaultRenderGlobals.imageFilePrefix", prefix, type="string")
        except Exception as e:
            print(f"Sync Error (Prefix): {e}")
        self.update_notice_label()

    def sync_all_to_maya(self):
        """Pushes all current UI states to Maya settings."""
        self.update_maya_frame_range()
        self.update_maya_image_format()
        self.update_maya_camera()
        self.update_maya_prefix()

    def create_widgets(self):
        """Create all UI elements."""
        
        # --- Section 1: Job Description ---
        self.le_job_name = QtWidgets.QLineEdit()
        self.le_job_name.setText(self.get_scene_name()) 
        self.le_job_name.setPlaceholderText("请描述递交Deadline任务的名字")
        self.le_job_name.setReadOnly(True) # Locked
        
        self.le_comment = QtWidgets.QLineEdit()
        self.HAL_TASK = os.environ.get("HAL_TASK", "task")

        self.le_comment.setText(f"{self.HAL_TASK} tasks have been sent to Deadline.") 
        self.le_comment.setPlaceholderText("请描述递交Deadline任务的内容")
        
        self.le_department = QtWidgets.QLineEdit()
        self.le_department.setText(self.HAL_TASK)
        self.le_department.setPlaceholderText("请描述递交Deadline任务的部门")
        self.le_department.setReadOnly(True) # Locked

        # --- Section 2: Job Scheduling ---
        self.pool_options = ["none", "2d", "3d", "all", "gpu", "proxy", "hal_pipeline"]
        self.group_options = ["none", "2d", "3d", "all", "gpu", "proxy"]

        self.cmb_pool = QtWidgets.QComboBox()
        self.cmb_pool.addItems(self.pool_options)
        self.set_combo_default(self.cmb_pool, "3d")

        self.cmb_sec_pool = QtWidgets.QComboBox()
        self.cmb_sec_pool.addItems(self.pool_options)
        self.set_combo_default(self.cmb_sec_pool, "3d")

        self.cmb_group = QtWidgets.QComboBox()
        self.cmb_group.addItems(self.group_options)
        self.set_combo_default(self.cmb_group, "3d")

        self.sliders = {}
        self.slider_config = [
            ("Priority", 50, 0, 100),
            ("Machine Limit", 20, 0, 100),
            ("Concurrent Tasks", 1, 1, 16),
            ("Task Timeout", 0, 0, 5000),
            ("Minimum Task Time", 0, 0, 5000),
        ]
        
        for label, default, min_val, max_val in self.slider_config:
            spin = QtWidgets.QSpinBox()
            spin.setRange(min_val, max_val)
            spin.setValue(default)
            slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            slider.setRange(min_val, max_val)
            slider.setValue(default)
            spin.valueChanged.connect(slider.setValue)
            slider.valueChanged.connect(spin.setValue)
            self.sliders[label] = {"spin": spin, "slider": slider}

        self.btn_submit = QtWidgets.QPushButton("Submit Job")
        self.btn_submit.setStyleSheet("background-color: #5D5D5D; font-weight: bold; padding: 6px;")
        self.btn_close = QtWidgets.QPushButton("Close")

        # --- Section 3: Additional Frame Options ---
        
        # 3.1 Camera (Loop through Maya cameras)
        self.cmb_camera = QtWidgets.QComboBox()
        self.refresh_cameras()

        # 3.1a Image Format (New)
        self.cmb_image_format = QtWidgets.QComboBox()
        self.cmb_image_format.addItems(["jpeg", "png", "deepexr", "tif", "exr", "maya"])
        self.set_combo_default(self.cmb_image_format, "exr")

        # Removed Quality widgets as requested

        # 3.2 Project Path
        self.le_project_path = QtWidgets.QLineEdit()
        try:
            self.le_project_path.setText(self.get_render_output_dir()[0].replace(os.sep, "/") or "")
        except:
            pass
        self.le_project_path.setPlaceholderText("请设置项目路径")
        self.le_project_path.setReadOnly(True) # Locked
        self.btn_project_path = QtWidgets.QPushButton("...")
        self.btn_project_path.setFixedWidth(30)
        self.btn_project_path.setEnabled(False) # Locked

        # 3.3 Output Path
        self.le_output_path = QtWidgets.QLineEdit()
        try:
            self.le_output_path.setText(self.get_render_output_dir()[1].replace(os.sep, "/") or "")
        except:
            pass
        self.le_output_path.setPlaceholderText("请设置输出路径")
        self.le_output_path.setReadOnly(True) # Locked
        self.btn_output_path = QtWidgets.QPushButton("...")
        self.btn_output_path.setFixedWidth(30)
        self.btn_output_path.setEnabled(False) # Locked

        # 3.4 File Name Prefix
        self.le_file_name_prefix = QtWidgets.QLineEdit()
        try:
            self.le_file_name_prefix.setText(self.get_custom_prefix(self.get_render_output_dir()))
        except:
            pass
        self.le_file_name_prefix.setPlaceholderText("请设置文件名前缀")
        self.le_file_name_prefix.setReadOnly(True) # Locked
        self.btn_file_name_prefix = QtWidgets.QPushButton("...")
        self.btn_file_name_prefix.setFixedWidth(30)
        self.btn_file_name_prefix.setEnabled(False) # Locked
        
        # 3.4b Notice Label (Moved to end of creation so all dependencies exist)
        self.label_filename_notice = QtWidgets.QLabel(f"{self.getFinalOutputPath()}")
        self.label_filename_notice.setStyleSheet("color: #C0C0C0; font-style: italic; font-size: 11px; margin-bottom: 5px;")


        # 3.5 Startup Script
        self.le_startup_script = QtWidgets.QLineEdit()
        self.btn_startup_script = QtWidgets.QPushButton("...")
        self.btn_startup_script.setFixedWidth(30)
        
        # 3.6 Frame Animation Ext
        self.cmb_frame_ext = QtWidgets.QComboBox()
        ext_options = [
            "name", 
            "name.ext", 
            "name.#.ext", 
            "name.ext.#", 
            "name.#", 
            "name#.ext", 
            "name_#.ext",
            "name (Single Frame)",
            "name.ext (Single Frame)",
            "name (Multi Frame)",
            "name.ext (Multi Frame)"
        ]
        self.cmb_frame_ext.addItems(ext_options)
        self.set_combo_default(self.cmb_frame_ext, "name.#.ext")
        self.cmb_frame_ext.setEnabled(False) # Locked: User cannot change this


        # 3.7 Frame Range
        start, end = self.getStartEndFrame()
        self.spin_start_frame = QtWidgets.QSpinBox()
        self.spin_start_frame.setRange(-999999, 999999)
        self.spin_start_frame.setValue(start)

        self.spin_end_frame = QtWidgets.QSpinBox()
        self.spin_end_frame.setRange(-999999, 999999)
        self.spin_end_frame.setValue(end)

        # --- Section 4: Render Data (New) ---
        self.txt_render_data = QtWidgets.QTextEdit()
        self.txt_render_data.setReadOnly(True)
        self.txt_render_data.setMinimumHeight(120)

    def create_layout(self):
        """Organize the widgets into layouts with a Scroll Area and Fixed Footer."""
        # Main Window Layout
        main_window_layout = QtWidgets.QVBoxLayout(self)
        main_window_layout.setContentsMargins(0, 0, 0, 0)
        main_window_layout.setSpacing(0) # Remove spacing between scroll and footer
        
        # Scroll Area setup
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        
        # Content Widget inside Scroll Area
        content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content_widget)
        content_layout.setSpacing(10)
        content_layout.setContentsMargins(15, 15, 15, 15)
        content_layout.setAlignment(QtCore.Qt.AlignTop)

        # --- 1. Job Description Collapsible ---
        self.box_description = CollapsibleBox("Job Description")
        desc_layout = QtWidgets.QFormLayout()
        desc_layout.setContentsMargins(10, 10, 10, 10)
        desc_layout.setLabelAlignment(QtCore.Qt.AlignLeft)
        
        desc_layout.addRow("Job Name", self.le_job_name)
        desc_layout.addRow("Comment", self.le_comment)
        desc_layout.addRow("Department", self.le_department)
        
        self.box_description.set_content_layout(desc_layout)
        content_layout.addWidget(self.box_description)

        # --- 2. Job Scheduling Collapsible ---
        self.box_scheduling = CollapsibleBox("Job Scheduling")
        sched_layout = QtWidgets.QGridLayout()
        sched_layout.setContentsMargins(10, 10, 10, 10)
        sched_layout.setColumnStretch(1, 1) 
        
        sched_layout.addWidget(QtWidgets.QLabel("Pool"), 0, 0)
        sched_layout.addWidget(self.cmb_pool, 0, 1)
        sched_layout.addWidget(QtWidgets.QLabel("Secondary Pool"), 1, 0)
        sched_layout.addWidget(self.cmb_sec_pool, 1, 1)
        sched_layout.addWidget(QtWidgets.QLabel("Group"), 2, 0)
        sched_layout.addWidget(self.cmb_group, 2, 1)
        
        current_row = 3
        for label_text, default, min_val, max_val in self.slider_config:
            widgets = self.sliders[label_text]
            sched_layout.addWidget(QtWidgets.QLabel(label_text), current_row, 0)
            row_widget = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(widgets["spin"])
            row_layout.addWidget(widgets["slider"])
            sched_layout.addWidget(row_widget, current_row, 1)
            current_row += 1
            
        self.box_scheduling.set_content_layout(sched_layout)
        content_layout.addWidget(self.box_scheduling)
        
        # --- 3. Additional Frame Options Collapsible ---
        self.box_frames = CollapsibleBox("Additional Frame Options")
        frame_layout = QtWidgets.QGridLayout()
        frame_layout.setContentsMargins(10, 10, 10, 10)
        frame_layout.setColumnStretch(1, 1)
        
        frame_layout.addWidget(QtWidgets.QLabel("Camera"), 0, 0)
        frame_layout.addWidget(self.cmb_camera, 0, 1)

        frame_layout.addWidget(QtWidgets.QLabel("Image format"), 1, 0)
        frame_layout.addWidget(self.cmb_image_format, 1, 1)

        # Removed Quality widgets as requested

        # Project Path
        frame_layout.addWidget(QtWidgets.QLabel("Project Path"), 2, 0)
        proj_group = QtWidgets.QWidget()
        proj_layout = QtWidgets.QHBoxLayout(proj_group)
        proj_layout.setContentsMargins(0,0,0,0)
        proj_layout.addWidget(self.le_project_path)
        proj_layout.addWidget(self.btn_project_path)
        frame_layout.addWidget(proj_group, 2, 1)

        # Output Path
        frame_layout.addWidget(QtWidgets.QLabel("Output Path"), 3, 0)
        out_group = QtWidgets.QWidget()
        out_layout = QtWidgets.QHBoxLayout(out_group)
        out_layout.setContentsMargins(0,0,0,0)
        out_layout.addWidget(self.le_output_path)
        out_layout.addWidget(self.btn_output_path)
        frame_layout.addWidget(out_group, 3, 1)

        # File Name Prefix
        frame_layout.addWidget(QtWidgets.QLabel("File Name Prefix"), 4, 0)
        file_name_prefix_group = QtWidgets.QWidget()
        file_name_prefix_layout = QtWidgets.QHBoxLayout(file_name_prefix_group)
        file_name_prefix_layout.setContentsMargins(0,0,0,0)
        file_name_prefix_layout.addWidget(self.le_file_name_prefix)
        file_name_prefix_layout.addWidget(self.btn_file_name_prefix)
        frame_layout.addWidget(file_name_prefix_group, 4, 1)

        # Notice Message
        frame_layout.addWidget(self.label_filename_notice, 5, 1)

        # Startup Script
        frame_layout.addWidget(QtWidgets.QLabel("Startup Script"), 6, 0)
        script_group = QtWidgets.QWidget()
        script_layout = QtWidgets.QHBoxLayout(script_group)
        script_layout.setContentsMargins(0,0,0,0)
        script_layout.addWidget(self.le_startup_script)
        script_layout.addWidget(self.btn_startup_script)
        frame_layout.addWidget(script_group, 6, 1)
        
        # Frame Animation Ext
        frame_layout.addWidget(QtWidgets.QLabel("Frame/Animation ext"), 7, 0)
        frame_layout.addWidget(self.cmb_frame_ext, 7, 1)

        # Frame Range
        frame_layout.addWidget(QtWidgets.QLabel("Frame Range"), 8, 0)
        range_group = QtWidgets.QWidget()
        range_layout = QtWidgets.QHBoxLayout(range_group)
        range_layout.setContentsMargins(0,0,0,0)
        range_layout.addWidget(QtWidgets.QLabel("Start:"))
        range_layout.addWidget(self.spin_start_frame)
        range_layout.addWidget(QtWidgets.QLabel("End:"))
        range_layout.addWidget(self.spin_end_frame)
        range_layout.addStretch()
        frame_layout.addWidget(range_group, 8, 1)

        self.box_frames.set_content_layout(frame_layout)
        content_layout.addWidget(self.box_frames)

        # --- 4. Render Data Collapsible (New) ---
        self.box_render_data = CollapsibleBox("Render Data")
        data_layout = QtWidgets.QVBoxLayout()
        data_layout.setContentsMargins(10, 10, 10, 10)
        # Removed button widget: data_layout.addWidget(self.btn_refresh_data)
        data_layout.addWidget(self.txt_render_data)
        self.box_render_data.set_content_layout(data_layout)
        
        # Ensure closed state is applied visually
        self.box_render_data.toggle_button.setChecked(False) 
        self.box_render_data.on_pressed() 
        
        content_layout.addWidget(self.box_render_data)
        
        # Add stretch to ensure content sticks to top
        content_layout.addStretch()

        # Finalize Scroll Area
        scroll_area.setWidget(content_widget)
        main_window_layout.addWidget(scroll_area)

        # --- Footer (Outside Scroll Area) ---
        footer_widget = QtWidgets.QWidget()
        footer_layout = QtWidgets.QHBoxLayout(footer_widget)
        footer_layout.setContentsMargins(15, 10, 15, 15) # Padding
        footer_layout.addWidget(self.btn_submit)
        footer_layout.addWidget(self.btn_close)
        main_window_layout.addWidget(footer_widget)

    def create_connections(self):
        self.btn_submit.clicked.connect(self.submit_job)
        self.btn_close.clicked.connect(self.close)
        
        # Dynamic Maya Links
        self.spin_start_frame.valueChanged.connect(self.update_maya_frame_range)
        self.spin_end_frame.valueChanged.connect(self.update_maya_frame_range)
        self.cmb_image_format.currentIndexChanged.connect(self.update_maya_image_format)
        self.cmb_camera.currentIndexChanged.connect(self.update_maya_camera)
        self.le_file_name_prefix.textChanged.connect(self.update_maya_prefix)
        self.le_output_path.textChanged.connect(self.refresh_versioning)
        
        # File Browsers
        self.btn_project_path.clicked.connect(lambda: self.browse_folder(self.le_project_path))
        self.btn_output_path.clicked.connect(lambda: self.browse_folder(self.le_output_path))
        self.btn_startup_script.clicked.connect(lambda: self.browse_file(self.le_startup_script, "Python Files (*.py)"))

    def browse_folder(self, line_edit):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            line_edit.setText(folder)

    def browse_file(self, line_edit, filter_str):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select File", "", filter_str)
        if file_path:
            line_edit.setText(file_path)

    def set_combo_default(self, combo, text):
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)

    def get_renderable_layers(self):
        """Returns a list of renderable layer names from Render Setup."""
        rs = renderSetup.instance()
        layers = rs.getRenderLayers()
        renderable = []
        
        # Check Default/Master Layer
        default_layer = rs.getDefaultRenderLayer()
        if default_layer and default_layer.isRenderable():
        ########Using masterLayer instead of defaultRenderLayer############
            renderable.append("masterLayer")
            
        # Check Setup Layers
        for layer in layers:
            if layer.isRenderable():
                renderable.append(layer.name())
        
        # Fallback if no renderable layers found (use current)
        if not renderable:
            renderable.append(self.getCurrentLayer())
            
        return renderable

    def submit_job(self):
        """Handles submission to Deadline with multi-layer dependency chaining."""
        # 1. Apply Sync
        self.sync_all_to_maya()
        
        # 2. Check Save
        file_path = cmds.file(q=True, sn=True)
        if not file_path:
            QtWidgets.QMessageBox.warning(self, "Unsaved File", "Please save the Maya scene before submitting.")
            return
        
        # 3. Force Save
        cmds.file(save=True, type='mayaAscii')
        print("Scene saved.")

        # 4. Prepare Common Job Data
        base_job_info = {
            "Comment": self.le_comment.text(),
            "Department": self.le_department.text(),
            "Pool": self.cmb_pool.currentText(),
            "SecondaryPool": self.cmb_sec_pool.currentText(),
            "Group": self.cmb_group.currentText(),
            "Priority": self.sliders["Priority"]["spin"].value(),
            "TaskTimeoutMinutes": self.sliders["Task Timeout"]["spin"].value(),
            "MachineLimit": self.sliders["Machine Limit"]["spin"].value(),
            "ConcurrentTasks": self.sliders["Concurrent Tasks"]["spin"].value(),
            "Plugin": "MayaBatch",
            "Frames": f"{self.spin_start_frame.value()}-{self.spin_end_frame.value()}",
            "ChunkSize": 1,
            "BatchName": self.le_job_name.text(), # Groups all layer jobs together
            "LimitGroups": "maya_render,arnold_render",
            "EnableAutoTimeOut": "True",
            # "OutputDirectory0": "test"
        }

        # 4.5 Get current resolution
        width, height = self.get_resolution()

        # 5. Prepare Common Plugin Info
        base_plugin_info = {
            "SceneFile": file_path,
            "Version": "2024", 
            "Renderer": "arnold",
            "Camera": self.cmb_camera.currentText(),
            "ImageWidth": str(width),
            "ImageHeight": str(height),
            "OutputFilePath": self.le_output_path.text().replace("/", "\\"),
            "OutputFilePrefix": self.le_file_name_prefix.text(),
            "StartupScript": self.le_startup_script.text(),
            "Animation": 1,
            "RenderHalfFrames": 0,
            "FrameNumberOffset": 0,
            "LocalRendering": 0,
            "StrictErrorChecking": 0,
            "MaxProcessors": 0,
            "ArnoldVerbose": 1,
            "UseLegacyRenderLayers": 0,
            "Build": "64bit",
            "ProjectPath": self.le_project_path.text().replace("/", "\\"),
            "IgnoreError211": 0,
        }

        # --- CAMERA LIST INJECTION ---
        base_plugin_info["Camera0"] = ""
        for i in range(self.cmb_camera.count()):
            base_plugin_info[f"Camera{i+1}"] = self.cmb_camera.itemText(i)
        # -----------------------------
            
        # 6. Loop Through Layers & Submit with Dependencies
        try:
            if deadline_submit_tasks is None:
                # Simulation Mode
                print("Deadline module not loaded. Simulation:")
                print("LAYERS:", self.get_renderable_layers())
                QtWidgets.QMessageBox.information(self, "Simulation", "Deadline module not found.")
                return

            renderable_layers = self.get_renderable_layers()
            previous_job_id = "" # Used for chaining dependencies
            submitted_ids = []

            for layer_name in renderable_layers:
                print(f"Preparing submission for layer: {layer_name}")
                
                # --- Specific Job Info ---
                job_info = base_job_info.copy()
                job_info["Name"] = f"{self.le_job_name.text()}_{layer_name}" # JobName_LayerName
                
                base_output = self.le_file_name_prefix.text().replace("/", "\\")
                active_aovs = self.get_active_arnold_aovs()
                
                for aovIndex,aovItem in enumerate(active_aovs):
                    print(f"aovItem is: {aovItem}")
                    output_index = aovIndex+1
                    final_aov_dir = self.getFinalOutputPath()
                    if "<RenderPass>" in final_aov_dir:
                            final_aov_dir = final_aov_dir.replace("<RenderLayer>", layer_name)
                            final_aov_dir = final_aov_dir.replace("<RenderPass>", aovItem)
                            final_aov_dir_dirname,_ = os.path.split(final_aov_dir)
                            os.makedirs(final_aov_dir_dirname, exist_ok=True)
                    else:
                        pass
                    
                    job_info[f"OutputFilename{output_index}"] = final_aov_dir

                final_aov_dir_beauty = self.getFinalOutputPath().replace("<RenderLayer>", layer_name).replace("<RenderPass>", "beauty")
                final_aov_dir_beauty_dirname,_ = os.path.split(final_aov_dir_beauty)
                os.makedirs(final_aov_dir_beauty_dirname, exist_ok=True)
                job_info[f"OutputFilename0"] = final_aov_dir_beauty

                if previous_job_id:
                    job_info["JobDependencies"] = previous_job_id # Chain: Run after previous finishes
                
                # --- Specific Plugin Info ---
                plugin_info = base_plugin_info.copy()
                plugin_info["RenderLayer"] = layer_name
                plugin_info["UsingRenderLayers"] = 1 # Force switch to this layer
                
                # --- Submit ---
                job_id = deadline_submit_tasks.deadline_submit(job_info, plugin_info)
                
                if job_id and "failed" not in str(job_id).lower():
                    # submitted_ids.append(f"渲染层：{layer_name}: {job_id}")
                    submitted_ids.append(f"渲染层： {layer_name}")
                    previous_job_id = job_id # Update previous ID for next iteration
                else:
                    print(f"Warning: Failed to get valid Job ID for {layer_name}. Breaking chain.")
                    previous_job_id = "" # Reset dependency if chain breaks

            # Summary
            if submitted_ids:
                msg = "成功提交渲染任务到农场:\n" + "\n".join(submitted_ids)
                QtWidgets.QMessageBox.information(self, "Success", msg)
            else:
                QtWidgets.QMessageBox.warning(self, "Warning", "没有成功提交任务。")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Submission Failed", str(e))

        # 7. Refresh versions
        self.refresh_versioning()

def get_command():
    """Return the current implementation of the command."""
    def _command():
        global deadline_tool
        
        # --- HOT RELOAD LOGIC ---
        if deadline_submit_tasks:
            try:
                importlib.reload(deadline_submit_tasks)
                print("Dev: Reloaded submission logic.")
            except Exception as e:
                print(f"Dev: Failed to reload submission logic: {e}")
        # -------------------------------
        
        try:
            if deadline_tool:
                deadline_tool.close()
                deadline_tool.deleteLater()
        except:
            pass
        deadline_tool = DeadlineSubmitTool()
        deadline_tool.show()
    return _command

def execute():
    """Execute the command with reloading."""
    if __name__ != "__main__":
        importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()

if __name__ == "__main__":
    execute()