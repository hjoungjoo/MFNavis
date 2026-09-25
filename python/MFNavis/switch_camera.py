#!/usr/bin/python
import sys

from PiFinder.boot_config import get_boot_config_path


def switch_boot(cam_type: str) -> None:
    """
    Edit the Raspberry Pi boot config to swap camera driver.
    Must be run as root.
    """
    boot_config_path = get_boot_config_path()

    # read config.txt into a list
    with open(boot_config_path, "r") as boot_in:
        boot_lines = list(boot_in)

    # Disable any existing cams
    for i, line in enumerate(boot_lines):
        if "dtoverlay=imx" in line and not line.startswith("#"):
            boot_lines[i] = "#" + line

        if "camera_auto_detect" in line and not line.startswith("#"):
            boot_lines[i] = "#" + line

    # Look for a line for requested cam
    cam_added = False
    for i, line in enumerate(boot_lines):
        if f"dtoverlay={cam_type}" in line:
            boot_lines[i] = line[1:]
            cam_added = True

    if not cam_added:
        if cam_type in ("imx290", "imx462"):
            boot_lines.append(f"dtoverlay={cam_type},clock-frequency=74250000\n")
        else:
            boot_lines.append(f"dtoverlay={cam_type}\n")
        cam_added = True

    with open(boot_config_path, "w") as boot_out:
        for line in boot_lines:
            boot_out.write(line)


def ensure_default_boot(cam_type: str = "imx462") -> bool:
    """Select the product camera only if no sensor overlay is configured."""
    with open(get_boot_config_path(), "r") as boot_in:
        if any(line.strip().startswith("dtoverlay=imx") for line in boot_in):
            return False
    switch_boot(cam_type)
    return True


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--default":
        ensure_default_boot(sys.argv[2])
    elif len(sys.argv) == 2:
        switch_boot(sys.argv[1])
    else:
        raise SystemExit("Usage: switch_camera.py [--default] CAMERA_TYPE")
