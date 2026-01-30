import os
import re
import subprocess
import importlib
import sys
from maya.cmds import warning

def open_maya_smarter():
    """
    Launch a new Maya instance with smarter logic for selecting the configuration file.
    """
    try:
        print("--- Starting Maya Launch Script (Smarter Version) ---")

        def get_hal_file_path():
            """
            Finds the path to the relevant maya.hal file.
            NEW: Prefers 'project' paths over others.
            """
            HAL_CONFIG_PATHS = os.environ.get("HAL_CONFIG_PATH", "").split(";")
            print(f"[DEBUG] HAL_CONFIG_PATHS: {HAL_CONFIG_PATHS}")
            HAL_ETC = os.environ.get("HAL_ETC", "")
            
            candidates = []
            for path in HAL_CONFIG_PATHS:
                if not path or path == HAL_ETC:
                    continue
                try:
                    if "maya.hal" in os.listdir(path):
                        print(f"[DEBUG] Found 'maya.hal' candidate: {path}")
                        candidates.append(path)
                except OSError:
                    continue

            if not candidates:
                print("[DEBUG] No candidate paths with 'maya.hal' found.")
                return None

            # --- MODIFIED LOGIC ---
            # We now prefer configuration files from a 'project' directory, as they are
            # more likely to contain the primary package definitions, while 'machine'
            # configs are often just for overrides.
            project_paths = [p for p in candidates if 'project' in p]
            
            if project_paths:
                # If we found any paths with 'project' in them, use the longest of those.
                selected_path = max(project_paths, key=len)
                print(f"[DEBUG] Selected preferred project-level config path: {selected_path}")
            else:
                # Otherwise, fall back to the original logic of just picking the longest path.
                selected_path = max(candidates, key=len)
                print(f"[DEBUG] No project path found. Selected config path based on length: {selected_path}")
            
            return selected_path

        def get_packages_section(path):
            """Reads the 'packages:' section from the maya.hal file."""
            if not path:
                return None
            file_path = os.path.join(path, "maya.hal")
            print(f"[DEBUG] Attempting to read packages from: {file_path}")
            try:
                with open(file_path, 'r') as file:
                    content = file.read()
                    parts = content.split("packages:")
                    if len(parts) > 1:
                        packages_section = parts[1].strip()
                        print(f"[DEBUG] Found packages section:\n---\n{packages_section}\n---")
                        return packages_section
                    else:
                        print("[DEBUG] No 'packages:' section found in the file.")
                        return None
            except Exception as e:
                warning(f"Error processing file: {e}")
                return None

        def get_clean_packages_list(packages_section):
            """Parses the packages section into a list for the command line."""
            if not packages_section:
                return []
            clean_packages_list = []
            for line in packages_section.splitlines():
                stripped_line = line.strip()
                if not stripped_line or stripped_line.startswith('#'):
                    continue
                match = re.search(r'-\s*(.*)', stripped_line)
                if not match:
                    continue
                package_name = match.group(1).strip()
                if ('!' in package_name or '"' in package_name):
                    continue
                clean_packages_list.append(package_name)
            packages = []
            for pkg in clean_packages_list:
                packages.extend(['+p', pkg])
            print(f"[DEBUG] Final formatted packages list: {packages}")
            return packages

        # --- Build and Execute ---
        selected_path = get_hal_file_path()
        packages_section = get_packages_section(selected_path)
        packages = get_clean_packages_list(packages_section)

        HAL_AREA = os.environ.get("HAL_AREA")
        # HAL_TASK = os.environ.get("HAL_TASK")
        HAL_TASK = "shd"

        afx_cmd = [
            "afx", "--area", HAL_AREA, "--task", HAL_TASK, "run", "maya"
        ]
        
        if packages:
            run_index = afx_cmd.index("run")
            afx_cmd[run_index:run_index] = packages

        print("="*50)
        print(f"[DEBUG] FINAL COMMAND to be executed:\n{afx_cmd}")
        print("="*50)
        
        try:
            print("[INFO] Attempting to launch new Maya instance...")
            if os.name == 'nt':
                subprocess.Popen(["start"] + afx_cmd, shell=True)
            else:
                subprocess.Popen(afx_cmd)
            
            print("[INFO] Subprocess command has been sent successfully.")
            
        except Exception as e:
            warning(f"Failed to launch Maya: {e}")
            sys.exit(1)
        
    except Exception as e:
        warning(f"A critical error occurred in the script: {str(e)}")

# --- Standard Maya execution functions ---
def get_command():
    def _command():
        open_maya_smarter()
    return _command

def execute():
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()

if __name__ == "__main__":
    execute()