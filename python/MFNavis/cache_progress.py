"""Line-delimited progress shared by the cache CLI and web job monitor."""

import json

PROGRESS_PREFIX = "MFNAVIS_CACHE_PROGRESS "


def emit_progress(stage, **values):
    print(PROGRESS_PREFIX + json.dumps({"stage": stage, **values}), flush=True)
