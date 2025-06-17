import shotgun_api3
import os

class ShotgunDataManager:
    def __init__(self):
        self.sg = shotgun_api3.Shotgun(base_url="https://aivfx.shotgrid.autodesk.com",
                          script_name="hal_roxy_templates_rw",
                          api_key="cstmibkrtcwqmaz4sjwtexG~s")
        self.PROJECT_SGID = int(os.environ.get('HAL_PROJECT_SGID'))
        self.SHOTID = int(os.environ.get('HAL_SHOT_SGID'))
        self.data_store = {}
        
    def getSGData(self, entity_type, entity_id, fields=None):
        """Store and retrieve Shotgun entity data in a dictionary cache"""
        # Add Var
        
        # Create unique cache key
        cache_key = f"{entity_type}_{entity_id}"
        
        # Fetch data if not cached
        if cache_key not in self.data_store:
            # Default fields if not specified
            if fields is None:
                fields = ["code", "sg_cut_in", "sg_cut_out", "sg_head_in", "sg_head_out"]
            
            # Fetch data from Shotgun
            entity_data = self.sg.find_one(
                entity_type,
                [["id", "is", entity_id]],
                fields=fields
            )
            
            # Store in cache
            self.data_store[cache_key] = entity_data or {}
        
        return self.data_store[cache_key], self.PROJECT_SGID, self.SHOTID


# Initialize manager (do this once)
sg_manager = ShotgunDataManager()
PROJECT_SGID = sg_manager.PROJECT_SGID
SHOTID = sg_manager.SHOTID

# # ===== USAGE EXAMPLES =====

# # 1. Get ALL stored data for shot ID 8141
# shot_data = sg_manager.getSGData("Shot", SHOTID)[0]
# print("Full shot data:", shot_data)

# # 2. Get SPECIFIC values (cut in/out)
# cut_data = sg_manager.getSGData("Shot", SHOTID)[0]
# print(f"Cut Range: {cut_data.get('sg_cut_in')}-{cut_data.get('sg_cut_out')}")

# # 3. Get ONLY frame handles (efficient - fetches only needed fields)
# handles = sg_manager.getSGData("Shot", SHOTID, fields=["sg_head_in", "sg_head_out"])[0]
# print(f"Handles: {handles.get('sg_head_in')} - {handles.get('sg_head_out')}")

# 4. Get value with fallback
cut_in = sg_manager.getSGData("Shot", SHOTID)[0].get('sg_cut_in', 'Not set')
cut_out = sg_manager.getSGData("Shot", SHOTID)[0].get('sg_cut_out', 'Not set')
print(f"Cut In: {cut_in}")
print(f"Cut Out: {cut_out}")
