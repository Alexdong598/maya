import os
import subprocess
import tempfile
import maya.cmds as cmds

current_file_path = cmds.file(q=True, loc=True)


class DeadlineSubmitter:
    def __init__(self, deadline_bin=None):
        self.deadline_bin = deadline_bin or r"C:\Program Files\Thinkbox\Deadline8\bin\deadlinecommand.exe"
        if not os.path.exists(self.deadline_bin):
            raise FileNotFoundError(f"Deadline command not found: {self.deadline_bin}")

    def submit(self, job_info: dict, plugin_info: dict):
        job_file = self._write_temp_file(job_info, ".job")
        plugin_file = self._write_temp_file(plugin_info, ".plugin")

        cmd = [self.deadline_bin, job_file, plugin_file]
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)

        # Cleanup
        try:
            os.unlink(job_file)
            os.unlink(plugin_file)
        except OSError:
            pass

        if result.returncode != 0:
            raise RuntimeError(f"Deadline submission failed: {result.stderr}")

        job_id = None
        for line in result.stdout.splitlines():
            if line.startswith("JobID="):
                job_id = line.split("=")[1].strip()
                break
        
        if not job_id:
            raise RuntimeError(f"Could not find JobID in response:\n{result.stdout}")
            
        return job_id

    @staticmethod
    def _write_temp_file(info_dict, suffix):
        # Ensure everything is a string
        text = "\n".join(f"{k}={v}" for k, v in info_dict.items())
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, mode='w', encoding='utf-8')
        tmp.write(text)
        tmp.close()
        return tmp.name

# ======================================================================
# Submit Two Sequential Jobs (Item 2 depends on Item 1)
# ======================================================================

def submit_two_item_job(scene_file, maya_version="2024"):
    d = DeadlineSubmitter()
    base = os.path.splitext(os.path.basename(scene_file))[0]
    batch_name = base

    ITEMS = [
        {
            "name": "test_item_one",
            "frames": "0-19",
            "item_check": "test_item_one",
            "output": r"C:/item_one/test_####.exr"
        },
        {
            "name": "test_item_two",
            "frames": "0-99",
            "item_check": "test_item_two",
            "output": r"C:/item_two/test_####.exr"
        }
    ]

    submitted_job_ids = []

    for idx, item in enumerate(ITEMS):

        job_info = {
            "BatchName": batch_name,
            "Name": f"{base} ({item['name']})",
            "Plugin": "MayaBatch",

            # Pools / groups
            "Pool": "3d",
            "SecondaryPool": "all",
            "Group": "3d",
            "Priority": 50,
            "Frames": item["frames"],
            "ChunkSize": 1,

            # Custom data
            "UserName": os.environ.get("HAL_USER_LOGIN"),
            "ItemCheck": item["item_check"],

            # Scripts
            "PreJobScript": r"C:/pre_job_script.py",
            "PostJobScript": r"C:/post_job_script.py",
            "PreTaskScript": r"C:/pre_task_script.py",
            "PostTaskScript": r"C:/post_task_script.py",
        }

        # ---------------------------------------------------------
        # ADD DEPENDENCY: item 2 depends on item 1
        # ---------------------------------------------------------
        if idx > 0:
                    # Get the ID of the previous job
                    previous_job_id = submitted_job_ids[-1]
                    
                    # Use the standard key 'JobDependencies'
                    job_info["JobDependencies"] = previous_job_id
                    
                    # If you want to resume on failed tasks, use this too:
                    # job_info["ResumeOnCompleteDependencies"] = True

        plugin_info = {
            "SceneFile": scene_file,
            "Version": maya_version,
            "Camera": "persp",
            "UsingRenderLayers": 0,
            "Renderer": "arnold",
            "OutputFile0": item["output"]
        }

        print(f"Submitting: {item['name']}")
        job_id = d.submit(job_info, plugin_info)
        print(f" → Submitted job ID: {job_id}")

        submitted_job_ids.append(job_id)

    print("\nDependency Chain:")
    for i, jobid in enumerate(submitted_job_ids):
        print(f" {ITEMS[i]['name']} → {jobid}")



# ======================================================================
# Run
# ======================================================================
if __name__ == "__main__":
    submit_two_item_job(
        scene_file=current_file_path,
        maya_version="2024"
    )
