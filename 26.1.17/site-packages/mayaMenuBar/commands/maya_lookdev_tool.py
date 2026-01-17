# -*- coding: utf-8 -*-
import maya.cmds as cmds
import maya.mel as mel
import maya.OpenMayaUI as omui
import math
import os
import importlib
import sys
import re
from datetime import datetime

from PySide2 import QtWidgets, QtCore, QtGui
from shiboken2 import wrapInstance

# Import deadline_submit_tasks with fallback
try:
    from utils import deadline_submit_tasks
except ImportError:
    try:
        from ..utils import deadline_submit_tasks
    except ImportError:
        print("Warning: 'deadline_submit_tasks' module not found. Submission logic will run in simulation mode.")
        deadline_submit_tasks = None

# ==============================================================================
# PART 1: EMBEDDED SCRIPTS (Python 3.9 Compatible via afx)
# ==============================================================================

class EmbeddedScripts:
    """
    Holds the source code for the external scripts. 
    Running in Python 3.9 via afx, so f-strings are enabled.
    """

    # 1. THE NUKE PAYLOAD
    NUKE_PAYLOAD_CONTENT = r'''import nuke
import sys
import os

def create_nuke_setup():
    print("--- Initializing Nuke Script ---")

    defaults = {
        'source': '', 'start': 1001, 'end': 1001, 'out': '', 
        'ocio': 'EMPTY', 'lut': 'EMPTY'
    }
    
    try:
        # sys.argv mapping: 
        # [1]=source, [2]=start, [3]=end, [4]=out, [5]=ocio, [6]=lut, [7]=read_cs, [8]=write_cs
        arg_source  = sys.argv[1].replace('\\', '/') if len(sys.argv) > 1 else defaults['source']
        arg_start   = int(sys.argv[2]) if len(sys.argv) > 2 else defaults['start']
        arg_end     = int(sys.argv[3]) if len(sys.argv) > 3 else defaults['end']
        arg_out     = sys.argv[4].replace('\\', '/') if len(sys.argv) > 4 else defaults['out']
        arg_ocio    = sys.argv[5] if len(sys.argv) > 5 else defaults['ocio']
        arg_lut     = sys.argv[6].replace('\\', '/') if len(sys.argv) > 6 else defaults['lut']
        arg_read_cs = sys.argv[7] if len(sys.argv) > 7 else "ACES - ACEScg"
        arg_write_cs= sys.argv[8] if len(sys.argv) > 8 else "Output - Rec.709"
    except Exception as e:
        print(f"CRITICAL ERROR parsing arguments: {e}")
        return

    print(f"Processing: {arg_source} -> {arg_out}")

    # --- OCIO SETUP ---
    if arg_ocio and arg_ocio != "EMPTY":
        try:
            nuke.root()['colorManagement'].setValue("OCIO")
            if os.path.isfile(arg_ocio):
                nuke.root()['OCIO_config'].setValue('custom')
                nuke.root()['customOCIOConfigPath'].setValue(arg_ocio)
                print(f"OCIO Config set to Custom File: {arg_ocio}")
            else:
                nuke.root()['OCIO_config'].setValue(arg_ocio)
                print(f"OCIO Config set to Internal Preset: {arg_ocio}")
        except Exception as e:
            print(f"WARNING: Failed to set OCIO config: {e}. Using default.")

    # --- NODE GRAPH ---
    current_node = None

    # A. Read
    try:
        read_node = nuke.createNode('Read')
        read_node['file'].setValue(arg_source)
        read_node['first'].setValue(arg_start)
        read_node['last'].setValue(arg_end)
        read_node['origfirst'].setValue(arg_start)
        read_node['origlast'].setValue(arg_end)
        read_node['raw'].setValue(True) 
        current_node = read_node
    except Exception as e:
        print(f"FATAL: Could not create Read node: {e}")
        return

    # B. OCIODisplay (Color Bake)
    try:
        ocio_display = nuke.createNode('OCIODisplay')
        ocio_display.setInput(0, current_node)
        ocio_display['colorspace'].setValue(arg_read_cs) 
        ocio_display['display'].setValue('default')
        ocio_display['view'].setValue(arg_write_cs) 
        current_node = ocio_display
        print(f"OCIODisplay Applied: {arg_read_cs} -> {arg_write_cs}")
    except Exception as e:
        print(f"FATAL: OCIODisplay node failed: {e}")

    # C. Formatting & Overlay
    reformat = nuke.createNode('Reformat')
    reformat['format'].setValue('HD_1080')
    reformat['resize'].setValue('fit')
    reformat.setInput(0, current_node)
    current_node = reformat

    try:
        txt_info = nuke.createNode('Text2')
        txt_info['message'].setValue("Shotgrid Review\n[file tail [value root.name]]")
        txt_info['global_font_scale'].setValue(0.5)
        txt_info['box'].setValue([0, 0, 1920, 100])
        txt_info['xjustify'].setValue('center')
        txt_info['yjustify'].setValue('center')
        txt_info.setInput(0, current_node)
        current_node = txt_info
    except:
        pass

    # D. Write
    try:
        write = nuke.createNode('Write')
        write.setName('Output_Write')
        write['file'].setValue(arg_out)
        write['file_type'].setValue('mov')
        write['mov64_codec'].setValue('appr') # ProRes
        write['mov64_pixel_format'].setValue('{0}') 
        write['create_directories'].setValue(True)
        write['colorspace'].setValue('raw') # Baked by OCIODisplay already
        write.setInput(0, current_node)
    except Exception as e:
        print(f"FATAL: Could not create Write node: {e}")
        sys.exit(1)

    # --- EXECUTE ---
    print(f"Starting Render -> {arg_out}")
    try:
        nuke.execute(write, arg_start, arg_end, 1)
        print("Render Success.")
    except Exception as e:
        print(f"Render Failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    create_nuke_setup()
'''

