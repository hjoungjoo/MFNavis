#!/usr/bin/env bash
# Explicit, reboot-volatile switch; never installs/enables a test boot service.
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
override_dir=/run/systemd/system/mfnavis.service.d
override_file="${override_dir}/90-detector-test.conf"
case "${1:-status}" in
  start)
    profile="${2:-mf4p}"
    [[ "$profile" == mf ]] && profile=mf4p
    mode="${3:-auto}"
    case "$mode" in auto|sync) ;; *) echo 'mode must be auto or sync' >&2; exit 2;; esac
    transport="${4:-process}"
    case "$transport" in process|ctypes) ;; *) echo 'transport must be process or ctypes' >&2; exit 2;; esac
    profile_lines=$(PYTHONPATH="$repo_dir/python" python3 -m MFNavis.detector_profiles "$profile" --runtime --mode "$mode" --transport "$transport" --systemd)
    test "$EUID" -eq 0 || { echo 'Run with sudo only when service switching is requested.' >&2; exit 1; }
    MFNAVIS_REPO_DIR="${repo_dir}"
    source "${repo_dir}/mfnavis_paths.sh"
    test -f "$repo_dir/python/MFNavis/star_detect.py"
    if [[ "$profile" != sep ]]; then
      if [[ "$transport" == process ]]; then
        test -x "$repo_dir/python/MFDS/build/mf_detect_star_server"
      else
        test -f "$repo_dir/python/MFDS/build/libmf_detect_star.so"
      fi
    fi
    install -d -o "${MFNAVIS_USER}" -g "${MFNAVIS_GROUP}" \
      "${MFNAVIS_DATA_DIR}/test_data"
    mkdir -p "$override_dir"
    cat > "$override_file" <<EOF
[Service]
WorkingDirectory=$repo_dir/python
Environment="MFNAVIS_DATA_DIR=${MFNAVIS_DATA_DIR}/test_data"
Environment=MFNAVIS_RUNTIME_DIR=/dev/shm/mfnavis_test
$profile_lines
Environment=MF_DETECT_SERVER=$repo_dir/python/MFDS/build/mf_detect_star_server
Environment=MF_DETECT_LIBRARY=$repo_dir/python/MFDS/build/libmf_detect_star.so
EOF
    systemctl daemon-reload
    if ! (systemctl restart mfnavis.service && sleep 2 && systemctl is-active --quiet mfnavis.service); then
      rm -f "$override_file"
      systemctl daemon-reload
      systemctl restart mfnavis.service
      exit 1
    fi
    ;;
  restore)
    test "$EUID" -eq 0 || { echo 'Run with sudo.' >&2; exit 1; }
    rm -f "$override_file"
    systemctl daemon-reload
    systemctl restart mfnavis.service
    ;;
  status)
    systemctl show mfnavis.service -p WorkingDirectory -p Environment -p ActiveState
    ;;
  *) echo 'Usage: test_runtime.sh start [mf4p|mf2|mf1|mf4o|mf8p|mf4p-pure|sep] [auto|sync] [process|ctypes] | restore | status' >&2; exit 2;;
esac
