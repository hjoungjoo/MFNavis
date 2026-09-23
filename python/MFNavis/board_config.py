from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


MODEL_PATH = Path("/proc/device-tree/model")
PWM_SYSFS_ROOT = Path("/sys/class/pwm")
# RP1 PWM0 block (the one pwm-2chan routes to GPIO12/13) in /proc/device-tree.
RP1_PWM0_DEVICE = "1f00098000.pwm"


@dataclass(frozen=True)
class BoardProfile:
    name: str
    gps_device: str
    uart_overlay: str
    # Fallback sysfs PWM chip index for the keypad backlight PWM.  Pi 1-4
    # expose the SoC PWM block as pwmchip0.  Pi 5 / CM5 drive PWM through the
    # RP1 controller, whose chip index depends on the kernel (2 on 6.6, 0 on
    # 6.12+), so get_pwm_chip() resolves it from sysfs and only uses this
    # value when the scan finds nothing.
    pwm_chip: int


PI5_CLASS = BoardProfile(
    name="pi5_class",
    gps_device="/dev/ttyAMA2",
    uart_overlay="dtoverlay=uart2-pi5",
    pwm_chip=2,
)
PI4 = BoardProfile(
    name="pi4",
    gps_device="/dev/ttyAMA3",
    uart_overlay="dtoverlay=uart3",
    pwm_chip=0,
)
LEGACY = BoardProfile(
    name="legacy",
    gps_device="/dev/ttyAMA1",
    uart_overlay="dtoverlay=uart3",
    pwm_chip=0,
)


def read_board_model(model_path: Path = MODEL_PATH) -> str:
    try:
        return model_path.read_bytes().decode(errors="ignore").strip("\x00")
    except OSError:
        return ""


def get_board_profile(model: str | None = None) -> BoardProfile:
    model = read_board_model() if model is None else model
    if "Raspberry Pi 5" in model or "Compute Module 5" in model:
        return PI5_CLASS
    if "Raspberry Pi 4" in model:
        return PI4
    return LEGACY


def get_default_gpsd_device(model: str | None = None) -> str:
    return get_board_profile(model).gps_device


def get_uart_overlay(model: str | None = None) -> str:
    return get_board_profile(model).uart_overlay


def _find_rp1_pwm_chip(sysfs_root: Path = PWM_SYSFS_ROOT) -> int | None:
    for chip in sorted(sysfs_root.glob("pwmchip*")):
        try:
            device = (chip / "device").resolve().name
        except OSError:
            continue
        if device == RP1_PWM0_DEVICE:
            return int(chip.name.removeprefix("pwmchip"))
    return None


def get_pwm_chip(model: str | None = None) -> int:
    profile = get_board_profile(model)
    if profile.name != PI5_CLASS.name:
        return profile.pwm_chip
    chip = _find_rp1_pwm_chip()
    return profile.pwm_chip if chip is None else chip
