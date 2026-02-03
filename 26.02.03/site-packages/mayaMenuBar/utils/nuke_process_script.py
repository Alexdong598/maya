import nuke
import sys
import os

def create_nuke_setup():
    print("--- Initializing Nuke Script ---")

    # ==========================================
    # 1. Robust Argument Parsing
    # ==========================================
    # Defaults to prevent crashing if testing manually
    defaults = {
        'source': '', 'start': 1001, 'end': 1001, 'out': '', 
        'ocio': 'EMPTY', 'lut': 'EMPTY'
    }
    
    try:
        # Get args from command line or fall back to defaults
        arg_source  = sys.argv[1].replace('\\', '/') if len(sys.argv) > 1 else defaults['source']
        arg_start   = int(sys.argv[2]) if len(sys.argv) > 2 else defaults['start']
        arg_end     = int(sys.argv[3]) if len(sys.argv) > 3 else defaults['end']
        arg_out     = sys.argv[4].replace('\\', '/') if len(sys.argv) > 4 else defaults['out']
        arg_ocio    = sys.argv[5] if len(sys.argv) > 5 else defaults['ocio']
        arg_lut     = sys.argv[6].replace('\\', '/') if len(sys.argv) > 6 else defaults['lut']
    except Exception as e:
        print(f"CRITICAL ERROR parsing arguments: {e}")
        return

    print(f"Processing: {arg_source} -> {arg_out}")

    # ==========================================
    # 2. Project Settings (OCIO)
    # ==========================================
    # We set this to ensure the correct config is loaded, 
    # so the OCIODisplay node has the right options available.
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

    # ==========================================
    # 3. Dynamic Node Chain
    # ==========================================
    current_node = None

    # --- A. Read Node ---
    try:
        read_node = nuke.createNode('Read')
        read_node['file'].setValue(arg_source)
        read_node['first'].setValue(arg_start)
        read_node['last'].setValue(arg_end)
        read_node['origfirst'].setValue(arg_start)
        read_node['origlast'].setValue(arg_end)
        
        # IMPORTANT: Input is Raw/Linear. We rely on the OCIO config to handle the IDT
        # or we treat it as raw data until the Display node.
        read_node['raw'].setValue(True) 
        
        current_node = read_node
    except Exception as e:
        print(f"FATAL: Could not create Read node: {e}")
        return

    # --- B. OCIODisplay (The Color Bake) ---
    # This matches your screenshot exactly.
    try:
        ocio_display = nuke.createNode('OCIODisplay')
        ocio_display.setInput(0, current_node)
        
        # 1. Input Colorspace (Matches UI "input": 'ACES - ACEScg')
        ocio_display['colorspace'].setValue('ACES - ACEScg')
        
        # 2. Display Device (Matches UI "display device": 'default')
        ocio_display['display'].setValue('default')

        # 3. View Transform (Matches UI "view transform": 'ACES - Rec.709')
        ocio_display['view'].setValue('ACES - Rec.709')

        current_node = ocio_display
        print("OCIODisplay Applied: ACEScg -> ACES - Rec.709")
        
    except Exception as e:
        print(f"FATAL: OCIODisplay node failed: {e}")
        # We continue, but color might be wrong if this fails.

    # --- C. Formatting & Overlay ---
    
    # 1. Reformat to HD
    reformat = nuke.createNode('Reformat')
    reformat['format'].setValue('HD_1080')
    reformat['resize'].setValue('fit')
    reformat.setInput(0, current_node)
    current_node = reformat

    # 2. Burn-in (Text)
    # Simple example overlay
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
        pass # If Text2 fails (rare), just skip overlay

    # --- D. Write Node ---
    try:
        write = nuke.createNode('Write')
        write.setName('Output_Write')
        write['file'].setValue(arg_out)
        write['file_type'].setValue('mov')
        
        # Codec settings
        write['mov64_codec'].setValue('appr') # ProRes
        write['mov64_pixel_format'].setValue('{0}') # YCbCr 4:2:2 10-bit usually
        write['create_directories'].setValue(True)
        
        # !!! VITAL SETTING !!!
        # Since OCIODisplay has already baked the Rec.709 look into the pixels,
        # we set the Write node to 'raw' so it doesn't change the colors again.
        write['colorspace'].setValue('raw')
        
        write.setInput(0, current_node)
    except Exception as e:
        print(f"FATAL: Could not create Write node: {e}")
        sys.exit(1)

    # ==========================================
    # 4. Execute Render
    # ==========================================
    print(f"Starting Render -> {arg_out}")
    try:
        nuke.execute(write, arg_start, arg_end, 1)
        print("Render Success.")
    except Exception as e:
        print(f"Render Failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    create_nuke_setup()