# Import necessary modules from PySide2 (standard for modern Maya)
from PySide2 import QtWidgets, QtCore, QtGui
import os
import re
import subprocess
import fnmatch
import hal_naming
# Import Maya commands and OpenMayaUI
import maya.cmds as cmds
import maya.OpenMayaUI as omui
from shiboken2 import wrapInstance

def maya_main_window():
    """Return the Maya main window widget"""
    main_window_ptr = omui.MQtUtil.mainWindow()
    if main_window_ptr is not None:
        return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)
    return None

class PlayblastDialog(QtWidgets.QDialog):
    def __init__(self, parent=maya_main_window()):
        super(PlayblastDialog, self).__init__(parent)

        self.setWindowTitle("Anim Playblast")
        self.setMinimumWidth(450) # Increased width for new elements
        self.setMinimumHeight(300) # Increased height for new elements

        # Create menu bar
        self.menu_bar = QtWidgets.QMenuBar()
        file_menu = self.menu_bar.addMenu("File")
        
        # Add "Open playblast folder" action
        open_folder_action = QtWidgets.QAction("Open playblast folder", self)
        open_folder_action.triggered.connect(self.open_playblast_folder)
        file_menu.addAction(open_folder_action)

        # Store camera data for the combobox
        self.camera_data_list = []

        # Main vertical layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setMenuBar(self.menu_bar)

        # --- Upload to SG Checkbox ---
        self.upload_sg_checkbox = QtWidgets.QCheckBox("是否上传SG")
        self.upload_sg_checkbox.setChecked(True)
        self.main_layout.addWidget(self.upload_sg_checkbox)

        # --- Camera Selection ---
        self.info_label_camera = QtWidgets.QLabel("请选择你要做playblast的照相机")
        self.main_layout.addWidget(self.info_label_camera)

        self.camera_combobox = QtWidgets.QComboBox()
        self.main_layout.addWidget(self.camera_combobox)

        # --- Frame Range Selection Area ---
        self.frame_range_label = QtWidgets.QLabel("4. 请选择要到处序列动画的起始帧和结束帧")
        self.main_layout.addWidget(self.frame_range_label)

        self.get_sg_frames_button = QtWidgets.QPushButton("直接从SG上获取镜头开始和结束帧")
        self.get_sg_frames_button.clicked.connect(self.on_get_sg_frames) # Placeholder
        self.main_layout.addWidget(self.get_sg_frames_button)

        # Start Frame layout
        self.start_frame_layout = QtWidgets.QHBoxLayout()
        self.start_frame_label_text = QtWidgets.QLabel("Start Frame")
        self.start_frame_line_edit = QtWidgets.QLineEdit()
        self.start_frame_line_edit.setValidator(QtGui.QIntValidator()) # Allow only integers
        self.start_frame_line_edit.setPlaceholderText("e.g., 1001")
        self.start_frame_context_label = QtWidgets.QLabel("根据目前帧范围选择:")
        self.get_current_start_button = QtWidgets.QPushButton("起始帧")
        self.get_current_start_button.clicked.connect(self.on_get_current_start_frame) # Placeholder

        self.start_frame_layout.addWidget(self.start_frame_label_text)
        self.start_frame_layout.addWidget(self.start_frame_line_edit)
        self.start_frame_layout.addStretch() # Add some space
        self.start_frame_layout.addWidget(self.start_frame_context_label)
        self.start_frame_layout.addWidget(self.get_current_start_button)
        self.main_layout.addLayout(self.start_frame_layout)

        # End Frame layout
        self.end_frame_layout = QtWidgets.QHBoxLayout()
        self.end_frame_label_text = QtWidgets.QLabel("End Frame  ") # Added space for alignment
        self.end_frame_line_edit = QtWidgets.QLineEdit()
        self.end_frame_line_edit.setValidator(QtGui.QIntValidator()) # Allow only integers
        self.end_frame_line_edit.setPlaceholderText("e.g., 1100")
        self.get_current_end_button = QtWidgets.QPushButton("结束帧")
        self.get_current_end_button.clicked.connect(self.on_get_current_end_frame) # Placeholder

        self.end_frame_layout.addWidget(self.end_frame_label_text)
        self.end_frame_layout.addWidget(self.end_frame_line_edit)
        self.end_frame_layout.addStretch() # Add some space
        # For the "End Frame" button, we can align it with the previous "Start Frame" button
        # by adding a spacer or ensuring the QHBoxLayout distributes space similarly.
        # We'll add a stretch before it to push it to the right, similar to the start frame section.
        self.end_frame_layout.addStretch()
        self.end_frame_layout.addWidget(self.get_current_end_button) # Button aligned to the right
        self.main_layout.addLayout(self.end_frame_layout)
        
        # Add some vertical spacing before the accept/cancel buttons
        self.main_layout.addSpacing(15)


        # --- Accept/Cancel Buttons ---
        self.button_layout = QtWidgets.QHBoxLayout()
        self.accept_button = QtWidgets.QPushButton("Accept")
        self.cancel_button = QtWidgets.QPushButton("Cancel")

        # Populate the combobox with qualifying cameras
        self._populate_camera_combobox() # This might disable accept_button

        self.button_layout.addStretch()
        self.button_layout.addWidget(self.accept_button)
        self.button_layout.addWidget(self.cancel_button)
        self.main_layout.addLayout(self.button_layout)

        # Connect button signals to slots
        self.accept_button.clicked.connect(self.on_accept)
        self.cancel_button.clicked.connect(self.reject)

    def _get_lowest_single_child_camera(self, node_path):
        children_transforms = cmds.listRelatives(node_path, children=True, fullPath=True, type='transform')
        if children_transforms and len(children_transforms) == 1:
            return self._get_lowest_single_child_camera(children_transforms[0])
        elif not children_transforms:
            shapes = cmds.listRelatives(node_path, shapes=True, fullPath=True)
            if shapes:
                for shape in shapes:
                    if cmds.nodeType(shape) == 'camera':
                        return shape
            return None
        else:
            return None

    def _populate_camera_combobox(self):
        self.camera_data_list = []
        self.camera_combobox.clear()
        temp_found_cameras = {}

        all_transforms = cmds.ls(type='transform', long=True)
        for transform_path in all_transforms:
            # Check if it's a top-level transform OR if it's a camera directly under an assembly root
            is_top_level = not cmds.listRelatives(transform_path, parent=True)
            is_camera_under_assembly = False
            if not is_top_level:
                parents = cmds.listRelatives(transform_path, parent=True, fullPath=True)
                if parents and cmds.ls(parents[0], assemblies=True): # Parent is an assembly
                    # Check if this transform_path itself has a camera shape and no transform children
                    # (meaning it's the 'lowest single child' for this branch starting from an assembly)
                    shapes = cmds.listRelatives(transform_path, shapes=True, fullPath=True, type='camera')
                    child_transforms = cmds.listRelatives(transform_path, children=True, type='transform')
                    if shapes and not child_transforms:
                         is_camera_under_assembly = True


            if is_top_level or is_camera_under_assembly:
                transform_short_name = transform_path.split('|')[-1]
                
                # Standard Maya default cameras
                default_cameras = {"persp", "top", "front", "side"}
                is_default_cam = transform_short_name in default_cameras
                
                camera_shape_path = None
                if is_default_cam:
                    # For default cameras, check their visibility. If visible, include them.
                    # Their shape name is usually transform_short_name + "Shape"
                    # We still use _get_lowest_single_child_camera to confirm it's a simple camera setup
                    camera_shape_path = self._get_lowest_single_child_camera(transform_path)
                    if camera_shape_path and not cmds.getAttr(transform_path + ".visibility"):
                         # If it's a default camera and it's hidden, skip it.
                        continue 
                else:
                    # For non-default cameras, or cameras under assemblies, apply the original logic
                    camera_shape_path = self._get_lowest_single_child_camera(transform_path)

                if camera_shape_path:
                    temp_found_cameras[camera_shape_path] = transform_short_name
        
        # Fallback: If the above logic missed some, iterate through all assemblies
        # This part is more like the original logic, but might be redundant or refined by the above
        top_level_assemblies = cmds.ls(assemblies=True, long=True)
        if not top_level_assemblies:
            top_level_assemblies = []
        for item_path in top_level_assemblies:
            camera_shape_path = self._get_lowest_single_child_camera(item_path)
            if camera_shape_path:
                transform_path_list = cmds.listRelatives(camera_shape_path, parent=True, fullPath=True)
                if transform_path_list:
                    transform_short_name = transform_path_list[0].split('|')[-1]
                    # Ensure it's not a hidden default camera unless explicitly visible
                    if transform_short_name in {"persp", "top", "front", "side"} and not cmds.getAttr(transform_path_list[0] + ".visibility"):
                        continue
                    temp_found_cameras[camera_shape_path] = transform_short_name


        if not temp_found_cameras:
            self.camera_combobox.addItem("No qualifying cameras found")
            self.camera_combobox.setEnabled(False)
            self.accept_button.setEnabled(False)
            return

        self.camera_data_list = sorted([(name, path) for path, name in temp_found_cameras.items()], key=lambda x: x[0])
        for display_name, cam_shape_path in self.camera_data_list:
            self.camera_combobox.addItem(display_name, cam_shape_path)

        self.camera_combobox.setEnabled(True)
        self.accept_button.setEnabled(True)

    def get_selected_camera_shape(self):
        current_index = self.camera_combobox.currentIndex()
        if current_index >= 0 and self.camera_data_list:
            if current_index < len(self.camera_data_list):
                return self.camera_data_list[current_index][1]
        return None
    
    def get_current_version(self):
        """Get next available version number for playblast files"""
        HAL_TASK_OUTPUT_ROOT = os.environ.get("HAL_TASK_OUTPUT_ROOT", "")
        playblast_dir = os.path.join(HAL_TASK_OUTPUT_ROOT, "playblast")
        
        if not os.path.exists(playblast_dir):
            return "v001"

        version_dirs = [d for d in os.listdir(playblast_dir) 
                      if os.path.isdir(os.path.join(playblast_dir, d))]
        
        version_pattern = re.compile(r'^v(\d{3,})$', re.IGNORECASE)
        max_version = 0

        for version_dir in version_dirs:
            match = version_pattern.match(version_dir)
            if match:
                version_num = int(match.group(1))
                if version_num > max_version:
                    max_version = version_num

        current_version = max_version
        return f"v{current_version:03d}", current_version

    def get_next_playblast_version(self):
        """Get next available version number for playblast files"""
        HAL_TASK_OUTPUT_ROOT = os.environ.get("HAL_TASK_OUTPUT_ROOT", "")
        playblast_dir = os.path.join(HAL_TASK_OUTPUT_ROOT, "playblast")
        
        if not os.path.exists(playblast_dir):
            return "v001"

        version_dirs = [d for d in os.listdir(playblast_dir) 
                      if os.path.isdir(os.path.join(playblast_dir, d))]
        
        version_pattern = re.compile(r'^v(\d{3,})$', re.IGNORECASE)
        max_version = 0

        for version_dir in version_dirs:
            match = version_pattern.match(version_dir)
            if match:
                version_num = int(match.group(1))
                if version_num > max_version:
                    max_version = version_num

        next_version = max_version + 1
        return f"v{next_version:03d}"

    def on_accept(self):
        selected_cam_shape = self.get_selected_camera_shape()
        start_frame_text = self.start_frame_line_edit.text()
        end_frame_text = self.end_frame_line_edit.text()

        # Validate frame inputs
        try:
            start_frame = int(start_frame_text) if start_frame_text else None
            end_frame = int(end_frame_text) if end_frame_text else None
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Input Error", "Start Frame and End Frame must be numbers.")
            return

        if selected_cam_shape:
            transform_nodes = cmds.listRelatives(selected_cam_shape, parent=True, fullPath=True)
            if transform_nodes:
                camera_path = transform_nodes[0]
                print(f"Selected camera for Playblast:")
                print(f"- Transform: {camera_path} (Shape: {selected_cam_shape})")
                
                if start_frame is None or end_frame is None:
                    QtWidgets.QMessageBox.warning(self, "Input Error", "Both start and end frames must be specified.")
                    return
                
                if start_frame > end_frame:
                    QtWidgets.QMessageBox.warning(self, "Input Error", "Start Frame cannot be greater than End Frame.")
                    return

                # Get environment variables
                HAL_TASK_OUTPUT_ROOT = os.environ.get("HAL_TASK_OUTPUT_ROOT")
                if not HAL_TASK_OUTPUT_ROOT:
                    QtWidgets.QMessageBox.warning(self, "Error", "HAL_TASK_OUTPUT_ROOT environment variable not set")
                    return
                    
                HAL_PROJECT_ABBR = os.environ.get("HAL_PROJECT_ABBR", "")
                HAL_SEQUENCE = os.environ.get("HAL_SEQUENCE", "")
                HAL_SHOT = os.environ.get("HAL_SHOT", "")
                HAL_TASK = os.environ.get("HAL_TASK", "")
                HAL_USER_ABBR = os.environ.get("HAL_USER_ABBR", "")
                
                # Create output path
                version = self.get_next_playblast_version()
                file_name = f"{HAL_PROJECT_ABBR}_{HAL_SEQUENCE}_{HAL_SHOT}_{HAL_TASK}_{version}_{HAL_USER_ABBR}"
                output_dir = os.path.join(HAL_TASK_OUTPUT_ROOT, "playblast", version)
                output_path = os.path.join(output_dir, file_name).replace(os.sep, "/")
                
                # Ensure directory exists
                os.makedirs(output_dir, exist_ok=True)
                
                try:
                    # Set camera and export playblast
                    cmds.lookThru(camera_path)
                    cmds.playblast(
                        format='image',
                        compression='jpg',
                        quality=100,
                        filename=output_path,
                        forceOverwrite=True,
                        viewer=False,
                        showOrnaments=False,
                        percent=100,
                        widthHeight=(1920, 1080),
                        startTime=start_frame,
                        endTime=end_frame,
                        clearCache=True
                    )
                    
                    # Prepare success message
                    success_msg = f"Playblast successfully created:\n{output_path}"
                    
                    # Submit to SG if checkbox is checked
                    if self.upload_sg_checkbox.isChecked():
                        try:
                            self.submit_to_SG()
                            success_msg += "\n\nPlayblast successfully submitted to ShotGrid"
                        except Exception as e:
                            success_msg += f"\n\nWarning: ShotGrid submission failed:\n{str(e)}"
                    
                    QtWidgets.QMessageBox.information(self, "Success", success_msg)
                except Exception as e:
                    QtWidgets.QMessageBox.critical(
                        self,
                        "Playblast Error",
                        f"Failed to create playblast:\n{str(e)}"
                    )
            else:
                print(f"- Shape: {selected_cam_shape} (No parent transform found - unusual)")
        else:
            print("No camera selected or no qualifying cameras were found.")
            QtWidgets.QMessageBox.information(self, "Info", "No camera selected.")


    # --- Placeholder methods for new buttons ---
    def on_get_sg_frames(self):
        try:
            from ..utils.SGlogin import ShotgunDataManager
            sg_manager = ShotgunDataManager()
            SHOTID = int(sg_manager.HAL_SHOT_SGID)
            frame_data = sg_manager.getSGData("Shot", SHOTID)
            
            sg_head_in = frame_data[0].get('sg_head_in')
            sg_tail_out = frame_data[0].get('sg_tail_out')
            sg_cut_in = frame_data[0].get('sg_cut_in')
            sg_cut_out = frame_data[0].get('sg_cut_out')

            """Set frame range from SG when button is clicked"""
            if sg_head_in is not None:
                self.start_frame_line_edit.setText(str(sg_head_in))
            else:
                if sg_cut_in is not None:
                    self.start_frame_line_edit.setText(str(int(sg_cut_in)-8))
                else:
                    self.start_frame_line_edit.setText("None")

            if sg_tail_out is not None:
                self.end_frame_line_edit.setText(str(sg_tail_out))
            else:
                if sg_cut_out is not None:
                    self.end_frame_line_edit.setText(str(int(sg_cut_out)+8))
                else:
                    self.end_frame_line_edit.setText("None")
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, 
                "Error", 
                f"Failed to get ShotGrid data:\n{str(e)}"
            )


    def on_get_current_start_frame(self):
        current_start = cmds.playbackOptions(query=True, minTime=True)
        self.start_frame_line_edit.setText(str(int(current_start)))
        print(f"Set Start Frame from timeline: {int(current_start)}")

    def open_playblast_folder(self):
        """Open Windows Explorer at the highest version playblast folder"""
        import subprocess
        HAL_TASK_OUTPUT_ROOT = os.environ.get("HAL_TASK_OUTPUT_ROOT", "")
        if not HAL_TASK_OUTPUT_ROOT:
            QtWidgets.QMessageBox.warning(self, "Error", "HAL_TASK_OUTPUT_ROOT environment variable not set")
            return
            
        playblast_dir = os.path.join(HAL_TASK_OUTPUT_ROOT, "playblast")
        if not os.path.exists(playblast_dir):
            QtWidgets.QMessageBox.information(
                self,
                "Info",
                "Playblast folder does not exist yet"
            )
            return
            
        version = self.get_current_version()[0]
        version_dir = os.path.join(playblast_dir, version)
        
        try:
            subprocess.Popen(f'explorer "{version_dir}"')
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self,
                "Error", 
                f"Could not open playblast folder:\n{str(e)}"
            )

    def on_get_current_end_frame(self):
        current_end = cmds.playbackOptions(query=True, maxTime=True)
        self.end_frame_line_edit.setText(str(int(current_end)))
        print(f"Set End Frame from timeline: {int(current_end)}")

    def get_frame_number(self, filename):
        """从文件名中提取帧号，返回整数，如果没有找到则返回None"""
        # 匹配常见的帧号模式，如.1001.或_1001.或1001.ext
        match = re.search(r'[._]?(\d+)(?:\.\w+|$)', filename)
        return int(match.group(1)) if match else None

    def submit_to_SG(self):
        """Submit playblast to ShotGrid"""
        if not self.upload_sg_checkbox.isChecked():
            return

        try:
            HAL_TASK_OUTPUT_ROOT = os.environ.get("HAL_TASK_OUTPUT_ROOT")
            if not HAL_TASK_OUTPUT_ROOT:
                QtWidgets.QMessageBox.warning(self, "Error", "HAL_TASK_OUTPUT_ROOT environment variable not set")
                return

            HAL_PROJECT_ABBR = os.environ.get("HAL_PROJECT_ABBR", "")
            HAL_SEQUENCE = os.environ.get("HAL_SEQUENCE", "")
            HAL_SHOT = os.environ.get("HAL_SHOT", "")
            HAL_TASK = os.environ.get("HAL_TASK", "")
            version = self.get_current_version()[0]
            vesionNum = self.get_current_version()[1]
            source_path = os.path.join(HAL_TASK_OUTPUT_ROOT, "playblast", version)

            if not os.path.exists(source_path):
                QtWidgets.QMessageBox.warning(self, "Error", f"Playblast folder not found: {source_path}")
                return

            # Get all non-Thumbs.db files
            folder_files = [f for f in os.listdir(source_path) if f != "Thumbs.db"]
            if not folder_files:
                QtWidgets.QMessageBox.warning(self, "Error", f"No valid files found in: {source_path}")
                return

            # Find sequence files
            sequence_files = None
            for file in folder_files:
                if fnmatch.fnmatch(file, f"*{version[1:]}*"):  # Remove 'v' from version
                    sequence_files = os.path.join(source_path, file).replace("\\", "/")
                    break

            if not sequence_files:
                sequence_files = os.path.join(source_path, folder_files[0]).replace("\\", "/")

            # Get frame numbers from UI inputs
            try:
                first_frame = f"{int(self.start_frame_line_edit.text()):04d}"
                last_frame = f"{int(self.end_frame_line_edit.text()):04d}"
            except ValueError:
                QtWidgets.QMessageBox.warning(self, "Error", "Invalid frame numbers in start/end frame fields")
                return

            # Build command
            custom_daily_tool_command = [
                "afx",
                "-a",
                f"{HAL_PROJECT_ABBR}/{HAL_SEQUENCE}/{HAL_SHOT}",
                "--task",
                HAL_TASK,
                "+p",
                "custom_daily_tool",
                "run",
                "custom_daily_tool",
                "cmdl",
                sequence_files,
                "Sequence",
                str(vesionNum),
                "--first-frame",
                first_frame,
                "--last-frame",
                last_frame
            ]

            # Execute command
            try:
                print(f"Executing command: {' '.join(custom_daily_tool_command)}")
                result = subprocess.run(
                    custom_daily_tool_command,
                    check=True,
                    shell=True,
                    capture_output=True,
                    text=True
                )
                print(f"Command output: {result.stdout}")
                if result.stderr:
                    print(f"Command errors: {result.stderr}")
                QtWidgets.QMessageBox.information(self, "Success", "Playblast successfully submitted to ShotGrid")
            except subprocess.CalledProcessError as e:
                error_msg = f"""
Command failed with exit code {e.returncode}:
Command: {' '.join(e.cmd)}
Output: {e.stdout if e.stdout else 'None'}
Error: {e.stderr if e.stderr else 'None'}
"""
                QtWidgets.QMessageBox.critical(self, "Error", error_msg)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"An error occurred: {e}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to submit to ShotGrid: {str(e)}")


# --- Global instance to keep the dialog alive ---
dialog_instance = None

def show_playblast_dialog():
    global dialog_instance
    if dialog_instance:
        try:
            dialog_instance.close()
            dialog_instance.deleteLater()
        except RuntimeError:
            dialog_instance = None
    dialog_instance = PlayblastDialog()
    dialog_instance.show()

def get_command():
    def _command():
        import importlib
        import sys
        importlib.reload(sys.modules[__name__])
        show_playblast_dialog()
    return _command

def execute():
    import importlib
    import sys
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()
