"""Give headless Qt tests enough screen space for the desktop workspace."""
import os
from pathlib import Path


# Qt's default offscreen screen is 800x800, smaller than the app's minimum
# width. On Windows this can clip a button's visible region at the screen edge.
# Qt separates platform options at colons, so a Windows drive letter cannot
# appear in the configfile option. The test process keeps its original cwd;
# startup/smoke subprocesses already select their own offscreen platform.
if os.environ.get("QT_QPA_PLATFORM", "offscreen") == "offscreen":
    config = Path(__file__).parent / "data" / "qt-offscreen.json"
    relative = Path(os.path.relpath(config, Path.cwd())).as_posix()
    os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={relative}"
