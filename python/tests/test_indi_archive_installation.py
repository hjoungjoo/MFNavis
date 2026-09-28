"""Exercise the real installer with system operations redirected to a fake root."""

import hashlib
import fcntl
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.unit


def executable(path, code):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    path.chmod(0o755)


@pytest.fixture
def installation(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in (
        "install_indi_mount_archive.sh",
        "verify_indi_archive.py",
        "indi_archive_platform.sh",
        "indi_archive_transaction.py",
    ):
        shutil.copy2(ROOT / "scripts" / name, repo / "scripts" / name)
    shutil.copy2(ROOT / "mfnavis_paths.sh", repo / "mfnavis_paths.sh")
    # Real installer logic, with a reserve sized for the tiny fake installation
    # on this device's 256 MiB /tmp. The real reserve is tested independently.
    safety = repo / "scripts/indi_archive_transaction.py"
    safety.write_text(
        safety.read_text().replace("RESERVE = 256 * 1024**2", "RESERVE = 1024 * 1024")
    )
    system = tmp_path / "system"
    # Match the fake ARM/Python 3.13 host below without reading the runner's
    # real OS (e.g. Ubuntu in CI). Keep the platform guard itself active.
    os_release = system / "etc/os-release"
    os_release.parent.mkdir(parents=True)
    os_release.write_text("VERSION_CODENAME=trixie\n")
    platform = repo / "scripts/indi_archive_platform.sh"
    platform.write_text(
        platform.read_text().replace("/etc/os-release", str(os_release))
    )
    (system / "usr/bin").mkdir(parents=True)
    (system / "usr/bin/indiserver").write_text("OLD_NATIVE")
    (system / "usr/bin/bash").write_text("SYSTEM_SENTINEL")
    for path in (system, system / "usr", system / "usr/bin"):
        path.chmod(0o750)
    venv = system / "home/user/venv"
    venv.mkdir(parents=True)
    (venv / "old.py").write_text("OLD_PYTHON")
    config = system / "etc/systemd/system/indiwebmanager.service"
    config.parent.mkdir(parents=True)
    config.write_text("OLD_SERVICE")
    chrony = system / "etc/chrony/chrony.conf"
    chrony.parent.mkdir(parents=True)
    chrony.write_text("OLD_CHRONY\n")
    fakebin = tmp_path / "commands"
    fakebin.mkdir()
    executable(fakebin / "uname", "#!/bin/sh\necho aarch64\n")
    executable(
        fakebin / "mktemp",
        """#!/usr/bin/python3
import os, tempfile
print(tempfile.mkdtemp(dir=os.environ['TEST_WORK']))
""",
    )
    executable(
        venv / "bin/python",
        """#!/usr/bin/python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
venv = Path(os.environ['TEST_VENV'])
if args[0].endswith('verify_indi_archive.py'):
    # Host ABI tests are separate; all archive content checks remain real.
    os.execv(sys.executable, [sys.executable, *[a for a in args if a != '--check-host']])
if args[0] == '-c':
    code = args[1]
    if 'version_info' in code: print('3.13')
    elif 'get_path' in code: print(venv / 'bin/indi-web')
    elif 'print(sys.prefix)' in code: print(venv)
    elif 'import PyIndi' in code and os.environ['TEST_FAILURE'] == 'import': sys.exit(43)
    sys.exit(0)
if args[:3] == ['-m', 'pip', 'install']:
    if '--dry-run' not in args:
        (venv / 'old.py').unlink()
        (venv / 'new.py').write_text('NEW_PYTHON')
        if os.environ['TEST_FAILURE'] in ('pip', 'rollback'): sys.exit(42)
    sys.exit(0)
raise SystemExit('unexpected Python invocation: ' + str(args))
""",
    )
    executable(
        fakebin / "sudo",
        """#!/usr/bin/python3
import importlib.util, os, shutil, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ['TEST_ROOT'])
with Path(os.environ['TEST_CALLS']).open('a') as log: log.write(' '.join(args) + '\\n')
if args[0] == '/usr/bin/python3':
    if os.environ['TEST_FAILURE'] == 'rollback' and 'rollback' in args: sys.exit(46)
    if os.environ['TEST_FAILURE'] == 'disk' and '--check-only' in args: sys.exit(45)
    spec = importlib.util.spec_from_file_location('transaction', args[1])
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    # The fake root lives on this device's small /tmp tmpfs.
    module.RESERVE = 1024 * 1024
    sys.argv = args[1:]
    if 'snapshot' in args: sys.argv += ['--target', str(root)]
    sys.exit(module.main())
if args[0] in ('apt', 'apt-get', 'ldconfig', 'chown'): sys.exit(0)
if args[0] == 'rm':
    if os.environ['TEST_FAILURE'] == 'cleanup': sys.exit(47)
    sys.exit(subprocess.run(args).returncode)
if args[0] == 'systemctl':
    action = args[1]
    if action == 'is-active': sys.exit(0)
    if action == 'enable':
        link = root / 'etc/systemd/system/multi-user.target.wants/indiwebmanager.service'
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to('../indiwebmanager.service')
    fail = os.environ['TEST_FAILURE']
    marker = Path(os.environ['TEST_WORK']) / 'failure-injected'
    if not marker.exists() and action == 'restart' and (
        (fail == 'service' and args[2] == 'indiwebmanager.service') or
        (fail == 'chrony' and args[2] == 'chrony')
    ):
        marker.touch(); sys.exit(44)
    sys.exit(0)
if args[0] == 'tar':
    if args[1:3] == ['-C', '/']:
        args[2] = str(root); args.insert(3, '--no-same-owner')
    sys.exit(subprocess.run(args).returncode)
if args[0] == 'cp':
    shutil.copy2(args[1], root / args[2].lstrip('/')); sys.exit(0)
if args[0] == 'chmod':
    (root / args[2].lstrip('/')).chmod(int(args[1], 8)); sys.exit(0)
if args[0] == 'grep':
    args[-1] = str(root / args[-1].lstrip('/'))
    sys.exit(subprocess.run(args).returncode)
if args[0] == 'tee':
    path = root / args[-1].lstrip('/')
    with path.open('a' if '-a' in args else 'w') as output: output.write(sys.stdin.read())
    sys.exit(0)
raise SystemExit('unexpected sudo invocation: ' + str(args))
""",
    )
    archive = tmp_path / "indi.tar.gz"
    info = "\n".join(
        (
            "archive_format=mfnavis-indi-binary-v2",
            "os_codename=trixie",
            "machine=aarch64",
            "python_version=3.13",
            "python_soabi=cpython-313-aarch64-linux-gnu",
            "python_payload=wheels",
        )
    )
    with tarfile.open(archive, "w:gz") as output:
        for name, data in (
            ("rootfs", None),
            ("rootfs/usr", None),
            ("rootfs/usr/bin", None),
            ("rootfs/usr/bin/indiserver", "NEW_NATIVE"),
            ("rootfs/usr/bin/indi_new", "NEW_DRIVER"),
            ("metadata", None),
            ("metadata/build_info.txt", info),
            ("metadata/runtime-packages.txt", "libev4t64\n"),
            (
                "metadata/python-requirements.txt",
                "pyindi-client==2.1.2\nindiweb==1.0.0\n",
            ),
            ("wheels", None),
            ("wheels/pyindi_client-2.1.2-cp313-cp313-linux_aarch64.whl", "wheel"),
            ("wheels/indiweb-1.0.0-py3-none-any.whl", "wheel"),
        ):
            member = tarfile.TarInfo(name)
            member.mode = 0o775
            if data is None:
                member.type = tarfile.DIRTYPE
                output.addfile(member)
            else:
                content = data.encode()
                member.size = len(content)
                output.addfile(member, io.BytesIO(content))
    Path(str(archive) + ".sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    return repo, system, venv, fakebin, archive


def run_install(installation, failure):
    repo, system, venv, fakebin, archive = installation
    return subprocess.run(
        ["bash", str(repo / "scripts/install_indi_mount_archive.sh"), str(archive)],
        env={
            **os.environ,
            "PATH": f"{fakebin}:{os.environ['PATH']}",
            "MFNAVIS_REPO_DIR": str(repo),
            "MFNAVIS_PYTHON": str(venv / "bin/python"),
            "MFNAVIS_DATA_DIR": str(repo / "data"),
            "MFNAVIS_HOME": str(repo),
            "TEST_ROOT": str(system),
            "TEST_VENV": str(venv),
            "TEST_WORK": str(repo.parent),
            "TEST_CALLS": str(repo / "calls.log"),
            "TEST_FAILURE": failure,
        },
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("failure", ["pip", "import", "service", "chrony"])
def test_installer_failure_rolls_back_before_restarting_services(installation, failure):
    result = run_install(installation, failure)
    repo, system, venv, _, _ = installation
    assert result.returncode != 0, result.stdout + result.stderr
    assert "restored" in result.stdout, result.stdout + result.stderr
    assert (system / "usr/bin/indiserver").read_text() == "OLD_NATIVE"
    assert not (system / "usr/bin/indi_new").exists()
    assert (venv / "old.py").read_text() == "OLD_PYTHON"
    assert not (venv / "new.py").exists()
    assert (
        system / "etc/systemd/system/indiwebmanager.service"
    ).read_text() == "OLD_SERVICE"
    assert (system / "etc/chrony/chrony.conf").read_text() == "OLD_CHRONY\n"
    assert not (
        system / "etc/systemd/system/multi-user.target.wants/indiwebmanager.service"
    ).is_symlink()
    assert (system / "usr/bin/bash").read_text() == "SYSTEM_SENTINEL"
    assert all(
        p.stat().st_mode & 0o777 == 0o750
        for p in (system, system / "usr", system / "usr/bin")
    )
    calls = (repo / "calls.log").read_text()
    assert calls.index(" rollback ") < calls.rindex("systemctl start mfnavis.service")
    logs = list((repo / "data/logs").glob("indi-install-*.log"))
    assert logs and "restored" in logs[0].read_text()


def test_success_preserves_directory_modes_and_keeps_new_installation(installation):
    result = run_install(installation, "none")
    repo, system, venv, _, _ = installation
    assert result.returncode == 0, result.stdout + result.stderr
    assert (system / "usr/bin/indiserver").read_text() == "NEW_NATIVE"
    assert (venv / "new.py").read_text() == "NEW_PYTHON"
    assert (system / "usr/bin/bash").read_text() == "SYSTEM_SENTINEL"
    assert all(
        p.stat().st_mode & 0o777 == 0o750
        for p in (system, system / "usr", system / "usr/bin")
    )
    assert " rollback " not in (repo / "calls.log").read_text()
    assert "rm -rf -- " in (repo / "calls.log").read_text()
    assert not list(repo.parent.glob("tmp*/rollback"))


def test_cleanup_failure_is_reported_without_rolling_back_committed_install(
    installation,
):
    result = run_install(installation, "cleanup")
    repo, system, venv, _, _ = installation
    assert result.returncode != 0, result.stdout + result.stderr
    assert (system / "usr/bin/indiserver").read_text() == "NEW_NATIVE"
    assert (venv / "new.py").read_text() == "NEW_PYTHON"
    calls = (repo / "calls.log").read_text()
    assert "rm -rf -- " in calls
    assert " rollback " not in calls
    assert len(list(repo.parent.glob("tmp*/rollback/state.json"))) == 1


def test_preflight_failure_leaves_services_and_files_untouched(installation):
    result = run_install(installation, "disk")
    repo, system, venv, _, _ = installation
    assert result.returncode != 0
    assert (system / "usr/bin/indiserver").read_text() == "OLD_NATIVE"
    assert (venv / "old.py").read_text() == "OLD_PYTHON"
    assert "systemctl stop" not in (repo / "calls.log").read_text()


def test_rollback_failure_retains_snapshot_and_leaves_services_stopped(installation):
    result = run_install(installation, "rollback")
    repo, _, _, _, _ = installation
    assert result.returncode != 0
    assert "Rollback failed" in result.stdout
    assert "systemctl start" not in (repo / "calls.log").read_text()
    assert "rm -rf -- " not in (repo / "calls.log").read_text()
    states = list(repo.parent.glob("tmp*/rollback/state.json"))
    assert len(states) == 1
    assert (states[0].parent / "previous.tar").is_file()


def test_another_installation_cannot_enter_while_lock_is_held(installation):
    repo = installation[0]
    with (repo / ".indi-install.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run_install(installation, "none")
    assert result.returncode != 0
    assert "already running" in result.stdout
    assert not (repo / "calls.log").exists()
