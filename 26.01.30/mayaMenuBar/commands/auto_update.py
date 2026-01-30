"""Auto Update - Open Heavy Mode to restore normal Maya functionality."""
import maya.cmds as cmds
import importlib
import sys

def open_heavy_mode():
    """Open heavy mode by restoring normal Maya functionality."""
    # 1) 恢复评估 + Undo + 自动关键帧 + 时间滑条
    try: cmds.evaluationManager(mode='parallel')
    except: pass
    try: cmds.undoInfo(stateWithoutFlush=True)
    except: pass
    try: cmds.autoKeyframe(state=False)  # 习惯默认：关自动关键帧（要开可改True）
    except: pass
    try: cmds.optionVar(iv=('timeSliderAutoRefresh', 1))
    except: pass

    # 2) Viewport回到常用：开选择高亮，基本着色，开双面光；阴影默认关
    panels = cmds.getPanel(type='modelPanel') or []
    for p in panels:
        try: cmds.modelEditor(p, e=True, displayTextures=True)
        except: pass
        try: cmds.modelEditor(p, e=True, shadows=False)
        except: pass
        try: cmds.modelEditor(p, e=True, displayLights='default')
        except: pass
        try: cmds.modelEditor(p, e=True, twoSidedLighting=True)
        except: pass
        try: cmds.modelEditor(p, e=True, wireframeOnShaded=False)
        except: pass
        try: cmds.modelEditor(p, e=True, sel=True)
        except: pass
        try: cmds.modelEditor(p, e=True, displayAppearance='smoothShaded')
        except: pass

    # 3) 关闭包围盒（恢复正常显示）
    try: cmds.displayPref(displayBoundingBox=False)
    except: pass

    # 4) 恢复刷新并强制刷新一次
    try: cmds.refresh(suspend=False)
    except: pass
    try: cmds.refresh()
    except: pass

    print(u'✅ Heavy Mode: OPEN（已恢复常用显示与评估）')

def get_command():
    """Return command implementation with auto-reload functionality."""
    def _command():
        open_heavy_mode()
    return _command

def execute():
    """Execute with reloading to enable script updates without restarting Maya."""
    importlib.reload(sys.modules[__name__])
    cmd = get_command()
    cmd()

if __name__ == "__main__":
    execute()