# 2. THE SHOTGUN PAYLOAD
    # [FIX] Added double curly braces {{ }} for f-strings and dictionaries
    SG_PAYLOAD_CONTENT = r'''import os
import sys
import time

# --- CONFIGURATION (Injected by Maya) ---
user_name = r"{user_name}"
department = r"{department}"
# -------------------------------


try:
    import shotgun_api3
except ImportError:
    print("Error: 'shotgun_api3' module not found.")
    print("Ensure +p shotgun_api3 is included in your afx/rez command.")
    sys.exit(1)

class ShotgunSubmitter:
    def __init__(self, base_url, script_name, api_key):
        print(f"Connecting to Shotgun: {{base_url}}")
        try:
            self.sg = shotgun_api3.Shotgun(base_url, script_name, api_key)
            print("Successfully connected to Shotgun.")
        except Exception as e:
            print(f"Failed to connect to Shotgun: {{e}}")
            sys.exit(1)

    def submit_version(self, project_id, version_code, file_path, link_entity_type, link_entity_id, task_id=None, description=""):
        if not os.path.exists(file_path):
            print(f"Error: File not found: {{file_path}}")
            return False

        try:
            project_id = int(project_id)
            link_entity_id = int(link_entity_id)
            if task_id: task_id = int(task_id)
        except ValueError as e:
            print(f"Error: ID fields must be numbers. {{e}}")
            return False

        data = {{
            'project': {{'type': 'Project', 'id': project_id}},
            'code': version_code,
            'description': description,
            'entity': {{'type': link_entity_type, 'id': link_entity_id}}, 
            'sg_path_to_movie': file_path,
            'sg_status_list': 'rev',
        }}
        if task_id:
            data['sg_task'] = {{'type': 'Task', 'id': task_id}}

        print(f"Creating Version '{{version_code}}' linked to {{link_entity_type}} ID {{link_entity_id}}...")
        try:
            version = self.sg.create('Version', data)
            print(f"Version created with ID: {{version['id']}}")
        except Exception as e:
            print(f"Error creating Version entity: {{e}}")
            return False

        print(f"Uploading movie file...")
        try:
            self.sg.upload('Version', version['id'], file_path, 'sg_uploaded_movie')
            print("Upload successful!")
        except Exception as e:
            print(f"Error uploading movie: {{e}}")
            return False
        return True

def main():
    # --- CONFIGURATION ---
    base_url="https://aivfx.shotgrid.autodesk.com"
    script_name="hal_roxy_templates_rw" 
    api_key="cstmibkrtcwqmaz4sjwtexG~s"

    # If passed as args, use them (Optional robustness)
    mov_path = sys.argv[1] if len(sys.argv) > 1 else ""
    
    if not mov_path or not os.path.exists(mov_path):
        print(f"Error: No valid MOV path provided. Arg: {{mov_path}}")
        sys.exit(1)

    # Env Vars from Deadline
    project_id = int(os.environ.get("HAL_PROJECT_SGID", 0))
    raw_tree = os.environ.get("HAL_TREE", "shots").lower()
    
    if "asset" in raw_tree:
        link_type = "Asset"
        link_id = int(os.environ.get("HAL_ASSET_SGID", 0))
    else:
        link_type = "Shot"
        link_id = int(os.environ.get("HAL_SHOT_SGID", 0))

    task_id = int(os.environ.get("HAL_TASK_SGID", 0))

    code = os.path.splitext(os.path.basename(mov_path))[0]
    description = user_name + " from " + department + " has finished lookdev render and submit to Shotgun (Auto Submit)"

    if project_id == 0 or link_id == 0:
        print(f"Error: Missing Environment Variables. PID: {{project_id}}, LinkID: {{link_id}}")
        sys.exit(1)

    submitter = ShotgunSubmitter(base_url, script_name, api_key)
    success = submitter.submit_version(project_id, code, mov_path, link_type, link_id, task_id, description)

    if not success: sys.exit(1)

if __name__ == "__main__":
    main()
'''

    # 3. THE LAUNCHER (Run via afx/python 3.9)
    LAUNCHER_TEMPLATE = r'''import os
import re
import subprocess
import sys

# --- CONFIGURATION (Injected by Maya) ---
NUKE_PROCESS_SCRIPT = r"{nuke_script}"
EXR_FOLDER_ROOT = r"{exr_folder}"
OUTPUT_MOV = r"{mov_out}"
READ_COLORSPACE = "{read_cs}"
WRITE_COLORSPACE = "{write_cs}"
# -------------------------------

def find_exr_sequence(folder):
    if not os.path.exists(folder): return None, 0, 0
    files = [f for f in os.listdir(folder) if f.endswith('.exr')]
    if not files: return None, 0, 0
    files.sort()
    
    # Simple Frame extraction
    frames = []
    pattern_candidate = ""
    
    for f in files:
        match = re.search(r'[._](\d+)\.exr$', f)
        if match:
            frames.append(int(match.group(1)))
            if not pattern_candidate:
                frame_str = match.group(1)
                padding = len(frame_str)
                # Double braces to escape f-string in template
                pad_str = f"%0{{padding}}d"
                pattern_candidate = f.replace(frame_str, pad_str)
                
    if not frames: return None, 0, 0
    full_path = os.path.join(folder, pattern_candidate).replace('\\', '/')
    return full_path, min(frames), max(frames)

def open_nuke():
    def get_hal_file_path():
        NUKE16 = "nuke_16.hal"
        HAL_ETC = os.environ.get("HAL_ETC", "")
        if HAL_ETC: return os.path.join(HAL_ETC, NUKE16)
        return NUKE16
    
    def get_packages_section(file_path):
        try:
            with open(file_path, 'r') as file:
                parts = file.read().split("packages:")
                if len(parts) > 1: return parts[1].strip()
        except: pass
        return None
        
    def get_clean_packages_list(packages_section):
        if not packages_section: return []
        clean = []
        for line in packages_section.splitlines():
            s = line.strip()
            if not s or s.startswith('#'): continue
            match = re.search(r'-\s*(.*)', s)
            if match: clean.append(match.group(1).strip())
        args = []
        for pkg in clean: args.extend(['+p', pkg])
        return args

    hal_file = get_hal_file_path()
    pkgs = get_packages_section(hal_file)
    pkg_args = get_clean_packages_list(pkgs)
    
    HAL_AREA = os.environ.get("HAL_AREA", "default")
    HAL_TASK = os.environ.get("HAL_TASK", "default")
    nuke_exe = r"\\af\x\app\ext\nuke\16.0.1\platform-windows\nuke\Nuke16.0.exe"
    
    cmd = ["afx.cmd", "--area", HAL_AREA, "--task", HAL_TASK, "run", nuke_exe]
    
    if pkg_args:
        if "run" in cmd:
            idx = cmd.index("run")
            cmd[idx:idx] = pkg_args
        else:
            cmd.insert(1, pkg_args)
    return cmd

def run_nuke_render(cmd_list, script, exr, start, end, mov, ocio_env):
    if "%04d" in exr: exr = exr.replace("%04d", "%%04d")
    
    args = [
        "-t", script, exr, str(start), str(end), mov,
        ocio_env if ocio_env else "EMPTY", "EMPTY",
        READ_COLORSPACE, WRITE_COLORSPACE
    ]
    
    full = cmd_list + args
    
    # Double braces for template safety
    print(f"Executing: {{full}}")
    
    proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    while True:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None: break
        if line: print(line.strip())
    
    if proc.poll() != 0:
        # Double braces for template safety
        raise RuntimeError(f"Nuke failed with code {{proc.poll()}}")

def main():
    exr_path, start, end = find_exr_sequence(EXR_FOLDER_ROOT)
    if not exr_path:
        print("Could not find valid EXR sequence.")
        sys.exit(1)
        
    ocio_path = os.environ.get("OCIO", "")
    nuke_cmd = open_nuke()
    run_nuke_render(nuke_cmd, NUKE_PROCESS_SCRIPT, exr_path, start, end, OUTPUT_MOV, ocio_path)

if __name__ == "__main__":
    main()
'''

