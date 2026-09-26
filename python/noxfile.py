import os
import sys

import nox

nox.options.sessions = ["lint", "format", "type_hints", "smoke_tests"]

# Keep the Bookworm CI default; an active Python 3.13 uses the Trixie setup.
_PYTHON = os.environ.get("NOX_PYTHON") or (
    "3.13" if sys.version_info[:2] == (3, 13) else "3.11"
)
_TRIXIE = _PYTHON == "3.13"
_DEV_REQUIREMENTS = "requirements_dev-trixie.txt" if _TRIXIE else "requirements_dev.txt"
_DOC_REQUIREMENTS = (
    "requirements_docs-trixie.txt" if _TRIXIE else "../docs/source/requirements.txt"
)
_VENV_PARAMS = ["--system-site-packages"] if _TRIXIE else []


def _install(session: nox.Session, *args: str) -> None:
    if not session.virtualenv.is_sandboxed:
        if sys.prefix == sys.base_prefix:
            session.error("Activate the development venv before using --no-venv")
        session.log("Using packages from the active development environment")
        return
    session.install(*args)


def _install_development(session: nox.Session) -> None:
    # Both developer requirement files include their matching runtime file.
    _install(session, "-r", _DEV_REQUIREMENTS)
    if (
        session.virtualenv.is_sandboxed
        and _TRIXIE
        and os.environ.get("MFNAVIS_DEV_USE_OS_GPIO") == "1"
    ):
        session.run("python", "-m", "pip", "uninstall", "-y", "RPi.GPIO")


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def lint(session: nox.Session) -> None:
    """
    Check the project's codebase for lint violations.

    Fails when the linter finds a violation, so CI catches it. This session
    deliberately does NOT rewrite files: it used to run ``ruff check --fix``,
    which repaired the checkout and then exited 0, so violations could be
    committed and CI never noticed. Run ``nox -s lint_fix`` to apply.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    _install(session, "ruff==0.4.8")
    session.run("ruff", "check", "--config", "builtins=['_']")


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def lint_fix(session: nox.Session) -> None:
    """
    Apply the linter's automatic fixes (rewrites files).

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    _install(session, "ruff==0.4.8")
    session.run("ruff", "check", "--fix", "--config", "builtins=['_']")


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def format(session: nox.Session) -> None:
    """
    Check the project's code formatting.

    Fails (and prints the diff) when a file is not formatted, so CI catches
    drift. This session deliberately does NOT rewrite files: it used to run a
    bare ``ruff format``, which always exited 0, so unformatted code could be
    committed and CI never noticed. Run ``nox -s format_fix`` to apply.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    _install(session, "ruff==0.4.8")
    session.run("ruff", "format", "--check", "--diff")


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def format_fix(session: nox.Session) -> None:
    """
    Apply the project's code formatting (rewrites files).

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    _install(session, "ruff==0.4.8")
    session.run("ruff", "format")


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def type_hints(session: nox.Session) -> None:
    """
    Check type hints in the project's codebase.

    This session installs necessary dependencies for type checking and runs a static type checker
    to validate the type hints throughout the project's codebase, ensuring they are correct and consistent.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    _install_development(session)
    # First run populates the cache so --install-types knows what stubs are needed.
    # success_codes=[0, 1] here is expected: missing-stub errors before stubs are
    # installed. The second run (with stubs) must exit 0; real type errors fail CI.
    # Targets PiFinder/ explicitly to avoid broken tetra3 symlink in the tree.
    session.run("python", "-m", "mypy", "PiFinder", success_codes=[0, 1])
    session.run(
        "python", "-m", "mypy", "--install-types", "--non-interactive", "PiFinder"
    )


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def unit_tests(session: nox.Session) -> None:
    """
    Run the project's unit tests.

    This session installs the necessary dependencies and runs the project's unit tests.
    It is focused on testing the functionality of individual units of code in isolation.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    _install_development(session)
    session.run("pytest", "-m", "unit", *session.posargs)


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def web_tests(session: nox.Session) -> None:
    """
    Run the project's test suite on the web interface.

    This session installs the necessary dependencies and tests the web interface using Selenium.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    _install_development(session)
    session.run("pytest", "-m", "web")


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def smoke_tests(session: nox.Session) -> None:
    """
        Run the project's smoke tests.
    nox
        This session installs the necessary dependencies and runs a subset of tests designed to quickly
        check the most important functions of the program, often as a prelude to more thorough testing.

        Args:
            session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    _install_development(session)
    session.run("pytest", "-m", "smoke")


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def ui_tests(session: nox.Session) -> None:
    """
    Run the UI module smoke harness (tests/test_ui_modules.py).

    Constructs every UI screen through a real MenuManager and exercises its
    key_* methods (crash-only smoke). Builds the real catalogs and, for
    chart/align, may download hip_main.dat on first run. Heavier and more
    network-dependent than the unit suite, so it lives in its own session.

    Args:
        session (nox.Session): The Nox session being run, providing context and methods for session actions.
    """
    _install_development(session)
    session.run("pytest", "-m", "integration", "tests/test_ui_modules.py")


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def babel(session: nox.Session) -> None:
    """
    Run the I18N toolchain
    """
    _install_development(session)

    session.run(
        "pybabel",
        "extract",
        "-F",
        "babel.cfg",
        "-c",
        "TRANSLATORS",
        "-o",
        "locale/messages.pot",
        "./PiFinder",
        "./views",
    )
    session.run("pybabel", "update", "-i", "locale/messages.pot", "-d", "locale")
    session.run("pybabel", "compile", "-d", "locale")


@nox.session(reuse_venv=True, python=_PYTHON, venv_params=_VENV_PARAMS)
def docs(session: nox.Session) -> None:
    """
    Build the Sphinx user manual, failing on any warning.

    Read the Docs publishes this manual from the same pinned requirements, but
    it only builds after a push. Locally this is the check that catches a
    cross-reference, substitution or image that a partially-applied upstream
    doc change left dangling -- ``-n`` reports missing references and ``-W``
    turns every warning into a failure, so "it rendered" is not mistaken for
    "it is correct". ``--keep-going`` reports all of them in one run.
    """
    _install(session, "-r", _DOC_REQUIREMENTS)
    session.run(
        "python",
        "-m",
        "sphinx",
        "-n",
        "-W",
        "--keep-going",
        "-q",
        "-E",
        "../docs/source",
        "../docs/build/html",
    )
