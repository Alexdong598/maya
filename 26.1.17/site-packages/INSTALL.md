# Maya Menu Bar Installation Guide

## Prerequisites
- Maya 2024 installed
- Basic Python knowledge

## Installation Steps

1. Locate your Maya 2024 scripts directory:
   ```
   C:/Users/yu.dong/Documents/maya/2024/scripts/
   ```

2. Copy the following files and folders to the scripts directory:
   - `mayaMenuBar/` (the entire folder with its contents)
   - `userSetup.py`

3. The final directory structure should look like:
   ```
   maya/
   └── 2024/
       └── scripts/
           ├── mayaMenuBar/
           │   ├── __init__.py
           │   ├── commands.py
           │   └── ui.py
           └── userSetup.py
   ```

4. Start Maya 2024 - the "Custom Tools" menu should appear automatically in the main menu bar.

## Verification
1. Open Maya's Script Editor
2. Check the output for any errors during loading
3. If the menu doesn't appear, try running this in Python tab:
   ```python
   from mayaMenuBar import ui
   ui.create_menu()
   ```

## Troubleshooting
- If you get import errors, verify the mayaMenuBar folder is in the scripts directory
- Check for any syntax errors in the Python files
- Make sure there are no other userSetup.py files conflicting
