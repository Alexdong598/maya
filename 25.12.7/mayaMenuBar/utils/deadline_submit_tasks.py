import os
import subprocess
import tempfile
import logging
import sys

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DeadlineSubmitter:
    def __init__(self, deadline_bin=None):
        """
        Initialize the submitter with a specific Deadline 8 path.
        """
        self.deadline_bin = deadline_bin
        
        # If no binary was manually passed, look strictly for Deadline 8
        if not self.deadline_bin:
            # 1. check for the specific Deadline 8 Windows Path
            deadline_8_path = r"C:\Program Files\Thinkbox\Deadline8\bin\deadlinecommand.exe"
            
            # 2. Check environment variable just in case
            env_path = os.environ.get("DEADLINE_PATH", "")
            
            if os.path.exists(deadline_8_path):
                self.deadline_bin = deadline_8_path
            elif env_path and "Deadline8" in env_path and os.path.exists(os.path.join(env_path, "deadlinecommand.exe")):
                self.deadline_bin = os.path.join(env_path, "deadlinecommand.exe")
        
        # Validation
        if not self.deadline_bin or not os.path.exists(self.deadline_bin):
            raise FileNotFoundError(
                "Deadline 8 executable not found.\n"
                f"Checked path: C:\\Program Files\\Thinkbox\\Deadline8\\bin\\deadlinecommand.exe\n"
                "Please ensure the Deadline 8 Client is installed."
            )
        
        logger.info(f"Initialized Deadline Submitter using: {self.deadline_bin}")

    def submit(self, job_info: dict, plugin_info: dict):
        """
        Submits a job to Deadline using job_info and plugin_info dictionaries.
        """
        
        # ---------------------------------------------------------
        # --- ENVIRONMENT VARIABLE INJECTION ----------------------
        # ---------------------------------------------------------
        
        env_index = 0
        while f"EnvironmentKeyValue{env_index}" in job_info:
            env_index += 1

        count_added = 0

        REZ_MAYA_MTOA_ROOT = os.environ.get("REZ_MAYA_MTOA_ROOT")
        arnoldScriptPath = f"{REZ_MAYA_MTOA_ROOT}\scripts"

        ALLOWED_MAYA_EXACT = {
            "MAYA_PREFERRED_RENDERER",  
            "MAYA_ENABLE_LEGACY_RENDER_LAYERS",     
            "MAYA_VP2_DEVICE_OVERRIDE",
            "ARNOLD_PLUGIN_PATH",
            "MAYA_PLUG_IN_PATH",
            "PATH",
            "PYTHONPATH",
        }
        for key, value in os.environ.items():

            key_upper = key.upper()
            if key_upper.startswith("HAL") or key_upper in ALLOWED_MAYA_EXACT:
                ########Add arnold paths into PYTHONPATH###################
                if key_upper == "PYTHONPATH":
                    value = f"{arnoldScriptPath};{value}"

                job_info[f"EnvironmentKeyValue{env_index}"] = f"{key}={value}"
                env_index += 1
                count_added += 1
        
        # job_info[f"EnvironmentKeyValue{env_index}"] = f"PYTHONPATH={os.environ.get("ARNOLD_PLUGIN_PATH")}"

        logger.info(f"--- Environment Injection: Added {count_added} safe variables (Excluded C: drive & System keys) ---")
        
        # ---------------------------------------------------------
        # --- END INJECTION ---------------------------------------
        # ---------------------------------------------------------

        # Create temporary files for submission
        job_file = self._write_temp_file(job_info, ".job")
        plugin_file = self._write_temp_file(plugin_info, ".plugin")

        cmd = [self.deadline_bin, job_file, plugin_file]
        
        logger.info(f"Executing Deadline 8 Command: {' '.join(cmd)}")
        
        # Run the command
        try:
            # creating CREATE_NO_WINDOW flag for Windows to avoid popping up cmd window
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
        except Exception as e:
            self._cleanup(job_file, plugin_file)
            raise RuntimeError(f"Failed to execute deadlinecommand: {e}")

        # Cleanup temp files
        self._cleanup(job_file, plugin_file)

        if result.returncode != 0:
            raise RuntimeError(f"Deadline submission failed:\n{result.stderr}\n{result.stdout}")

        # Parse Job ID
        job_id = None
        for line in result.stdout.splitlines():
            if line.startswith("JobID="):
                job_id = line.split("=")[1].strip()
                break
        
        if not job_id:
            # Sometimes successful output doesn't start with JobID= immediately
            logger.warning(f"Could not explicitly parse JobID from output. Output was:\n{result.stdout}")
            return "Submission Successful (ID parsing failed)"
            
        return job_id

    def _cleanup(self, *files):
        for f in files:
            try:
                os.unlink(f)
            except OSError:
                pass

    @staticmethod
    def _write_temp_file(info_dict, suffix):
        """Writes a dictionary to a temporary file in 'Key=Value' format."""
        lines = []
        for k, v in info_dict.items():
            # Handle boolean values for Deadline (True -> True, False -> False/empty)
            if isinstance(v, bool):
                v = str(v)
            # Filter out None values
            if v is not None:
                lines.append(f"{k}={v}")
        
        text = "\n".join(lines)
        
        # Create temp file, explicitly closing it so subprocess can read it
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='w', encoding='utf-8')
        tmp.write(text)
        tmp.close()
        return tmp.name

def deadline_submit(job_data, plugin_data):
    """
    Helper function to easily submit from external scripts.
    """
    submitter = DeadlineSubmitter()
    return submitter.submit(job_data, plugin_data)