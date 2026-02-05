import shotgun_api3
import os, re
import importlib
import sys

class ShotgunDataManager:
    def __init__(self):
        self.sg = shotgun_api3.Shotgun(base_url="https://aivfx.shotgrid.autodesk.com",
                          script_name="hal_roxy_templates_rw",
                          api_key="cstmibkrtcwqmaz4sjwtexG~s")
        
        # Handle environment variables safely
        self.HAL_PROJECT_SGID = os.environ.get('HAL_PROJECT_SGID')
        self.HAL_PROJECT = os.environ.get('HAL_PROJECT')
        self.HAL_PROJECT_ABBR = os.environ.get('HAL_PROJECT_ABBR')
        self.HAL_PROJECT_ROOT = os.environ.get('HAL_PROJECT_ROOT')


        self.HAL_AREA = os.environ.get('HAL_AREA')
        self.HAL_USER_ABBR = os.environ.get('HAL_USER_ABBR')
        self.HAL_USER_LOGIN = os.environ.get('HAL_USER_LOGIN')

        self.HAL_TREE = os.environ.get('HAL_TREE')
        if self.HAL_TREE == "shots":
            # From Sequence to Shot
            self.HAL_SEQUENCE = os.environ.get('HAL_SEQUENCE')
            self.HAL_SEQUENCE_SGID = os.environ.get('HAL_SEQUENCE_SGID')
            self.HAL_SEQUENCE_ROOT = os.environ.get('HAL_SEQUENCE_ROOT')

            self.HAL_SHOT = os.environ.get('HAL_SHOT')
            self.HAL_SHOT_SGID = os.environ.get('HAL_SHOT_SGID')
            self.HAL_SHOT_ROOT = os.environ.get('HAL_SHOT_ROOT')
            
        if self.HAL_TREE == "assets":
            # From Category to Asset(Category does not have ShotgunID configured)
            self.HAL_CATEGORY = os.environ.get('HAL_CATEGORY')
            self.HAL_CATEGORY_ROOT = os.environ.get('HAL_CATEGORY_ROOT')

            self.HAL_ASSET = os.environ.get('HAL_ASSET')
            self.HAL_ASSET_SGID = os.environ.get('HAL_ASSET_SGID')
            self.HAL_ASSET_ROOT = os.environ.get('HAL_ASSET_ROOT')

        # Get Task
        self.HAL_TASK = os.environ.get('HAL_TASK')
        self.HAL_TASK_TYPE = os.environ.get('HAL_TASK_TYPE')
        self.HAL_TASK_ROOT = os.environ.get('HAL_TASK_ROOT')
        self.HAL_TASK_SGID = os.environ.get('HAL_TASK_SGID')
        self.HAL_TASK_OUTPUT_ROOT = os.environ.get('HAL_TASK_OUTPUT_ROOT') # Y:/ Framestone Root
        self.HAL_TASK_ROOT = os.environ.get('HAL_TASK_ROOT') # X:/ Project Root

        self.data_store = {}
        
    def getSGData(self, entity_type, entity_id, fields=None):
        """Store and retrieve Shotgun entity data in a dictionary cache"""
        # Create unique cache key
        cache_key = f"{entity_type}_{entity_id}"
        
        # Fetch data if not cached
        if cache_key not in self.data_store:
            # Default fields if not specified
            if fields is None:
                fields = ["code", "sg_head_in", "sg_tail_out", "sg_cut_in", "sg_cut_out"]
            
            # Fetch data from Shotgun
            entity_data = self.sg.find(
                entity_type,
                [["id", "is", entity_id]],
                fields=fields
            )
            
            # Store in cache
            self.data_store[cache_key] = entity_data or {}
        
        return self.data_store[cache_key]

    def upload_file(self, entity_type, entity_id, path, field_name=None, display_name=None, tag_list=None):
        try:
            return self.sg.upload(
                entity_type,
                entity_id,
                path,
                field_name=field_name,
                display_name=display_name,
                tag_list=tag_list
            )
        except Exception as e:
            print(f"Failed to upload file: {e}")
            raise

    def find_files(self, context_key, entity_type='Asset'):
        # 拆解 context_key 形如 'shd/characters'
        task = 'shd'
        parts = context_key.strip().split('/')
        if parts and parts[0]:
            task = parts[0].strip()
        # 构建简单过滤条件列表
        filters = [
            ['project', 'is', {'type':'Project', 'id': int(self.HAL_PROJECT_SGID)}],
            ['code', 'contains', f'_{task}_']
        ]
        if entity_type:
            filters.append(['entity', 'type_is', entity_type])
        # 调用 find()，不再把过滤器打包成顶层字典
        fields = ['id','code','sg_path_to_geometry','image','created_at','user','entity']
        return self.sg.find('Version', filters, fields, filter_operator='all')

    def upload_thumbnail(self, entity_type, entity_id, path, **kwargs):
        try:
            return self.sg.upload_thumbnail(
                entity_type,
                entity_id,
                path,
                **kwargs
            )
        except Exception as e:
            print(f"Failed to upload thumbnail: {e}")
            raise

    def upload_filmstrip_thumbnail(self, entity_type, entity_id, path, **kwargs):
        try:
            return self.sg.upload_filmstrip_thumbnail(
                entity_type,
                entity_id,
                path,
                **kwargs
            )
        except Exception as e:
            print(f"Failed to upload filmstrip thumbnail: {e}")
            raise

    def SG_Find_Version(self, anim_tag=""):
        parent_entity_type = None
        parent_entity_id = None

        if self.HAL_TREE == "shots":
            parent_entity_type = 'Shot'
            parent_entity_id = int(self.HAL_SHOT_SGID)
            self.HAL_CONTENT = f"{self.HAL_SEQUENCE}_{self.HAL_SHOT}_{self.HAL_TASK}"
        elif self.HAL_TREE == "assets":
            parent_entity_type = 'Asset'
            parent_entity_id = int(self.HAL_ASSET_SGID)
            self.HAL_CONTENT = f"{self.HAL_ASSET}_{self.HAL_TASK}"
        else:
            raise ValueError("HAL_TREE must be 'shots' or 'assets'.")

        task_filters = [
            ['project', 'is', {'type': 'Project', 'id': int(self.HAL_PROJECT_SGID)}],
            ['entity', 'is', {'type': parent_entity_type, 'id': parent_entity_id}],
            ['content', 'is', self.HAL_CONTENT] 
        ]

        self.task = self.sg.find_one('Task', task_filters, fields=['id', 'content', 'entity'])
        
        if not self.task:
            raise ValueError(f"No Task found with content '{self.HAL_CONTENT}' for {parent_entity_type} ID {parent_entity_id} in Project ID {self.HAL_PROJECT_SGID}")

        print(f"Found Task: {self.task['content']} (ID: {self.task['id']}) linked to {self.task['entity']['type']} ID {self.task['entity']['id']}")
        
        version_filters = [
            ['project', 'is', {'type': 'Project', 'id': int(self.HAL_PROJECT_SGID)}],
            ['entity', 'is', {'type': parent_entity_type, 'id': parent_entity_id}], 
            ['sg_task', 'is', self.task] 
        ]
        
        all_versions = self.sg.find('Version', 
                                      version_filters, 
                                      fields=['code'],
                                      order=[{'field_name': 'created_at', 'direction': 'desc'}]
                                      )
        
        versions_to_parse = []
        # --- CORRECTED LOGIC: Filter based on the expected final name format ---
        if anim_tag:
            # For a tagged version, the pattern is "..._vXXX_aaa-tag"
            for v in all_versions:
                if v['code'].endswith(f"-{anim_tag}"):
                    versions_to_parse.append(v)
        else:
            # For a non-tagged version, it should not end with "-<word>" after the artist code.
            for v in all_versions:
                if not re.search(r'_v\d{3,}_[a-zA-Z]{3}-', v['code']):
                    versions_to_parse.append(v)

        print(f"Found {len(all_versions)} total versions. After filtering for tag '{anim_tag or 'None'}', now checking {len(versions_to_parse)} versions.")

        version_numbers = []
        if versions_to_parse:
            for version in versions_to_parse:
                version_str = version['code']
                version_match = re.search(r'_v(\d{3,})', version_str)
                if version_match:
                    version_numbers.append(int(version_match.group(1)))
                else:
                    print(f"Warning: Could not parse version number from: {version_str}")

        if version_numbers:
            next_version = max(version_numbers) + 1
        else:
            print(f"No previous versions found for this specific tag. Starting with v001.")
            next_version = 1
            
        # --- CORRECTED LOGIC: Build the name with the tag at the end ---
        base_name = f"{self.HAL_CONTENT}_v{next_version:03d}_{self.HAL_USER_ABBR}"
        highestVersionCode = base_name

        if anim_tag:
            # Append the tag to the very end of the base name.
            highestVersionCode = f"{base_name}-{anim_tag}"
        
        print(f"The new version name is: {highestVersionCode}")
        return highestVersionCode

    def Create_SG_Version(self, thumbnail_path, submit_path=None, first_frame=None, last_frame=None, anim_tag=""):
        """Create a Shotgun Version, then upload the thumbnail in a separate, stable step."""
        highestVersion = self.SG_Find_Version(anim_tag=anim_tag)
        
        data = {
            "project": {"type": "Project", "name": self.HAL_PROJECT, "id": int(self.HAL_PROJECT_SGID)},
            "code": f"{highestVersion}",
            "sg_status_list": "ip",
            "sg_task": self.task,
            "sg_path_to_geometry": submit_path,
            "sg_first_frame": first_frame,
            "sg_last_frame": last_frame
        }
        
        if self.HAL_TREE == "assets":
            data["entity"] = {"type": "Asset", "id": int(self.HAL_ASSET_SGID)}
        elif self.HAL_TREE == "shots":
            data["entity"] = {"type": "Shot", "id": int(self.HAL_SHOT_SGID)}
            
        print(f"Creating Version '{highestVersion}'...")
        created_version = self.sg.create('Version', data)
        print(f"Successfully created Version ID: {created_version['id']}")
        
        if thumbnail_path and os.path.exists(thumbnail_path):
            print(f"Uploading thumbnail '{thumbnail_path}' to Version ID {created_version['id']}...")
            try:
                self.upload_thumbnail(
                    entity_type="Version",
                    entity_id=created_version["id"],
                    path=thumbnail_path
                )
                print("Thumbnail upload complete.")
            except Exception as e:
                print(f"ERROR: Failed to upload thumbnail: {e}")
        
        return created_version

def get_command():
    """Return command implementation"""
    def _command():
        """Create new ShotgunDataManager instance"""
        global sg_manager
        try:
            if 'sg_manager' in globals():
                print("Updating existing ShotgunDataManager instance")
            sg_manager = ShotgunDataManager()
            sg_manager.__init__()
            print("ShotgunDataManager successfully created")
            return sg_manager
        except Exception as e:
            print(f"Error creating ShotgunDataManager: {str(e)}")
            raise

    sg_manager = ShotgunDataManager()
    return _command

def execute():
    """Execute command"""
    cmd = get_command()
    cmd()

if __name__ == "__main__":
    execute()

