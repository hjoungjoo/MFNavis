"""Exercise Tools initialization and status polling across cached SPA visits."""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.unit
def test_cache_download_page_lifecycle():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the Tools UI tests")
    script = Path(__file__).with_name("js") / "cache_download.mjs"
    result = subprocess.run(
        [node, "--test", str(script)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
