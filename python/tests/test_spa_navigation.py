"""Execute the SPA history regression tests without browser dependencies."""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.unit
def test_spa_navigation_history():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the JavaScript navigation tests")
    script = Path(__file__).with_name("js") / "spa_navigation.mjs"
    result = subprocess.run(
        [node, "--test", str(script)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
