#!/usr/bin/python
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING or __package__:
    from PiFinder.boot_config import get_boot_config_path
else:
    # Installed alongside this script for privileged execution, independent
    # of the service's working directory and virtual environment.
    from boot_config import get_boot_config_path


def switch_boot(cam_type: str) -> None:
    """
    Edit the Raspberry Pi boot config to swap camera driver.
    Must be run as root.
    """
    if cam_type not in ("imx477", "imx296", "imx290", "imx462", "imx678"):
        raise ValueError(f"Unsupported camera: {cam_type}")
    boot_config_path = get_boot_config_path()
    overlay_name = "imx678-mfnavis" if cam_type == "imx678" else cam_type
    if cam_type == "imx678":
        if not (
            Path(boot_config_path).parent / "overlays" / f"{overlay_name}.dtbo"
        ).is_file():
            raise RuntimeError(
                "Prepare IMX678 first: sudo bash scripts/install_imx678.sh --install"
            )

    # read config.txt into a list
    with open(boot_config_path, "r") as boot_in:
        boot_lines = list(boot_in)

    # Disable any existing cams
    for i, line in enumerate(boot_lines):
        if "dtoverlay=imx" in line and not line.startswith("#"):
            boot_lines[i] = "#" + line

        if "camera_auto_detect" in line and not line.startswith("#"):
            if cam_type == "imx678" and line.strip() == "camera_auto_detect=0":
                continue
            boot_lines[i] = "#" + line

    # Look for a line for requested cam
    cam_added = False
    for i, line in enumerate(boot_lines):
        if f"dtoverlay={overlay_name}" in line:
            boot_lines[i] = line[1:]
            cam_added = True

    if not cam_added:
        if cam_type in ("imx290", "imx462"):
            boot_lines.append(f"dtoverlay={cam_type},clock-frequency=74250000\n")
        else:
            if cam_type == "imx678":
                if boot_lines and not boot_lines[-1].endswith("\n"):
                    boot_lines[-1] += "\n"
                boot_lines.append("[all]\n")
            boot_lines.append(f"dtoverlay={overlay_name}\n")
        cam_added = True

    if cam_type == "imx678" and not any(
        line.strip() == "camera_auto_detect=0" for line in boot_lines
    ):
        boot_lines.append("[all]\ncamera_auto_detect=0\n")

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
