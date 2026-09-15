#!/usr/bin/env bash
# Explicit, reboot-volatile switch; never installs/enables a test boot service.
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
override_dir=/run/systemd/system/pifinder.service.d
override_file="${override_dir}/90-detector-test.conf"
case "${1:-status}" in
  start)
    profile="${2:-mf4p}"
    [[ "$profile" == mf ]] && profile=mf4p
    mode="${3:-auto}"
    case "$mode" in auto|sync) ;; *) echo 'mode must be auto or sync' >&2; exit 2;; esac
    profile_lines=$(PYTHONPATH="$repo_dir/python" python3 -m PiFinder.detector_profiles "$profile" --systemd)
    test "$EUID" -eq 0 || { echo 'Run with sudo only when service switching is requested.' >&2; exit 1; }
    test -f "$repo_dir/python/PiFinder/star_detect.py"
    if [[ "$profile" != sep ]]; then
      test -f "$repo_dir/python/mf_detect_star/build/libmf_detect_star.so"
    fi
    mkdir -p "$override_dir"
    cat > "$override_file" <<EOF
[Service]
WorkingDirectory=$repo_dir/python
Environment=PIFINDER_DATA_DIR=/home/pifinder/PiFinder_test_data
Environment=PIFINDER_RUNTIME_DIR=/dev/shm/pifinder_test
$profile_lines
Environment=PIFINDER_PREPROCESS_MODE=$mode
Environment=MF_DETECT_LIBRARY=$repo_dir/python/mf_detect_star/build/libmf_detect_star.so
EOF
    systemctl daemon-reload
    if ! (systemctl restart pifinder.service && sleep 2 && systemctl is-active --quiet pifinder.service); then
      rm -f "$override_file"
      systemctl daemon-reload
      systemctl restart pifinder.service
      exit 1
    fi
    ;;
  restore)
    test "$EUID" -eq 0 || { echo 'Run with sudo.' >&2; exit 1; }
    rm -f "$override_file"
    systemctl daemon-reload
    systemctl restart pifinder.service
    ;;
  status)
    systemctl show pifinder.service -p WorkingDirectory -p Environment -p ActiveState
    ;;
  *) echo 'Usage: test_runtime.sh start [mf4p|mf2|mf1|mf4o|mf8p|mf4p-pure|sep] [auto|sync] | restore | status' >&2; exit 2;;
esac
