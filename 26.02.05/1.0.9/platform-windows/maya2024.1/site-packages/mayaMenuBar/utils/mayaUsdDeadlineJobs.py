import sys
import os
import json
import shutil
import glob
import math
import maya.cmds as cmds

# ==============================================================================
# 1. EMBEDDED SHOTGUN MANAGER (Corrected)
# ==============================================================================
class EmbeddedShotgunManager:
    def __init__(self):
        try:
            import shotgun_api3
        except ImportError:
            print("[WARN] shotgun_api3 module not found. Shotgun submission will be skipped.")
            self.sg = None
            return

        base_url = "https://aivfx.shotgrid.autodesk.com"
        script_name = "hal_roxy_templates_rw"
        api_key = "cstmibkrtcwqmaz4sjwtexG~s" 

        try:
            self.sg = shotgun_api3.Shotgun(base_url, script_name, api_key)
            print(">>> Connected to Shotgun.")
        except Exception as e:
            print(f"[ERROR] Shotgun connection failed: {e}")
            self.sg = None
            return

        self.project_id = int(os.environ.get('HAL_PROJECT_SGID', 0))
        self.task_id = int(os.environ.get('HAL_TASK_SGID', 0))
        
        self.link_type = "Asset"
        self.link_id = int(os.environ.get('HAL_ASSET_SGID', 0))
        if self.link_id == 0:
            self.link_id = int(os.environ.get('HAL_SHOT_SGID', 0))
            self.link_type = "Shot"

    def Create_SG_Version(self, thumbnail_path, submit_path, specific_code=None):
        if not self.sg: return
        if self.project_id == 0 or self.link_id == 0:
            print("[ERROR] Missing SG Environment Variables.")
            return

        # 1. Determine Version Name (Code)
        if specific_code:
            code = specific_code
        else:
            # Fallback to filename (Avoid this if file is named 'package.usdc')
            code = os.path.splitext(os.path.basename(submit_path))[0]
        
        description = "USD Assembly Publish (Auto-Submit from Deadline)"

        data = {
            'project': {'type': 'Project', 'id': self.project_id},
            'code': code,
            'description': description,
            'sg_path_to_geometry': submit_path, # This ensures we point to the USD
            'entity': {'type': self.link_type, 'id': self.link_id},
            'sg_status_list': 'rev'
        }

        if self.task_id:
            data['sg_task'] = {'type': 'Task', 'id': self.task_id}

        print(f">>> Creating Version '{code}' linked to {self.link_type} ID {self.link_id}...")
        
        try:
            version = self.sg.create('Version', data)
            print(f">>> Version created: ID {version['id']}")
            
            if thumbnail_path and os.path.exists(thumbnail_path):
                print(f">>> Uploading thumbnail: {thumbnail_path}")
                self.sg.upload_thumbnail('Version', version['id'], thumbnail_path)
            
            print(">>> Shotgun Submission Successful.")
            return version
            
        except Exception as e:
            print(f"[ERROR] Failed to create SG Version: {e}")
            return None

