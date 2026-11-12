"""PauseGuard's offline mock backend foundation."""

from pathlib import Path
import sys

# Ensure repository root is on sys.path for portable cross-package discovery (e.g. safety)
_REPO_ROOT = Path(__file__).resolve().parents[2]
if (_REPO_ROOT / "safety").is_dir() and str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

