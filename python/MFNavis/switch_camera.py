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


def _default_imx678_overlay(model_path=Path("/proc/device-tree/model")) -> str:
    """MFNavis CM5 uses the verified CSI0 converter without installer options."""
    try:
        model = model_path.read_text().rstrip("\x00\n")
    except OSError:
        model = ""
    if "Raspberry Pi Compute Module 5" in model:
        return "imx678-mfnavis-cm5-converter"
    return "imx678-mfnavis"


def _switch_imx678(boot_config_path, *, converter: bool = False) -> None:
    """Keep the selected board wiring across menu switches and boot sections."""
    boot = Path(boot_config_path)
    lines = boot.read_text().splitlines(keepends=True)
    names = ("imx678-mfnavis", "imx678-mfnavis-cm5-converter")
    candidates = [
        line.strip().lstrip("#").strip()
        for line in lines
        if line.strip().lstrip("#").strip().split(",")[0]
        in tuple(f"dtoverlay={name}" for name in names)
    ]
    active = [line.strip() for line in lines if line.strip() in candidates]
    if converter:
        selected = "dtoverlay=imx678-mfnavis-cm5-converter"
    elif active or candidates:
        selected = (active or candidates)[-1]
    else:
        selected = f"dtoverlay={_default_imx678_overlay()}"
    overlay = selected.split(",")[0].split("=", 1)[1]
    if not (boot.parent / "overlays" / f"{overlay}.dtbo").is_file():
        raise RuntimeError(
            "Prepare IMX678 first: sudo bash scripts/install_imx678.sh --install"
        )
    result = []
    for line in lines:
        value = line.strip()
        if value.lstrip("#").strip() == selected or value == "camera_auto_detect=0":
            continue
        if value.startswith(("dtoverlay=imx", "camera_auto_detect=")):
            line = "#" + line
        result.append(line)
    # Canonical all-board section, even when the previous profile was in [pi4].
    while result and result[-1].strip() in ("", "[all]"):
        result.pop()
    if result and not result[-1].endswith("\n"):
        result[-1] += "\n"
    result.extend(["[all]\n", "camera_auto_detect=0\n", selected + "\n"])
    boot.write_text("".join(result))


def switch_boot(cam_type: str, *, converter: bool = False) -> None:
    """
    Edit the Raspberry Pi boot config to swap camera driver.
    Must be run as root.
    """
    if cam_type not in ("imx477", "imx296", "imx290", "imx462", "imx678"):
        raise ValueError(f"Unsupported camera: {cam_type}")
    boot_config_path = get_boot_config_path()
    if cam_type == "imx678":
        _switch_imx678(boot_config_path, converter=converter)
        return
    if converter:
        raise ValueError("The CM5 converter requires IMX678")
    overlay_name = cam_type

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
        if f"dtoverlay={overlay_name}" in line:
            boot_lines[i] = line[1:]
            cam_added = True

    if not cam_added:
        if cam_type in ("imx290", "imx462"):
            boot_lines.append(f"dtoverlay={cam_type},clock-frequency=74250000\n")
        else:
            boot_lines.append(f"dtoverlay={overlay_name}\n")
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
