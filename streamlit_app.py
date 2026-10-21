import sys
from pathlib import Path

# Add directory and parent to sys.path
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
if str(CURRENT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR.parent))

# Launch main dashboard app
try:
    import elite_cloud.dashboard.app
except ImportError:
    import dashboard.app