# ==============================================================================
# 2. EMBEDDED THUMBNAIL GENERATOR (Fixed Path & Existence Check)
# ==============================================================================
def create_farm_thumbnail(top_node_name, spin_offset=45, pitch_offset=-20):
    """
    Generates a thumbnail. If it already exists at the specific path, skips generation.
    Path: {HAL_TASK_ROOT}/_publish/_SGthumbnail/{top_node_name}_temp.1001.png
    """
    hal_root = os.environ.get("HAL_TASK_ROOT", "")
    if not hal_root:
        # Fallback if env missing (unlikely on farm if submitted right)
        print("[WARN] HAL_TASK_ROOT not set. Using current dir.")
        hal_root = os.getcwd()

    thumb_dir = os.path.join(hal_root, "_publish", "_SGthumbnail")
    if not os.path.exists(thumb_dir): os.makedirs(thumb_dir)
    
    # EXACT Path requested
    final_path = os.path.join(thumb_dir, f"{top_node_name}_temp.1001.png").replace("\\", "/")

    # 1. CHECK EXISTENCE
    if os.path.exists(final_path):
        print(f">>> Thumbnail already exists: {final_path}")
        return final_path

    print(f">>> Generating Thumbnail: {final_path}")

    created_nodes = []
    try:
        # A. FIND OBJECTS
        top_level_objects = [
            obj for obj in cmds.ls(assemblies=True, type='transform')
            if cmds.listRelatives(obj, allDescendents=True, type='mesh')
        ]
        valid_objs = []
        for o in top_level_objects:
             shapes = cmds.listRelatives(o, s=True) or []
             if not any(cmds.nodeType(s) in ['camera', 'light', 'aiSkyDomeLight'] for s in shapes):
                 valid_objs.append(o)
                 
        if not valid_objs:
            print("[WARN] No geometry found to frame.")
            return None

        # B. CALCULATE CENTER
        bbox = cmds.exactWorldBoundingBox(valid_objs)
        center_x = (bbox[0] + bbox[3]) / 2.0
        center_y = (bbox[1] + bbox[4]) / 2.0
        center_z = (bbox[2] + bbox[5]) / 2.0
        object_center = (center_x, center_y, center_z)

        # C. CREATE CAMERA RIG
        camera_transform, camera_shape = cmds.camera(name="render_cam")
        cmds.setAttr(f"{camera_shape}.focalLength", 35)
        created_nodes.append(camera_transform)
        
        temp_rig = cmds.group(empty=True, name=f"{camera_transform}_rig_temp")
        created_nodes.append(temp_rig)
        cmds.xform(temp_rig, worldSpace=True, translation=object_center)
        cmds.parent(camera_transform, temp_rig)
        
        final_rig_rotate_x = 5 + pitch_offset
        final_rig_rotate_y = -35 + spin_offset
        cmds.xform(temp_rig, rotation=(final_rig_rotate_x, final_rig_rotate_y, 0), worldSpace=False)
        
        cmds.parent(camera_transform, world=True)
        cmds.delete(temp_rig)
        
        # D. FIT & PULL
        cmds.viewFit(camera_transform, valid_objs, fitFactor=1.1, animate=False)
        
        cam_pos = cmds.xform(camera_transform, query=True, translation=True, worldSpace=True)
        current_dist = math.sqrt(
            (cam_pos[0] - object_center[0])**2 +
            (cam_pos[1] - object_center[1])**2 +
            (cam_pos[2] - object_center[2])**2
        )
        cmds.move(0, 0, 0.5 * current_dist, camera_transform, relative=True, objectSpace=True)
        
        # E. BATCH VIEWPORT SETUP
        window_name = "pv_window_farm"
        if cmds.window(window_name, exists=True): cmds.deleteUI(window_name)
            
        cmds.window(window_name, widthHeight=(1920, 1080))
        cmds.paneLayout()
        panel = cmds.modelPanel(label="PlayblastPanel")
        cmds.showWindow(window_name)
        
        cmds.modelPanel(panel, edit=True, camera=camera_transform)
        cmds.setFocus(panel)
        cmds.modelEditor(panel, edit=True, grid=False, headsUpDisplay=False, 
                         displayAppearance='smoothShaded', displayTextures=True, allObjects=False, polymeshes=True)

        # F. PLAYBLAST
        # Prefix without extension/frame
        pb_prefix = os.path.join(thumb_dir, f"{top_node_name}_temp").replace("\\", "/")
        
        generated_files = cmds.playblast(
            f=pb_prefix, startTime=1001, endTime=1001, 
            fmt='image', compression='png', quality=100, percent=100, 
            widthHeight=(1920, 1080), viewer=False, framePadding=4, 
            forceOverwrite=True, showOrnaments=False, offScreen=True
        )
        
        if cmds.window(window_name, exists=True): cmds.deleteUI(window_name)

        if os.path.exists(final_path):
            print(f">>> Thumbnail Created: {final_path}")
            return final_path
        else:
            print(f"[ERROR] Playblast ran but file missing: {final_path}")
            return None

    except Exception as e:
        print(f"[ERROR] Thumb gen failed: {e}")
        import traceback; traceback.print_exc()
        return None
    finally:
        for n in created_nodes:
            if cmds.objExists(n): cmds.delete(n)

def farm_publish_ma_scene(current_src, version_dir):
    try:
        # project = os.environ.get("HAL_PROJECT_ABBR", "PROJ")
        asset   = os.environ.get("HAL_ASSET", "ASSET")
        task    = os.environ.get("HAL_TASK", "shd")
        user    = os.environ.get("HAL_USER_ABBR", "user")
        version = os.path.basename(version_dir)
        name = f"{asset}_{task}_{version}_{user}.ma"
        dst = os.path.join(version_dir, name).replace("\\", "/")
        shutil.copy2(current_src, dst)
        print(f">>> Published Maya File: {dst}")
        return dst, name # Return name for Version Code calculation
    except Exception as e:
        print(f"[ERROR] Failed to publish MA file: {e}")
        return None, None

