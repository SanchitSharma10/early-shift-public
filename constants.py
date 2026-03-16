import shutil
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

_src_db = PROJECT_ROOT / "early_shift_demo.db"
_tmp_db = Path(tempfile.gettempdir()) / "early_shift_demo.db"
if _src_db.exists() and not _tmp_db.exists():
    shutil.copy2(_src_db, _tmp_db)
DEFAULT_DB_PATH = str(_tmp_db) if _tmp_db.exists() else str(_src_db)
