import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# File event threads are enabled only by the tests that exercise them.
os.environ["WORKSPACE_WATCH"] = "false"
