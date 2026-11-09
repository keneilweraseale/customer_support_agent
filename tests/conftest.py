import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory


_test_data_directory = TemporaryDirectory(prefix="customer-support-test-data-")
shutil.copytree(
    Path(__file__).resolve().parent / "fixtures" / "demo_data",
    _test_data_directory.name,
    dirs_exist_ok=True,
)

os.environ["STORAGE_BACKEND"] = "json"
os.environ["JSON_DATA_DIRECTORY"] = _test_data_directory.name
os.environ["GROQ_TOOL_AGENT_ENABLED"] = "false"
