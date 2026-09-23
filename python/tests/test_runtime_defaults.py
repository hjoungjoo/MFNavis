"""Production startup must not silently load the experimental data directory."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("explicit", [False, True])
def test_fresh_process_data_and_runtime_paths(tmp_path, explicit):
    env = dict(os.environ)
    env.pop("MFNAVIS_DATA_DIR", None)
    env.pop("MFNAVIS_RUNTIME_DIR", None)
    env.pop("PIFINDER_DATA_DIR", None)
    env.pop("PIFINDER_RUNTIME_DIR", None)
    data = Path.home() / "MFNavis_data"
    if not data.exists() and (Path.home() / "PiFinder_data").exists():
        data = Path.home() / "PiFinder_data"
    runtime = Path("/dev/shm/mfnavis")
    if explicit:
        data = tmp_path / "test-data"
        runtime = tmp_path / "test-runtime"
        env["PIFINDER_DATA_DIR"] = str(data)
        env["PIFINDER_RUNTIME_DIR"] = str(runtime)
    output = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import json; from PiFinder import utils; "
            "print(json.dumps([str(utils.data_dir), str(utils.runtime_dir)]))",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
    )
    if not (Path("/dev/shm").is_dir() and os.access("/dev/shm", os.W_OK)):
        runtime = data
    assert json.loads(output) == [str(data), str(runtime)]
