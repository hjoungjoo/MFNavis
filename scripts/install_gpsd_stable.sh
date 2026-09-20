#!/usr/bin/env bash
# Install the upstream stable daemon without replacing Debian's client libraries.
set -euo pipefail

# Official release, checked 2026-09-20. Update version and digest together.
version=3.27.5
sha256=409873f5048462ef1ac413a51ab35caa8b50b31be62b3347bee1cc2994e7c649
prefix="/opt/pifinder/gpsd-${version}"
dropin=/etc/systemd/system/gpsd.service.d/50-pifinder-stable.conf

if [[ $(id -u) -eq 0 ]]; then
    echo 'Run as the normal PiFinder user; sudo is used only for installation.' >&2
    exit 1
fi

sudo apt-get update
sudo apt-get install -y gpsd curl ca-certificates scons build-essential \
    pkg-config python3-dev bc libncurses-dev libusb-1.0-0-dev libdbus-1-dev \
    libsystemd-dev libudev-dev

# /tmp is a small RAM disk on PiFinder; build on disk instead.
work=$(mktemp -d /var/tmp/pifinder-gpsd.XXXXXX)
trap 'rm -rf "$work"' EXIT
curl --fail --location --retry 3 \
    "https://download-mirror.savannah.gnu.org/releases/gpsd/gpsd-${version}.tar.gz" \
    --output "$work/gpsd.tar.gz"
echo "$sha256  $work/gpsd.tar.gz" | sha256sum --check --status
tar -xzf "$work/gpsd.tar.gz" -C "$work"
cd "$work/gpsd-${version}"
options=(shared=no qt=no manbuild=no systemd=yes gpsd_user=gpsd
    gpsd_group=dialout target_python=python3)
scons -j2 "${options[@]}"
scons -j2 "${options[@]}" check
build="gpsd-${version}"
"$build/gpsd/gpsd" -V

# Static libgps linkage keeps the system libgps ABI and Python bindings intact.
sudo install -d -m 755 "$prefix/sbin" "$prefix/bin"
sudo install -m 755 "$build/gpsd/gpsd" "$build/clients/gpsdctl" "$prefix/sbin/"
sudo install -m 755 "$build/clients/gpspipe" "$build/gpsctl" "$prefix/bin/"
sudo install -m 644 COPYING "$prefix/COPYING"

had_dropin=0
if sudo test -f "$dropin"; then
    sudo cat "$dropin" > "$work/previous.conf"
    had_dropin=1
fi
cat > "$work/stable.conf" <<EOF
[Service]
ExecStart=
ExecStart=$prefix/sbin/gpsd \$GPSD_OPTIONS \$OPTIONS \$DEVICES
EOF
sudo install -d -m 755 "$(dirname "$dropin")"
sudo install -m 644 "$work/stable.conf" "$dropin"
sudo systemctl daemon-reload
if ! sudo systemctl restart gpsd.service || ! sudo systemctl is-active --quiet gpsd.service; then
    echo 'GPSD restart failed; restoring the previous service command.' >&2
    if [[ $had_dropin -eq 1 ]]; then
        sudo install -m 644 "$work/previous.conf" "$dropin"
    else
        sudo rm -f "$dropin"
    fi
    sudo systemctl daemon-reload
    sudo systemctl restart gpsd.service
    exit 1
fi
echo "GPSD ${version} installed at ${prefix}; /etc/default/gpsd preserved."
