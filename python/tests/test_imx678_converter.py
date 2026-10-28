"""Compile the real power sequencing and merge the board overlay on CM5 DTBs."""

from pathlib import Path
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.unit
SOURCE = Path(__file__).resolve().parents[2] / "deployment/imx678"


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def require(*commands):
    if any(shutil.which(command) is None for command in commands):
        pytest.skip(f"Requires {' '.join(commands)}")


def test_converter_power_sequence_and_failure_cleanup(tmp_path):
    require("cc", "patch")
    shutil.copy(SOURCE / "imx678.c", tmp_path)
    run(
        "patch",
        "--batch",
        "--fuzz=0",
        "-d",
        str(tmp_path),
        "-p1",
        "-i",
        str(SOURCE / "0001-cm5-converter-power-sequence.patch"),
    )
    driver = (tmp_path / "imx678.c").read_text()
    sequence = driver.split("static int imx678_converter_power_off", 1)[1]
    sequence = (
        "static int imx678_converter_power_off"
        + sequence.split("static int imx678_power_on", 1)[0]
    )
    (tmp_path / "power-sequence-under-test.h").write_text(sequence)
    executable = tmp_path / "power-sequence-test"
    run(
        "cc",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-I",
        str(tmp_path),
        str(SOURCE / "tests/power_sequence.c"),
        "-o",
        str(executable),
    )
    assert "9 converter power sequencing / failure cases passed" in run(str(executable))


@pytest.mark.parametrize("carrier", ["cm5io", "cm4io"])
def test_converter_overlay_on_cm5(tmp_path, carrier):
    require("dtc", "dtmerge", "fdtget")
    base = Path(f"/boot/firmware/bcm2712-rpi-cm5-{carrier}.dtb")
    if not base.exists():
        pytest.skip("Requires Raspberry Pi CM5 firmware DTB")
    overlay = tmp_path / "converter.dtbo"
    merged = tmp_path / "merged.dtb"
    run(
        "dtc",
        "-@",
        "-I",
        "dts",
        "-O",
        "dtb",
        "-o",
        str(overlay),
        str(SOURCE / "imx678-mfnavis-cm5-converter-overlay.dts"),
    )
    run("dtmerge", str(base), str(merged), str(overlay))

    def prop(node, name, kind="s"):
        return run("fdtget", "-t", kind, str(merged), node, name)

    bus = prop("/__symbols__", "i2c_csi_dsi0")
    sensor = f"{bus}/imx678@1a"
    csi = prop("/__symbols__", "csi0")
    gpio = prop(prop("/__symbols__", "rp1_gpio"), "phandle", "i")
    assert prop(sensor, "compatible") == "mfnavis,imx678-cm5-converter"
    assert prop(bus, "status") == prop(csi, "status") == "okay"
    assert prop(sensor, "reset-gpios", "i") == f"{gpio} 35 1"
    assert prop("/cam0_reg", "gpio", "i") == f"{gpio} 34 0"
    assert prop("/cam0_reg", "startup-delay-us", "i") == "150000"
    assert prop("/cam0_reg", "off-on-delay-us", "i") == "150000"
    assert prop("/cam0_clk", "clock-frequency", "i") == "74250000"
    assert prop(bus, "pinctrl-names") == "default imx678-off"
    off = prop("/__symbols__", "rp1_gpio") + "/imx678-i2c-off"
    assert prop(off, "pins") == "gpio39 gpio38"
    assert prop(off, "output-low") == ""
    assert prop(bus, "pinctrl-1", "i") == prop(off, "phandle", "i")
    for endpoint in (f"{sensor}/port/endpoint", f"{csi}/port/endpoint"):
        assert prop(endpoint, "data-lanes", "i") == "1 2 3 4"
    assert prop(f"{sensor}/port/endpoint", "remote-endpoint", "i") == prop(
        f"{csi}/port/endpoint", "phandle", "i"
    )