# ==============================================================================
# PART 2: LOGIC CORE
# ==============================================================================

class LookdevLogic:
    REFERENCE_PATH = "U:/_lookdev/maya/antares_image_lookdev_v04.mb"
    HDR_LIBRARY_PATH = "U:/_lookdev/HDR"
    THUMB_FOLDER_NAME = "_thumbnails" 
    
    CONTROLLER = 'turntableControl'
    CAMERA_SHAPE = 'cam_tntblShape' 
    REF_OBJ_ROOT = 'ASSET_ANIM'
    VIEW_PANEL = 'perspView'

    cam_pull_value = 0

    @staticmethod
    def calculate_framing_distance(camera_shape_name, object_name):
        try:
            if not cmds.objExists(camera_shape_name) or cmds.nodeType(camera_shape_name) != 'camera':
                return None
            
            fov_h_deg = cmds.camera(camera_shape_name, query=True, horizontalFieldOfView=True)
            fov_v_deg = cmds.camera(camera_shape_name, query=True, verticalFieldOfView=True)
            fov_h_rad = math.radians(fov_h_deg)
            fov_v_rad = math.radians(fov_v_deg)
            
            bbox = cmds.xform(object_name, query=True, boundingBox=True, worldSpace=True)
            obj_width = bbox[3] - bbox[0]
            obj_height = bbox[4] - bbox[1]

            if obj_width == 0 and obj_height == 0: return 0.0
            
            dist_for_width = (obj_width / 2.0) / math.tan(fov_h_rad / 2.0) if fov_h_rad > 0 else float('inf')
            dist_for_height = (obj_height / 2.0) / math.tan(fov_v_rad / 2.0) if fov_v_rad > 0 else float('inf')
            
            fit_distance = max(dist_for_width, dist_for_height)
            return fit_distance * 1.1 
            
        except Exception as e:
            cmds.warning(f"Calculation Error: {e}")
            return None

    @classmethod
    def run_setup(cls):
        selection = cmds.ls(selection=True, type='transform')
        if len(selection) != 1:
            return False, "Error: Please select ONE object before running.", None

        true_obj_name = selection[0]
        true_obj_bbox = cmds.xform(true_obj_name, query=True, boundingBox=True, worldSpace=True)
        true_obj_height = true_obj_bbox[4] - true_obj_bbox[1]

        if not os.path.exists(cls.REFERENCE_PATH):
            cmds.warning(f"Path not found: {cls.REFERENCE_PATH}.")

        try:
            is_imported = False
            refs = cmds.file(q=True, reference=True) or []
            for r in refs:
                if "antares_image_lookdev" in r:
                    is_imported = True
            
            if not is_imported:
                cmds.file(cls.REFERENCE_PATH, i=True, type="mayaBinary", ignoreVersion=True, 
                          mergeNamespacesOnClash=False, namespace=":")
        except Exception as e:
            return False, f"Import Error: {str(e)}", None, None, None

        new_cam_pull = cls.calculate_framing_distance(cls.CAMERA_SHAPE, true_obj_name)
        new_cam_height = true_obj_height / 2.0

        if new_cam_pull is None:
            return False, "Camera Calculation Failed", None, None, None

        cls.cam_pull_value = new_cam_pull

        if cmds.objExists(cls.CONTROLLER):
            cmds.lookThru(cls.VIEW_PANEL, cls.CONTROLLER) 
        
        # --- APPLY DEFAULTS & CALCULATIONS ---
        if cmds.objExists(cls.CONTROLLER):
            if cmds.attributeQuery('cam_height', node=cls.CONTROLLER, exists=True):
                cmds.setAttr(f'{cls.CONTROLLER}.cam_height', new_cam_height)
            if cmds.attributeQuery('cam_pull', node=cls.CONTROLLER, exists=True):
                cmds.setAttr(f'{cls.CONTROLLER}.cam_pull', new_cam_pull)
            if cmds.attributeQuery('focusLength', node=cls.CONTROLLER, exists=True):
                cmds.setAttr(f'{cls.CONTROLLER}.focusLength', 85)

        if cmds.objExists(cls.REF_OBJ_ROOT):
            ref_children = cmds.listRelatives(cls.REF_OBJ_ROOT, children=True, type='transform') or []
            for child in ref_children:
                if child != true_obj_name:
                    cmds.setAttr(f'{child}.visibility', 0)
            
            try:
                cmds.parent(true_obj_name, cls.REF_OBJ_ROOT)
            except:
                pass 
        
        return True, f"Setup Complete for {true_obj_name}", true_obj_name, new_cam_pull, new_cam_height