# ==============================================================================
# 3. ROBUST USD UTILS (To Override potential broken ones)
# ==============================================================================
def robust_clean_shader_file(dirty_path, clean_path):
    from pxr import Usd, Sdf, UsdShade
    if not os.path.exists(dirty_path): return False     
    src_layer = Sdf.Layer.FindOrOpen(dirty_path)
    if not src_layer: return False
    
    if os.path.exists(clean_path):
        try: os.remove(clean_path)
        except: pass

    dst_layer = Sdf.Layer.Find(clean_path)
    if dst_layer: dst_layer.Clear()
    else:
        try: dst_layer = Sdf.Layer.CreateNew(clean_path, args={'format':'usdc'})
        except:
            dst_layer = Sdf.Layer.FindOrOpen(clean_path)
            if dst_layer: dst_layer.Clear()

    if not dst_layer: return False

    mtl_path = Sdf.Path("/mtl")
    mtl_prim_spec = Sdf.CreatePrimInLayer(dst_layer, mtl_path)
    mtl_prim_spec.specifier = Sdf.SpecifierDef
    mtl_prim_spec.typeName = "Scope"
    
    stage_tmp = Usd.Stage.Open(src_layer)
    materials_copied = 0
    for prim in stage_tmp.Traverse():
        if prim.IsA(UsdShade.Material):
            mat_name = prim.GetName()
            src_path = prim.GetPath()            
            dst_path = mtl_path.AppendChild(mat_name)            
            Sdf.CopySpec(src_layer, src_path, dst_layer, dst_path)
            materials_copied += 1
            
    dst_layer.Save()
    print(f"[CLEAN] Extracted {materials_copied} materials to {os.path.basename(clean_path)}")
    return True

# ==============================================================================
# 4. INITIALIZATION & MAIN
# ==============================================================================
def initialize_maya():
    import maya.standalone
    print(">>> Initializing Maya Standalone...")
    try: maya.standalone.initialize(name='python')
    except RuntimeError: pass
    except Exception as e: print(f">>> Warning: {e}")

    required = ["mtoa", "mayaUsdPlugin"]
    for p in required:
        if not cmds.pluginInfo(p, q=True, loaded=True):
            try: cmds.loadPlugin(p)
            except: print(f"[WARN] Failed to load {p}")

def safe_print(msg):
    try: print(msg)
    except UnicodeEncodeError: 
        print(msg.encode('ascii', 'replace').decode('ascii'))
    except: pass

