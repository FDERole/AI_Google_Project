import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "static"
RUNTIME_DIR = Path(os.environ.get("SANJAYA_RUNTIME_DIR", ROOT / "runtime"))
UPLOAD_DIR = RUNTIME_DIR / "uploads"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Demo speed: 1 = real time. 20 = one plant minute passes in 3 real seconds.
DEMO_SPEED = float(os.environ.get("SANJAYA_DEMO_SPEED", "1"))

# Minutes without a reply before a request escalates to the next approver level.
ESCALATE_AFTER_MIN = float(os.environ.get("SANJAYA_ESCALATE_AFTER_MIN", "3"))

# Minutes before the limit at which the requester gets a reminder.
REMIND_BEFORE_MIN = float(os.environ.get("SANJAYA_REMIND_BEFORE_MIN", "5"))
