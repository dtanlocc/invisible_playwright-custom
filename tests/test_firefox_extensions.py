import json
import zipfile
from pathlib import Path

import pytest

from invisible_playwright.firefox_extensions import (
    FirefoxExtensionInstallError,
    firefox_extension_id,
    install_firefox_extensions,
)
from invisible_playwright.launcher import InvisiblePlaywright
from invisible_playwright.async_api import InvisiblePlaywright as AsyncInvisiblePlaywright


def _xpi(path: Path, addon_id: str, marker: str) -> None:
    manifest = {
        "manifest_version": 3,
        "name": "Test extension",
        "version": "1.0",
        "browser_specific_settings": {"gecko": {"id": addon_id}},
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("marker.txt", marker)


def test_installs_and_atomically_replaces_distribution_extension(tmp_path: Path) -> None:
    executable = tmp_path / "engine" / "firefox.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"binary")
    source = tmp_path / "solver.xpi"
    _xpi(source, "solver@example.test", "first")

    installed = install_firefox_extensions(executable, [source])
    destination = executable.parent / "distribution" / "extensions" / "solver@example.test.xpi"

    assert installed == (destination,)
    assert destination.read_bytes() == source.read_bytes()
    _xpi(source, "solver@example.test", "second")
    install_firefox_extensions(executable, [source])
    with zipfile.ZipFile(destination) as archive:
        assert archive.read("marker.txt") == b"second"
    assert not list(destination.parent.glob("*.tmp"))


def test_reads_id_and_rejects_invalid_archive(tmp_path: Path) -> None:
    source = tmp_path / "solver.xpi"
    _xpi(source, "solver@example.test", "ok")
    assert firefox_extension_id(source) == "solver@example.test"

    broken = tmp_path / "broken.xpi"
    broken.write_bytes(b"not a zip")
    with pytest.raises(FirefoxExtensionInstallError):
        firefox_extension_id(broken)


@pytest.mark.parametrize("launcher_class", [InvisiblePlaywright, AsyncInvisiblePlaywright])
def test_launcher_extension_configuration_keeps_constructor_compatible(
    launcher_class,
    tmp_path: Path,
) -> None:
    source = tmp_path / "solver.xpi"
    _xpi(source, "solver@example.test", "ok")
    launcher = launcher_class(seed=123)

    assert launcher.set_firefox_extensions([source]) is launcher
    assert launcher._firefox_extensions == (source,)