def main():
    try:
        if len(sys.argv) >= 4:
            json_path = sys.argv[1]; task_type = sys.argv[2]; extra_arg = sys.argv[3]
        elif len(sys.argv) == 3:
            json_path = sys.argv[1]; task_type = sys.argv[2]; extra_arg = None
        else:
            json_path = sys.argv[-2]; task_type = sys.argv[-1]; extra_arg = None
            
        safe_print(f">>> Task: {task_type} | Extra: {extra_arg}")
    except: return

    if not os.path.exists(json_path): return

    with open(json_path, 'r') as f: data = json.load(f)

    paths = data['paths']
    scene_file = data['scene_file']
    top_name = paths['top_name']
    
    initialize_maya()
    
    safe_print(f">>> Opening Scene: {scene_file}")
    cmds.file(scene_file, open=True, force=True)
    
    top_node = top_name
    if not cmds.objExists(top_node):
        safe_print(f"[ERROR] Top node '{top_node}' not found.")
        return
    
    # --- MONKEY PATCH GLOBALS ---
    globals()['clean_shader_file'] = robust_clean_shader_file

    # Retrieve globals
    fix_arnold_usd_structure = globals().get('fix_arnold_usd_structure')
    _rename_nonmesh_parents_in_layer_with_sdf = globals().get('_rename_nonmesh_parents_in_layer_with_sdf')
    _inject_binding_metadata = globals().get('_inject_binding_metadata')
    arnold_usd_mask = globals().get('arnold_usd_mask')

    # ... [TASK 1-3: export_base, proxy, lod REMAIN UNCHANGED] ...
    # (Abbreviated for clarity - KEEP PREVIOUS LOGIC)
    if task_type == 'export_base':
        print(f"=== Task: Export Base Render (LOD0) ===")
        cmds.select(top_node, r=True)
        try:
            mask = arnold_usd_mask(shaderOrNot=False) 
            cmds.arnoldExportAss(
                f=paths['render_path'], selected=True, mask=mask, 
                lightLinks=False, shadowLinks=False, expandProcedurals=True
            )
            if os.path.exists(paths['render_path']):
                if fix_arnold_usd_structure: fix_arnold_usd_structure(paths['render_path'])
                if _inject_binding_metadata:
                    from pxr import Usd, Sdf
                    lyr = Sdf.Layer.FindOrOpen(paths['render_path'])
                    if lyr:
                        stg = Usd.Stage.Open(lyr)
                        _inject_binding_metadata(stg, top_node)
                        stg.GetRootLayer().Save()
            print(">>> Base Export Complete.")
        except Exception as e:
            safe_print(f"[ERROR] Base Export Failed: {e}")

    elif task_type == 'proxy':
        print("=== Task: Export Proxy ===")
        if data.get('has_proxy'):
            pct = data.get('proxy_percent', 50.0)
            top_name_base = paths['top_name']
            src_tmp = _safe_rename(top_node, f"{top_name_base}_origTmp")
            try:
                proxy_dup = _duplicate_and_reduce(src_tmp, suffix='_proxy', percent=pct)
                proxy_as_src = _safe_rename(proxy_dup, top_name_base)
                mask = arnold_usd_mask(shaderOrNot=False)
                cmds.select(proxy_as_src, r=True)
                cmds.arnoldExportAss(
                    f=paths['proxy_path'], selected=True, mask=mask, 
                    lightLinks=False, shadowLinks=False, expandProcedurals=True
                )
                if os.path.exists(paths['proxy_path']):
                    if fix_arnold_usd_structure: fix_arnold_usd_structure(paths['proxy_path'])
                    if _rename_nonmesh_parents_in_layer_with_sdf:
                        _rename_nonmesh_parents_in_layer_with_sdf(paths['proxy_path'], suffix='_proxy')
                print(">>> Proxy Export Complete.")
            except Exception as e: safe_print(f"[ERROR] Proxy: {e}")
            finally:
                if 'proxy_as_src' in locals() and cmds.objExists(proxy_as_src): cmds.delete(proxy_as_src)
                if cmds.objExists(src_tmp): _safe_rename(src_tmp, top_name_base)

    elif task_type == 'lod':
        if extra_arg:
            lod_idx = int(extra_arg)
            print(f"=== Task: Export Geo Variant LOD {lod_idx} ===")
            base_pct = data.get('lod_percent', 50.0)
            keep_ratio = (base_pct / 100.0) ** lod_idx
            remove_percent = max(0.0, min(99.0, 100.0 - (keep_ratio * 100.0)))
            cmds.select(top_node, r=True)
            exporter = LODVariantExporter()
            exporter.task_export_single_lod(top_node, paths, "geoVariant", lod_index=lod_idx, percent=remove_percent, shaderOrNot=False)

    # ==========================================================================
    # TASK 4: ASSEMBLE (AND SHOTGUN)
    # ==========================================================================
    elif task_type == 'assemble':
        print("=== Task: Assembly & Publish ===")
        
        # 1. Geo Assembly
        geoUsdExport(f"/{top_name}", paths['version_dir'])
        addGeoVariantsIntoGeoUsd(f"/{top_name}", paths['version_dir'], paths, data.get('lod_count', 0))
        
        # 2. Shader Assembly
        if data.get('do_tex'):
             print("--- Generating Shader Variants ---")
             if not os.path.exists(paths['shdVariant_dir']): os.makedirs(paths['shdVariant_dir'])
             cmds.select(top_node, r=True)
             exporter = LODVariantExporter()
             
             target_indices = [0, 2, 4, 10]
             for idx in target_indices:
                 exporter.task_export_single_lod(top_node, paths, "shdVariant", lod_index=idx, shaderOrNot=True)
             
             addShdVariantsIntoShdUsd(f"/{top_name}", paths['version_dir'], paths)
        
        # 3. Payload & Shell
        create_payload_file(top_name, paths['version_dir'])
        bind_materials_in_payload(paths['payload_path'], top_name)
        final_usd = _write_interface_top_layer(top_name, paths['payload_path'], paths['top_path'])
        
        # 4. Shotgun Submission
        print("--- Finalizing & Submitting to Shotgun ---")
        
        # A. Generate/Find Thumbnail
        thumb_path = create_farm_thumbnail(top_name)
        
        # B. Publish Maya File
        ma_path, ma_name = farm_publish_ma_scene(scene_file, paths['version_dir'])
        
        # C. Submit to Shotgun (Single correct version)
        sg_manager = EmbeddedShotgunManager()
        if sg_manager.sg and thumb_path:
            if ma_name:
                version_code = os.path.splitext(ma_name)[0]
            else:
                # version_code = f"{top_name}_{os.path.basename(paths['version_dir'])}"
                asset   = os.environ.get("HAL_ASSET", "ASSET")
                task    = os.environ.get("HAL_TASK", "shd")
                user    = os.environ.get("HAL_USER_ABBR", "user")
                version = os.path.basename(version_dir)
                version_code = f"{asset}_{task}_{version}_{user}"

            sg_manager.Create_SG_Version(thumb_path, final_usd, specific_code=version_code)
            
        print(">>> Assembly Complete.")

if __name__ == "__main__":
    main()