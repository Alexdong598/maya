# -*- coding: utf-8 -*-

# Run this script in your Maya environment
import os
import sys
import subprocess
import tempfile

try:
    from maya import cmds
except ImportError:
    print("WARNING: Maya environment not found. Using a mock for testing.")
    class MockCmds:
        def file(self, *args, **kwargs):
            os.environ["HAL_TASK"] = "anim"
            return "X:/project/shots/shot010/3d/anim/shot010_anim_v001.ma"
        def warning(self, msg): print(f"WARNING: {msg}")
    cmds = MockCmds()


def open_houdini_with_new_scene():
    """
    Creates a new Houdini scene in the background and then opens it in the UI.
    """
    print("\n--- Starting Maya to Houdini: Create and Open Task ---")

    # --- PART 1: CREATE THE HIP FILE IN THE BACKGROUND ---
    # This part remains mostly the same to correctly generate the file first.
    
    # (Path calculation logic is correct and remains the same)
    hal_task = os.environ.get("HAL_TASK", "").strip()
    if not hal_task:
        cmds.warning("HAL_TASK environment variable is not set.")
        return
    maya_file_path = cmds.file(query=True, sceneName=True)
    if not maya_file_path:
        cmds.warning("Maya file is not saved.")
        return
    dirname, basename = os.path.split(maya_file_path)
    parent_dir, last_folder = os.path.split(dirname)
    new_dirname = os.path.join(parent_dir, "assy") if last_folder == hal_task else dirname
    new_basename = basename.replace(hal_task, "assy") if hal_task in basename else basename
    hip_basename = os.path.splitext(new_basename)[0] + ".hip"
    output_hip_file = os.path.join(new_dirname, hip_basename).replace('\\', '/')
    print(f"Target Houdini file path: {output_hip_file}")

    # (Houdini script payload is correct and remains the same)
    houdini_script_payload = f"""
import hou, os, sys
HIP_FILE_PATH = r'{output_hip_file}'

def build_lop_network():
    print("--- Houdini Background Process Started ---")
    try:
        dir_name = os.path.dirname(HIP_FILE_PATH)
        if not os.path.exists(dir_name): os.makedirs(dir_name)
    except Exception as e:
        print(f"FATAL: Could not create directory. Error: {{e}}"); sys.exit(1)
    hou.hipFile.clear()
    stage = hou.node('/stage')
    if not stage:
        print("FATAL: Could not find /stage context."); sys.exit(1)
    print("Found /stage context. Beginning node creation...")
    try:
        print("Creating nodes...")
        usd_lop_import = stage.createNode('yu.dong::usd_lop_import', 'USD_Lop_Import')
        sop_create = stage.createNode('sopcreate', 'Sopcreate')
        usd_anim_input = stage.createNode('yu.dong::USD_anim_input::1.0', 'USD_Anim_Input')
        assy_submit = stage.createNode('yu.dong::Assy_Shotgun_Submit::1.0', 'Assy_Shotgun_Submit')
        print("All nodes created successfully.")
        
        print("Setting node positions...")
        base_pos = hou.Vector2(0, 0); usd_lop_import.setPosition(base_pos)
        sop_create.setPosition(base_pos + hou.Vector2(3, 0))
        usd_anim_input_pos = base_pos + hou.Vector2(1.5, -1.5); usd_anim_input.setPosition(usd_anim_input_pos)
        assy_submit.setPosition(usd_anim_input_pos + hou.Vector2(0, -1.5))
        
        print("Connecting nodes...")
        usd_anim_input.setInput(0, usd_lop_import, 0)
        usd_anim_input.setInput(1, sop_create, 0)
        assy_submit.setInput(0, usd_anim_input, 0)
        assy_submit.setDisplayFlag(True); assy_submit.setRenderFlag(True)
        print("Nodes connected successfully.")
    except hou.OperationFailed as e:
        print(f"FATAL ERROR: Could not create a required node. Please check if the node type is loaded."); print(f"Details: {{e}}"); sys.exit(1)
    
    hou.hipFile.save(HIP_FILE_PATH)
    print(f"Scene successfully saved to: {{HIP_FILE_PATH}}")
    print("--- Houdini Background Process Finished ---")

if __name__ == "__main__": build_lop_network()
"""

    temp_file_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as temp_f:
            temp_file_path = temp_f.name
            temp_f.write(houdini_script_payload)
        
        HAL_AREA = os.environ.get("HAL_AREA")
        HAL_TASK = os.environ.get("HAL_TASK")
        if not HAL_AREA or not HAL_TASK:
            cmds.warning("HAL_AREA or HAL_TASK environment variables not found.")
            return

        # CHANGE 1: Define two separate commands
        # Command to CREATE the file in the background
        create_file_cmd = [
            "afx", "--area", HAL_AREA, "--task", HAL_TASK,
            "run", "hython", temp_file_path.replace('\\', '/')
        ]
        
        # Command to OPEN the file in the UI
        open_houdini_cmd = [
            "afx", "--area", HAL_AREA, "--task", HAL_TASK,
            "run", "houdini", output_hip_file
        ]

        print(f"Executing background command: {' '.join(create_file_cmd)}")
        process = subprocess.Popen(
            create_file_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', shell=True if os.name == 'nt' else False
        )
        stdout, stderr = process.communicate()
        
        print("\n--- Background Process Output ---")
        print(stdout)
        if stderr: print(f"--- Errors ---\n{stderr}")
        
        if process.returncode != 0:
            print(f"❌ Failure! Could not create the Houdini file. Aborting open.")
            return

        # --- PART 2: OPEN THE CREATED FILE IN HOUDINI ---
        if os.path.exists(output_hip_file):
            print(f"✅ File created successfully. Now opening Houdini...")
            # CHANGE 2: Run the 'open' command
            # We use Popen without waiting so Maya doesn't freeze
            subprocess.Popen(open_houdini_cmd, shell=True if os.name == 'nt' else False)
        else:
            print(f"❌ Failure! The target file was not found at {output_hip_file}.")
            
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            print("Temporary script file deleted.")

# --- Maya Script Entry Point ---
if __name__ == "__main__":
    open_houdini_with_new_scene()