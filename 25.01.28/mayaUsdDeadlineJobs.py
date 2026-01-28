import sys
import os
import json
import maya.cmds as cmds

# --- 1. ROBUST INITIALIZATION ---
def initialize_maya():
    import maya.standalone
    print(">>> Initializing Maya Standalone...")
    try:
        maya.standalone.initialize(name='python')
    except RuntimeError:
        print(">>> Maya Standalone already initialized (expected in MayaBatch).")
    except Exception as e:
        print(f">>> Warning during initialization: {e}")

    # Load Plugins
    if not cmds.pluginInfo("mtoa", q=True, loaded=True):
        try: 
            cmds.loadPlugin("mtoa")
            print(">>> Loaded mtoa")
        except: print(">>> Warning: mtoa not loaded")
        
    if not cmds.pluginInfo("mayaUsdPlugin", q=True, loaded=True):
        try: 
            cmds.loadPlugin("mayaUsdPlugin")
            print(">>> Loaded mayaUsdPlugin")
        except: print(">>> Warning: mayaUsdPlugin not loaded")

# --- 2. MAIN EXECUTION ---
def main():
    try:
        # Matches: run mayapy "worker.py" "json_path" "task_type"
        json_path = sys.argv[-2]
        task_type = sys.argv[-1] 
    except IndexError:
        print(f"CRITICAL: sys.argv arguments invalid: {sys.argv}")
        return

    print(f">>> Loading Config: {json_path}")
    with open(json_path, 'r') as f:
        data = json.load(f)

    paths = data['paths']
    scene_file = data['scene_file']
    top_name = paths['top_name']
    
    # Initialize before doing any Maya commands
    initialize_maya()
    
    print(f">>> Opening Scene: {scene_file}")
    cmds.file(scene_file, open=True, force=True)
    
    if not cmds.objExists(top_name):
        print(f"Error: Top node {top_name} not found.")
        return

    top_node = top_name 

    # --- TASK: EXPORT ---
    if task_type == 'export':
        print("--- Task: Export Base & Proxy ---")
        
        cmds.select(top_node, r=True)
        exporter = LODVariantExporter()
        
        # 1. Export LOD0 (Original)
        exporter.task_export_single_lod(top_node, paths, "shdVariant", lod_index=0, shaderOrNot=True)
        
        # 2. Proxy Logic
        if data.get('has_proxy'):
            print("--- Exporting Proxy ---")
            pct = data.get('proxy_percent', 50.0)
            proxy_dup = _duplicate_and_reduce(top_node, suffix='_proxy', percent=pct)
            
            top_name_base = paths['top_name']
            src_tmp = _safe_rename(top_node, f"{top_name_base}_origTmp")
            proxy_as_src = _safe_rename(proxy_dup, top_name_base)
            
            try:
                mask = arnold_usd_mask(shaderOrNot=False)
                cmds.select(proxy_as_src, r=True)
                cmds.arnoldExportAss(
                    f=paths['proxy_path'], selected=True, mask=mask, 
                    lightLinks=False, shadowLinks=False, expandProcedurals=True
                )
                
                # Cleanup Proxy USD structure
                if os.path.exists(paths['proxy_path']):
                    # Ensure functions exist before calling (Safety check)
                    if 'fix_arnold_usd_structure' in globals():
                        fix_arnold_usd_structure(paths['proxy_path'])
                    
                    if '_rename_nonmesh_parents_in_layer_with_sdf' in globals():
                        _rename_nonmesh_parents_in_layer_with_sdf(paths['proxy_path'], suffix='_proxy')
            
            except Exception as e:
                print(f"Proxy Export Failed: {e}")
                import traceback
                traceback.print_exc()
            finally:
                if cmds.objExists(proxy_as_src): cmds.delete(proxy_as_src)
                if cmds.objExists(src_tmp): _safe_rename(src_tmp, top_name_base)

        # 3. Export Geo Variants (LODs)
        if data.get('has_lods'):
            lod_count = data.get('lod_count', 3)
            base_pct = data.get('lod_percent', 50.0)
            
            for i in range(1, lod_count + 1):
                # Calculate Reduction
                keep_ratio = (base_pct / 100.0) ** i
                remove_percent = 100.0 - (keep_ratio * 100.0)
                remove_percent = max(0.0, min(99.0, remove_percent))
                
                # Export Geo Variant
                exporter.task_export_single_lod(top_node, paths, "geoVariant", lod_index=i, percent=remove_percent, shaderOrNot=False)
                
                # Export Shader Variant (Textures) if needed
                if i in [2, 4, 10]:
                     exporter.task_export_single_lod(top_node, paths, "shdVariant", lod_index=i, shaderOrNot=True)

    # --- TASK: ASSEMBLE ---
    elif task_type == 'assemble':
        print("--- Task: Assembly & Publish ---")
        geoUsdExport(f"/{top_name}", paths['version_dir'])
        addGeoVariantsIntoGeoUsd(f"/{top_name}", paths['version_dir'], paths, data.get('lod_count', 0))
        addShdVariantsIntoShdUsd(f"/{top_name}", paths['version_dir'], paths)
        
        create_payload_file(top_name, paths['version_dir'])
        bind_materials_in_payload(paths['payload_path'], top_name)
        
        _write_interface_top_layer(top_name, paths['payload_path'], paths['top_path'])

if __name__ == "__main__":
    main()