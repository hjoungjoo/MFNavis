"""SQM/Bortle bands shared with the device's SQM display."""

import math


# Ordered darkest first; shared boundaries belong to the darker class.
BORTLE_SQM_RANGES = {
    1: (21.76, 22.0),
    2: (21.60, 21.76),
    3: (21.30, 21.60),
    4: (20.80, 21.30),
    4.5: (20.30, 20.80),
    5: (19.25, 20.30),
    6: (18.50, 19.25),
    7: (18.00, 18.50),
    8: (17.00, 18.00),
    9: (0.0, 17.00),
}


def sqm_to_bortle(sqm):
    if not isinstance(sqm, (int, float)) or not math.isfinite(sqm):
        return None
    for bortle, (low, high) in BORTLE_SQM_RANGES.items():
        if low <= sqm <= high:
            return bortle
    return None


def bortle_to_sqm(bortle):
    """Representative brightness for an optional configured Bortle class."""
    if isinstance(bortle, bool) or bortle not in BORTLE_SQM_RANGES:
        return None
    low, high = BORTLE_SQM_RANGES[bortle]
    return 16.5 if bortle == 9 else (low + high) / 2
