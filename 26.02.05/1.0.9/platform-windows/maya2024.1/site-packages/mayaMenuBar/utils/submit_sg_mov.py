import os
import sys
import argparse
import time

# 尝试导入 shotgun_api3，如果不存在则提示
try:
    import shotgun_api3
except ImportError:
    print("Error: 'shotgun_api3' module not found. Please install it using 'pip install git+https://github.com/shotgunsoftware/python-api.git'")
    sys.exit(1)

class ShotgunSubmitter:
    def __init__(self, base_url, script_name, api_key):
        """
        初始化 Shotgun 连接
        """
        print(f"Connecting to Shotgun: {base_url} (Script: {script_name})")
        try:
            self.sg = shotgun_api3.Shotgun(base_url, script_name, api_key)
            print("Successfully connected to Shotgun.")
        except Exception as e:
            print(f"Failed to connect to Shotgun: {e}")
            sys.exit(1)

    def submit_version(self, project_id, version_code, file_path, link_entity_type, link_entity_id, task_id=None, description=""):
        """
        创建 Version 并上传 MOV
        """
        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            return False

        # [修复] 健壮性处理：强制将 ID 转换为整数
        try:
            project_id = int(project_id)
            link_entity_id = int(link_entity_id)
            if task_id:
                task_id = int(task_id)
        except ValueError as e:
            print(f"Error: ID fields must be numbers. {e}")
            return False

        file_name = os.path.basename(file_path)
        
        # 1. 准备创建 Version 的数据字典
        data = {
            'project': {'type': 'Project', 'id': project_id},
            'code': version_code,
            'description': description,
            # [关键] 这里 link_entity_type 必须是首字母大写的单数，如 "Shot"
            'entity': {'type': link_entity_type, 'id': link_entity_id}, 
            'sg_path_to_movie': file_path,
            'sg_status_list': 'rev',
        }

        # 如果提供了 Task ID，则关联 Task
        if task_id:
            data['sg_task'] = {'type': 'Task', 'id': task_id}

        # 2. 在 Shotgun 创建 Version 实体
        print(f"Creating Version '{version_code}' linked to {link_entity_type} ID {link_entity_id}...")
        try:
            version = self.sg.create('Version', data)
            print(f"Version created with ID: {version['id']}")
        except Exception as e:
            print(f"Error creating Version entity: {e}")
            return False

        # 3. 上传文件到 sg_uploaded_movie 字段
        print(f"Uploading movie file: {file_name} ...")
        try:
            # [关键修复] 参数顺序修正：upload(entity_type, entity_id, path, field_name)
            # 之前的错误顺序导致代码试图把 'sg_uploaded_movie' 字符串当成文件路径去读取
            self.sg.upload('Version', version['id'], file_path, 'sg_uploaded_movie')
            print("Upload successful!")
        except Exception as e:
            print(f"Error uploading movie: {e}")
            print(f"Warning: Version {version['id']} created but media upload failed.")
            return False

        return True

def main():
    # ================= 配置区域 =================
    base_url="https://aivfx.shotgrid.autodesk.com"
    script_name="hal_roxy_templates_rw"
    api_key="cstmibkrtcwqmaz4sjwtexG~s"

    # 获取 Project ID
    project_id = int(os.environ.get("HAL_PROJECT_SGID", 0))
    
    # [修复] 实体类型映射逻辑
    # 你的环境变量 HAL_TREE 通常是 "shots" 或 "assets" (小写复数)
    # 但 Shotgun API 需要 "Shot" 或 "Asset" (首字母大写单数)
    raw_tree = os.environ.get("HAL_TREE", "shots").lower()
    
    if "asset" in raw_tree:
        link_type = "Asset"
        link_id = int(os.environ.get("HAL_ASSET_SGID", 0))
    else:
        # 默认为 Shot
        link_type = "Shot"
        link_id = int(os.environ.get("HAL_SHOT_SGID", 0))

    print(f"Detected Environment: {raw_tree} -> Linking to {link_type} ID: {link_id}")

    task_id = int(os.environ.get("HAL_TASK_SGID", 0))

    # ================= 文件与命名 =================
    mov_path = r"X:\_temp\yu.dong\nukeTest\output\robust_test.mov" 
    
    # 自动获取版本名
    code = os.path.splitext(os.path.basename(mov_path))[0]
    description = "Rendered from Nuke (Auto Submit)"

    # ===========================================

    # 检查必要参数
    if project_id == 0 or link_id == 0:
        print(f"Error: Missing Environment Variables. ProjectID: {project_id}, LinkID: {link_id}")
        sys.exit(1)

    submitter = ShotgunSubmitter(base_url, script_name, api_key)

    success = submitter.submit_version(
        project_id=project_id,
        version_code=code,
        file_path=mov_path,
        link_entity_type=link_type,
        link_entity_id=link_id,
        task_id=task_id if task_id != 0 else None,
        description=description
    )

    if success:
        print("--- Shotgun Submission Complete ---")
        # sys.exit(0)
    else:
        print("--- Shotgun Submission Failed ---")
        # sys.exit(1)

if __name__ == "__main__":
    main()