import os
import shutil
import tempfile
from pathlib import Path

def _prepare_isolated_json_data_dir() -> str:
    project_root = Path(__file__).resolve().parents[1]
    source_data_dir = project_root / "data"
    temp_data_dir = Path(tempfile.mkdtemp(prefix="customer-support-data-"))
    for path in source_data_dir.iterdir():
        target = temp_data_dir / path.name
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
    return str(temp_data_dir)


os.environ["STORAGE_BACKEND"] = "json"
os.environ["CUSTOMER_SUPPORT_DATA_DIR"] = _prepare_isolated_json_data_dir()