# ==============================================================================
# PART 3: MAIN QT INTERFACE
# ==============================================================================

def get_maya_window():
    """Get Maya's main window as a parent widget."""
    ptr = omui.MQtUtil.mainWindow()
    if ptr:
        return wrapInstance(int(ptr), QtWidgets.QWidget)
    return None

class LookdevToolUI(QtWidgets.QDialog):
    def __init__(self, parent=get_maya_window()):
        super(LookdevToolUI, self).__init__(parent)
        
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowMinimizeButtonHint | QtCore.Qt.WindowMaximizeButtonHint | QtCore.Qt.WindowCloseButtonHint)
        self.setWindowTitle("Antares Lookdev Manager")
        self.resize(450, 650)
        
        self.logic = LookdevLogic()
        self.true_obj_name = None 
        
        self.create_widgets()
        self.create_layouts()
        self.create_connections()
        
        self.populate_hdri_library()
        QtCore.QTimer.singleShot(200, self.read_scene_settings)

    def create_widgets(self):
        # Core
        self.btn_run_setup = QtWidgets.QPushButton("RE-IMPORT & FRAME")
        self.btn_run_setup.setMinimumHeight(35)
        self.btn_run_setup.setStyleSheet("background-color: #5D8AA8; color: white; font-weight: bold; font-size: 12px;")
        
        # Camera Settings
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QtWidgets.QWidget()
        self.scroll_area.setWidget(self.scroll_content)
        self.ctrl_widgets = {} 

        # Time
        self.gb_time = QtWidgets.QGroupBox("Turntable Info")
        self.lbl_time_info = QtWidgets.QLabel("Frame Range Locked: 1001 - 1072")
        self.lbl_time_info.setStyleSheet("color: #AAA; font-style: italic;")
        self.lbl_time_info.setAlignment(QtCore.Qt.AlignCenter)

        # Library
        self.gb_library = QtWidgets.QGroupBox("Antares HDR Library")
        self.list_hdri = QtWidgets.QListWidget()
        self.list_hdri.setViewMode(QtWidgets.QListWidget.IconMode)
        self.list_hdri.setResizeMode(QtWidgets.QListWidget.Adjust)
        self.list_hdri.setIconSize(QtCore.QSize(120, 60)) 
        self.list_hdri.setSpacing(5)
        self.list_hdri.setStyleSheet("""
            QListWidget { background-color: #2b2b2b; }
            QListWidget::item { background: #333; border-radius: 4px; padding: 5px; color: #ddd; } 
            QListWidget::item:selected { background: #5D8AA8; color: white; }
        """)
        self.list_hdri.setMinimumHeight(120)
        
        # Manual
        self.gb_manual = QtWidgets.QGroupBox("Custom HDRI")
        self.le_hdri_path = QtWidgets.QLineEdit()
        self.le_hdri_path.setPlaceholderText("Or browse for .exr/.hdr...")
        self.btn_browse_hdri = QtWidgets.QPushButton("...")
        self.btn_browse_hdri.setFixedWidth(30)
        
        # Deadline
        self.btn_submit_deadline = QtWidgets.QPushButton("SUBMIT TO DEADLINE")
        self.btn_submit_deadline.setMinimumHeight(35)
        self.btn_submit_deadline.setStyleSheet("background-color: #5D8A5B; color: white; font-weight: bold; font-size: 12px;")
        self.btn_submit_deadline.setEnabled(False) 

    def create_layouts(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        title = QtWidgets.QLabel("ANTARES PIPELINE")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-weight: bold; color: #5D8AA8; margin-bottom: 5px;")
        main_layout.addWidget(title)
        main_layout.addWidget(self.btn_run_setup)

        form_layout = QtWidgets.QFormLayout(self.scroll_content)
        form_layout.setLabelAlignment(QtCore.Qt.AlignRight)
        
        # 1. Focus Length
        self.add_float_control(form_layout, "焦距(一般不调)", "focusLength", 0, 100, 1)
        
        # 2. Chromeballs Size (Fixed 50-100, Default 60)
        self.add_float_control(form_layout, "镜面球和色卡的大小", "chromeballs_size", 50, 100, 1)
        if hasattr(self, 'ctrl_widgets') and 'chromeballs_size' in self.ctrl_widgets:
             self.ctrl_widgets['chromeballs_size']['spin'].setValue(60)

        # 3. Cam Pull (Dynamic Range)
        # Determine initial range based on whether run_setup has happened recently
        current_pull = self.logic.cam_pull_value
        if current_pull > 0:
            min_p = current_pull * 0.5
            max_p = current_pull * 2.0
        else:
            # Default fallback if tool opened fresh
            min_p = 0
            max_p = 500
            
        self.add_float_control(form_layout, "照相机推拉", "cam_pull", min_p, max_p, 1)

        self.gb_camera = QtWidgets.QGroupBox("Settings")
        gb_cam_layout = QtWidgets.QVBoxLayout()
        gb_cam_layout.addWidget(self.scroll_area)
        self.gb_camera.setLayout(gb_cam_layout)
        
        main_layout.addWidget(self.gb_camera) 

        time_layout = QtWidgets.QVBoxLayout()
        time_layout.addWidget(self.lbl_time_info)
        self.gb_time.setLayout(time_layout)
        main_layout.addWidget(self.gb_time)

        lib_layout = QtWidgets.QVBoxLayout()
        lib_layout.addWidget(self.list_hdri)
        self.gb_library.setLayout(lib_layout)
        main_layout.addWidget(self.gb_library, stretch=1)

        man_layout = QtWidgets.QHBoxLayout()
        man_layout.addWidget(self.le_hdri_path)
        man_layout.addWidget(self.btn_browse_hdri)
        self.gb_manual.setLayout(man_layout)
        main_layout.addWidget(self.gb_manual)
        
        main_layout.addSpacing(10)
        main_layout.addWidget(self.btn_submit_deadline)

    # --- WIDGET BUILDERS ---
    def add_float_control(self, layout, label_text, attr_name, min_v, max_v, step):
        container = QtWidgets.QWidget()
        h_layout = QtWidgets.QHBoxLayout(container)
        h_layout.setContentsMargins(0,0,0,0)
        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(int(min_v), int(max_v)) 
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(min_v, max_v)
        spin.setSingleStep(step)
        spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        spin.setFixedWidth(60)

        slider.valueChanged.connect(lambda val: spin.setValue(val))
        spin.valueChanged.connect(lambda val: slider.setValue(int(val)))
        spin.valueChanged.connect(lambda val: self.update_maya_attr(attr_name, val))
        h_layout.addWidget(slider)
        h_layout.addWidget(spin)
        layout.addRow(label_text + ":", container)
        self.ctrl_widgets[attr_name] = {'type': 'float', 'spin': spin, 'slider': slider}

    def add_enum_control(self, layout, label_text, attr_name):
        combo = QtWidgets.QComboBox()
        combo.addItems(["Off", "On"])
        combo.currentIndexChanged.connect(lambda val: self.update_maya_attr(attr_name, val))
        layout.addRow(label_text + ":", combo)
        self.ctrl_widgets[attr_name] = {'type': 'enum', 'widget': combo}

    def create_connections(self):
        self.btn_run_setup.clicked.connect(self.on_run_setup)
        self.btn_browse_hdri.clicked.connect(self.browse_hdri)
        self.list_hdri.itemClicked.connect(self.on_library_item_clicked)
        self.btn_submit_deadline.clicked.connect(self.on_submit_to_deadline)

    def update_cam_pull_range(self, center_val):
        """Updates the Cam Pull slider range dynamically based on calculation."""
        if 'cam_pull' in self.ctrl_widgets:
            widgets = self.ctrl_widgets['cam_pull']
            min_val = center_val * 0.5
            max_val = center_val * 2.0
            
            # Block signals to avoid loops during range update
            widgets['slider'].blockSignals(True)
            widgets['spin'].blockSignals(True)
            
            widgets['slider'].setRange(int(min_val), int(max_val))
            widgets['spin'].setRange(min_val, max_val)
            widgets['spin'].setValue(center_val) 
            
            widgets['slider'].blockSignals(False)
            widgets['spin'].blockSignals(False)

    # --- HELPERS ---
    def populate_hdri_library(self):
        hdr_root = self.logic.HDR_LIBRARY_PATH
        thumb_root = os.path.join(hdr_root, self.logic.THUMB_FOLDER_NAME)
        if not os.path.exists(thumb_root): return

        self.list_hdri.clear()
        try:
            thumb_files = os.listdir(thumb_root)
        except Exception: return

        for t_file in thumb_files:
            if not t_file.lower().endswith(('.png', '.jpg', '.jpeg')): continue
            base_name = os.path.splitext(t_file)[0]
            expected_tx_name = base_name + ".tx"
            full_tx_path = os.path.join(hdr_root, expected_tx_name)
            if os.path.exists(full_tx_path):
                full_thumb_path = os.path.join(thumb_root, t_file)
                item = QtWidgets.QListWidgetItem(base_name)
                item.setData(QtCore.Qt.UserRole, full_tx_path.replace('\\', '/'))
                item.setIcon(QtGui.QIcon(full_thumb_path))
                self.list_hdri.addItem(item)

    def on_library_item_clicked(self, item):
        tx_path = item.data(QtCore.Qt.UserRole)
        self.le_hdri_path.setText(tx_path) 
        self.apply_hdri(tx_path)

    # --- DEADLINE LOGIC ---
    def get_scene_name(self):
        scene_name = cmds.file(q=True, sn=True, shn=True)
        return os.path.splitext(scene_name)[0] if scene_name else "untitled"

    def get_version_from_scene(self):
        scene_path = cmds.file(q=True, sn=True)
        if not scene_path: return "v000_unSaved"
        match = re.search(r'[vV](\d{3,})', os.path.basename(scene_path))
        return match.group(0).lower() if match else "v000_noVersion"

    def get_render_output_dir(self):
        return os.environ.get("HAL_TASK_ROOT", ""), os.environ.get("HAL_TASK_OUTPUT_ROOT", "")

    def get_custom_prefix(self):
        self.HAL_USER_ABBR = os.environ.get("HAL_USER_ABBR", "user")
        self.HAL_USER_LOGIN = os.environ.get("HAL_USER_LOGIN", "userName")
        self.HAL_PROJECT_ABBR = os.environ.get("HAL_PROJECT_ABBR", "proj")
        self.HAL_SEQUENCE = os.environ.get("HAL_SEQUENCE", "seq")
        self.HAL_SHOT = os.environ.get("HAL_SHOT", "shot")
        self.HAL_TASK = os.environ.get("HAL_TASK", "task")
        version = self.get_version_from_scene()
        return f"<RenderLayer>/{version}/fullres/<RenderPass>/{self.HAL_PROJECT_ABBR}_{self.HAL_SEQUENCE}_{self.HAL_SHOT}_{self.HAL_TASK}_<RenderLayer>_{version}_{self.HAL_USER_ABBR}.<RenderPass>"

    def get_final_output_path(self, output_dir, prefix, frame_padding="####", img_fmt="exr"):
        outputPath = f"{output_dir}/{prefix}.{frame_padding}.{img_fmt}"
        return outputPath.replace(os.sep, "/")
        
    def collect_environment_vars(self):
        env_dict = {}
        for k, v in os.environ.items():
            if k.startswith("HAL_") or k == "OCIO":
                env_dict[k] = v
        return env_dict

    def generate_scripts_on_disk(self, directory, nuke_script_name, sg_script_name, launcher_name, mov_path, user_name, department):
        nuke_payload_path = os.path.join(directory, nuke_script_name).replace('\\', '/')
        with open(nuke_payload_path, 'w') as f:
            f.write(EmbeddedScripts.NUKE_PAYLOAD_CONTENT)
            
        sg_payload_content = EmbeddedScripts.SG_PAYLOAD_CONTENT.format(
            user_name=user_name,
            department=department
        )
        sg_payload_path = os.path.join(directory, sg_script_name).replace('\\', '/')
        with open(sg_payload_path, 'w') as f:
            f.write(sg_payload_content)
            
        launcher_content = EmbeddedScripts.LAUNCHER_TEMPLATE.format(
            nuke_script=nuke_payload_path,
            exr_folder=directory,
            mov_out=mov_path,
            read_cs="ACES - ACEScg", 
            write_cs="Output - Rec.709",
        )
        launcher_path = os.path.join(directory, launcher_name).replace('\\', '/')
        with open(launcher_path, 'w') as f:
            f.write(launcher_content)
            
        return nuke_payload_path, sg_payload_path, launcher_path

    # --- SUBMIT ---
    def on_submit_to_deadline(self):
        if deadline_submit_tasks is None:
            QtWidgets.QMessageBox.critical(self, "Error", "Deadline module not found.")
            return

        if not self.true_obj_name:
            QtWidgets.QMessageBox.warning(self, "No Object", "Please run setup first.")
            return
            
        # =========================================================
        # FORCE NAMING: name.####.exr (OpenEXR, Frame Before Ext, Dot)
        # =========================================================
        try:
            cmds.setAttr("defaultRenderGlobals.animation", 1)
            cmds.setAttr("defaultRenderGlobals.outFormatControl", 2)
            cmds.setAttr("defaultRenderGlobals.putFrameBeforeExt", 1)
            cmds.setAttr("defaultRenderGlobals.extensionPadding", 4)
            cmds.setAttr("defaultRenderGlobals.periodInExt", 1)
            cmds.setAttr("defaultRenderGlobals.imageFormat", 51) 
            print("Render Globals updated: Forced name.####.exr format.")
        except Exception as e:
            print(f"Warning: Could not set Render Globals: {e}")
        # =========================================================

        file_path = cmds.file(q=True, sn=True)
        if not file_path:
            QtWidgets.QMessageBox.warning(self, "Unsaved File", "Please save scene.")
            return
            
        try:
            cmds.file(save=True)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save Failed", f"Error: {e}")
            return

        # 1. Gather Info
        layer_name = self.true_obj_name
        render_pass = "beauty"
        scene_name = self.get_scene_name()
        
        timestamp = datetime.now().strftime("%H%M%S")
        batch_name = f"{scene_name}_{timestamp}"

        project_path, output_path = self.get_render_output_dir()
        
        raw_prefix = self.get_custom_prefix()
        maya_prefix = raw_prefix.replace("<RenderLayer>", layer_name)

        base_output_string = self.get_final_output_path(output_path, raw_prefix, "####", "exr")
        final_output = base_output_string.replace("<RenderLayer>", layer_name).replace("<RenderPass>", render_pass)
        final_output_windows = final_output.replace("/", "\\")
        
        exr_directory = os.path.dirname(final_output_windows).replace('\\', '/')
        mov_filename = f"{os.path.basename(final_output).split('.')[0]}.mov"
        mov_output_path = os.path.join(exr_directory, mov_filename).replace('\\', '/')

        if not os.path.exists(exr_directory):
            try: os.makedirs(exr_directory)
            except OSError: pass 

        # 2. GENERATE HELPER SCRIPTS
        print("Generating helper scripts in render folder...")
        try:
            n_script, sg_script, l_script = self.generate_scripts_on_disk(
                exr_directory, 
                "payload_nuke.py", 
                "payload_sg.py", 
                "launcher_bridge.py",
                mov_output_path,
                self.HAL_USER_LOGIN,
                self.HAL_TASK
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to generate scripts: {e}")
            return

        env_vars = self.collect_environment_vars()

        # 3. JOB 1: MAYA RENDER
        maya_job_info = {
            "Name": f"{scene_name}_{layer_name} [Maya]",
            "Plugin": "MayaBatch",
            "Frames": "1001-1072",
            "BatchName": batch_name,
            "Department": os.environ.get("HAL_TASK", "task"),
            "Pool": "3d",
            "SecondaryPool": "3d",
            "Group": "3d",
            "Priority": 50,
            "OutputFilename0": final_output_windows
        }
        for i, (k, v) in enumerate(env_vars.items()): maya_job_info[f"EnvironmentKeyValue{i}"] = f"{k}={v}"

        maya_plugin_info = {
            "SceneFile": file_path,
            "Version": "2024",
            "Renderer": "arnold",
            "Build": "64bit",
            "ProjectPath": project_path.replace("/", "\\"),
            "OutputFilePath": output_path.replace("/", "\\"),
            "OutputFilePrefix": maya_prefix,
            "RenderLayer": "defaultRenderLayer", 
            "Camera": self.logic.CAMERA_SHAPE, 
            "ImageWidth": 1920,
            "ImageHeight": 1080,
            "Animation": 1,
            "ImageFormat": "exr",
            "UsingRenderLayers": 1
        }

        # 4. JOB 2: NUKE (VIA COMMANDLINE + AFX)
        nuke_job_info = {
            "Name": f"{scene_name}_{layer_name} [Nuke]",
            "Plugin": "CommandLine", 
            "Frames": "0", 
            "BatchName": batch_name,
            "Department": os.environ.get("HAL_TASK", "task"),
            "Pool": "all", 
            "SecondaryPool": "all",
            "Group": "all",
            "Priority": 50,
        }
        for i, (k, v) in enumerate(env_vars.items()): nuke_job_info[f"EnvironmentKeyValue{i}"] = f"{k}={v}"

        nuke_plugin_info = {
            "Executable": "afx.cmd",
            "Arguments": f'+p python==3.9.13 run python "{l_script}"'
        }

        # 5. JOB 3: SHOTGUN (VIA COMMANDLINE + AFX)
        sg_job_info = {
            "Name": f"{scene_name}_{layer_name} [Shotgun]",
            "Plugin": "CommandLine", 
            "Frames": "0",
            "BatchName": batch_name,
            "Department": "production",
            "Pool": "all", 
            "SecondaryPool": "all",
            "Group": "all",
            "Priority": 50
        }
        for i, (k, v) in enumerate(env_vars.items()): sg_job_info[f"EnvironmentKeyValue{i}"] = f"{k}={v}"

        sg_plugin_info = {
            "Executable": "afx.cmd",
            "Arguments": f'+p python==3.9.13 +p shotgun_api3 run python "{sg_script}" "{mov_output_path}"'
        }

        # 6. Execute
        self.btn_submit_deadline.setEnabled(False)
        self.btn_submit_deadline.setText("SUBMITTING...")
        QtCore.QCoreApplication.processEvents()

        try:
            print("--- Submitting Maya Job ---")
            maya_job_id = deadline_submit_tasks.deadline_submit(maya_job_info, maya_plugin_info)
            if not maya_job_id: raise RuntimeError("Maya Job Submission Failed")

            print("--- Submitting Nuke Job ---")
            nuke_job_info["JobDependencies"] = str(maya_job_id)
            nuke_job_id = deadline_submit_tasks.deadline_submit(nuke_job_info, nuke_plugin_info)
            if not nuke_job_id: raise RuntimeError("Nuke Job Submission Failed")

            print("--- Submitting Shotgun Job ---")
            sg_job_info["JobDependencies"] = str(nuke_job_id)
            sg_job_id = deadline_submit_tasks.deadline_submit(sg_job_info, sg_plugin_info)
            if not sg_job_id: raise RuntimeError("Shotgun Job Submission Failed")

            msg = f"Chain Submitted:\n1. Maya: {maya_job_id}\n2. Nuke: {nuke_job_id}\n3. SG: {sg_job_id}"
            QtWidgets.QMessageBox.information(self, "Success", msg)
            cmds.inViewMessage(amg=f'<span style=\"color: lime;\">Jobs Submitted</span>', pos='midCenter', fade=True)

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Submission Failed", f"Error:\n{e}")
        finally:
            self.btn_submit_deadline.setEnabled(True)
            self.btn_submit_deadline.setText("SUBMIT TO DEADLINE")

    # --- SCENE INTERACTION ---
    def force_timeline(self):
        start_frame, end_frame = 1001, 1072
        cmds.playbackOptions(min=start_frame, max=end_frame, animationStartTime=start_frame, animationEndTime=end_frame)
        cmds.currentTime(start_frame)

    def on_run_setup(self):
        msg_box = QtWidgets.QMessageBox(get_maya_window()) 
        msg_box.setWindowTitle("Lookdev Check")
        msg_box.setText(u"即将准备进行lookdev，请选择是否要继续？") 
        msg_box.setIcon(QtWidgets.QMessageBox.Question)
        btn_yes = msg_box.addButton("Yes", QtWidgets.QMessageBox.YesRole)
        btn_no = msg_box.addButton("No", QtWidgets.QMessageBox.NoRole)
        msg_box.exec_()

        if msg_box.clickedButton() != btn_yes: return

        # Unpack the 5 values returned by run_setup
        success, message, obj_name, new_pull, new_height = self.logic.run_setup()
        
        self.force_timeline()
        
        if success:
            self.true_obj_name = obj_name 
            self.btn_submit_deadline.setEnabled(True) 
            
            # Update the Cam Pull slider range dynamically
            if new_pull:
                self.update_cam_pull_range(new_pull)

            cmds.inViewMessage(amg=f'<span style=\"color: lime;\">{message}</span>', pos='midCenter', fade=True)
            self.read_scene_settings()
        else:
            self.true_obj_name = None 
            self.btn_submit_deadline.setEnabled(False) 
            cmds.inViewMessage(amg=f'<span style=\"color: red;\">{message}</span>', pos='midCenter', fade=True)

    def update_maya_attr(self, attr_name, value):
        full_attr = f"{self.logic.CONTROLLER}.{attr_name}"
        if cmds.objExists(full_attr):
            try: cmds.setAttr(full_attr, value)
            except: pass

    def browse_hdri(self):
        f_path = cmds.fileDialog2(fileFilter="HDRI Files (*.exr *.hdr *.tx);;All Files (*.*)", dialogStyle=2, fm=1)
        if f_path:
            self.le_hdri_path.setText(f_path[0])
            self.apply_hdri(f_path[0])

    def apply_hdri(self, path):
        dome_lights = cmds.ls(type='aiSkyDomeLight')
        target = dome_lights[0] if dome_lights else None
        if target:
            color_attr = f"{target}.color"
            conns = cmds.listConnections(color_attr, type='file')
            file_node = conns[0] if conns else cmds.shadingNode('file', asTexture=True)
            if not conns: cmds.connectAttr(f"{file_node}.outColor", color_attr, force=True)
            cmds.setAttr(f"{file_node}.fileTextureName", path, type="string")
            print(f"HDRI Applied: {path}")

    def read_scene_settings(self):
        node, root = self.logic.CONTROLLER, self.logic.REF_OBJ_ROOT
        found_active_obj = None
        if cmds.objExists(node) and cmds.objExists(root):
            for child in (cmds.listRelatives(root, children=True, type='transform') or []):
                try: 
                    if cmds.getAttr(f'{child}.visibility'): 
                        found_active_obj = child
                        break
                except: pass
        
        self.true_obj_name = found_active_obj
        self.btn_submit_deadline.setEnabled(bool(found_active_obj))
        
        if not cmds.objExists(node): return

        for attr, widgets in self.ctrl_widgets.items():
            full_attr = f"{node}.{attr}"
            if cmds.objExists(full_attr):
                try:
                    val = cmds.getAttr(full_attr)
                    if widgets['type'] == 'float':
                        widgets['spin'].blockSignals(True)
                        widgets['slider'].blockSignals(True)
                        widgets['spin'].setValue(val)
                        widgets['slider'].setValue(int(val))
                        widgets['spin'].blockSignals(False)
                        widgets['slider'].blockSignals(False)
                    elif widgets['type'] == 'enum':
                        widgets['widget'].blockSignals(True)
                        widgets['widget'].setCurrentIndex(int(val))
                        widgets['widget'].blockSignals(False)
                except:
                    pass

# ==============================================================================
# PART 4: LAUNCHER
# ==============================================================================

def get_command():
    def _command():
        global lookdev_ui_instance
        try:
            lookdev_ui_instance.close()
            lookdev_ui_instance.deleteLater()
        except: pass
        lookdev_ui_instance = LookdevToolUI()
        lookdev_ui_instance.show()
    return _command

def execute():
    importlib.reload(sys.modules[__name__])
    if deadline_submit_tasks:
        try:
            importlib.reload(deadline_submit_tasks)
            print("Reloaded 'deadline_submit_tasks'")
        except: pass
    cmd = get_command()
    cmd()