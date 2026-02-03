
import sys
import json
import os
import subprocess
import concurrent.futures
import shutil

# --- CONFIGURATION ---
def find_oiio_tool():
    # 1. Try finding it in the current Houdini Install ($HFS/bin)
    MTOA_PATH = os.getenv("MTOA_PATH")
    if MTOA_PATH:
        ext = ".exe" if os.name == "nt" else ""
        candidate = os.path.join(MTOA_PATH, "bin", "oiiotool" + ext)
        if os.path.isfile(candidate): return candidate.replace("\\", "/")

    # 2. Try generic names
    return shutil.which("oiiotool") or "oiiotool"

OIIO_TOOL = find_oiio_tool()
MAX_WORKERS = 20  # Threads per machine

LOD_SPECS = [
    {"suffix": "LOD2",  "scale": 2},
    {"suffix": "LOD4",  "scale": 4},
    {"suffix": "LOD10", "scale": 10}
]

def get_dst_path(src, lod):
    src = src.replace("\\", "/")
    parts = src.split("/")
    if "export" in parts:
        parts.insert(len(parts) - 1 - parts[::-1].index("export") + 1, lod)
    else:
        parts.insert(-1, lod)
    
    stem, ext = os.path.splitext(parts[-1])
    if not stem.endswith(f"_{lod}"):
        parts[-1] = f"{stem}_{lod}{ext}"
    return "/".join(parts)

def convert_texture(src):
    try:
        # Generate all 3 LODs for this single texture
        for spec in LOD_SPECS:
            dst = get_dst_path(src, spec['suffix'])
            pct = int(100.0 / spec['scale'])
            
            try: os.makedirs(os.path.dirname(dst), exist_ok=True)
            except OSError: pass
            
            cmd = [OIIO_TOOL, src, "--resize", f"{pct}%", "-o", dst]
            
            # Run silently
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            subprocess.run(cmd, check=True, startupinfo=startupinfo, stderr=subprocess.PIPE)
        return True, src
    except Exception as e:
        return False, f"{src}: {e}"

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: script.py <manifest> <start> <end>")
        sys.exit(1)

    manifest_path, start_idx, end_idx = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])

    print(f"Tool found at: {OIIO_TOOL}")

    with open(manifest_path, 'r') as f:
        all_files = json.load(f)

    # Slice the list for this specific task
    batch = all_files[start_idx : end_idx + 1]

    print(f"Processing {len(batch)} textures with {MAX_WORKERS} threads...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(convert_texture, path): path for path in batch}
        for future in concurrent.futures.as_completed(futures):
            success, msg = future.result()
            print(f"[{'OK' if success else 'FAIL'}] {msg}")
