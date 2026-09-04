"""Install Firefox WebExtensions before the browser process starts.

Recent Firefox builds no longer discover an XPI merely because it was copied
to ``<profile>/extensions``.  Firefox still supports application-distributed
extensions from ``<firefox>/distribution/extensions``.  This module performs
that installation atomically so concurrent invisible_playwright sessions never
observe a partially-written archive.

The caller owns extension configuration.  In particular, this module never
logs or inspects resources such as API keys embedded in an XPI.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Iterable


_INSTALL_LOCK = threading.Lock()
_ADDON_ID_RE = re.compile(r"^[A-Za-z0-9@._{}+-]+$")


class FirefoxExtensionInstallError(RuntimeError):
    """A requested Firefox extension could not be installed safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def firefox_extension_id(xpi_path: os.PathLike[str] | str) -> str:
    """Read and validate the Gecko ID declared by an XPI manifest."""

    source = Path(xpi_path).expanduser().resolve()
    if not source.is_file():
        raise FirefoxExtensionInstallError(f"Firefox extension does not exist: {source}")
    try:
        with zipfile.ZipFile(source) as archive:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8-sig"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise FirefoxExtensionInstallError(
            f"Firefox extension has no valid root manifest.json: {source}"
        ) from exc

    addon_id = None
    for key in ("browser_specific_settings", "applications"):
        gecko = (manifest.get(key) or {}).get("gecko") if isinstance(manifest, dict) else None
        if isinstance(gecko, dict) and gecko.get("id"):
            addon_id = str(gecko["id"])
            break
    if not addon_id or not _ADDON_ID_RE.fullmatch(addon_id):
        raise FirefoxExtensionInstallError(
            f"Firefox extension has no valid Gecko ID: {source}"
        )
    return addon_id


def install_firefox_extensions(
    firefox_executable: os.PathLike[str] | str,
    xpi_paths: Iterable[os.PathLike[str] | str],
) -> tuple[Path, ...]:
    """Atomically install XPIs into the selected Firefox distribution.

    The destination is tied to the resolved engine binary, so a future
    invisible_playwright engine upgrade automatically receives the extensions
    again on its first launch. Existing identical files are left untouched.
    """

    executable = Path(firefox_executable).expanduser().resolve()
    if not executable.is_file():
        raise FirefoxExtensionInstallError(f"Firefox executable does not exist: {executable}")
    sources = [Path(value).expanduser().resolve() for value in xpi_paths]
    if not sources:
        return ()

    prepared = [(source, firefox_extension_id(source)) for source in sources]
    destination_dir = executable.parent / "distribution" / "extensions"
    installed: list[Path] = []

    with _INSTALL_LOCK:
        destination_dir.mkdir(parents=True, exist_ok=True)
        for source, addon_id in prepared:
            destination = destination_dir / f"{addon_id}.xpi"
            if destination.is_file() and _sha256(destination) == _sha256(source):
                installed.append(destination)
                continue

            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    prefix=f".{addon_id}.",
                    suffix=".tmp",
                    dir=destination_dir,
                    delete=False,
                ) as target, source.open("rb") as origin:
                    shutil.copyfileobj(origin, target, length=1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                    temporary = Path(target.name)
                if _sha256(temporary) != _sha256(source):
                    raise FirefoxExtensionInstallError(
                        f"Firefox extension copy verification failed: {source}"
                    )
                os.replace(temporary, destination)
                temporary = None
            except OSError as exc:
                raise FirefoxExtensionInstallError(
                    f"Could not install Firefox extension {addon_id} into {destination_dir}: {exc}"
                ) from exc
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass
            installed.append(destination)
    return tuple(installed)


__all__ = [
    "FirefoxExtensionInstallError",
    "firefox_extension_id",
    "install_firefox_extensions",
]
