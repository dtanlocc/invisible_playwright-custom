"""Procures the Node that runs the forked driver.

WHY WE DON'T SHIP IT. The Playwright driver weighs 105 MB, of which 92.3 are
``node.exe``. Committing it would mean a 92 MB binary in git history
forever, against a GitHub limit of 100 MB per file, times four
platforms. So we version the code (``_pw/`` and ``_driver/``, 9 MB in
all) and download the runtime on first use, the same way Playwright itself does
with browsers.

ONE SOURCE ONLY. The download, the checksum and the cache folder are those of
``invisible_core.download``: they are already written, already tested, and having a
second copy of them here would be the same fact done in two places. They are private
names of a package we write ourselves and that this wrapper pins to an EXACT
version (the number lives in ``pyproject.toml`` and nowhere else: writing it
twice is the drift ``tests/test_core_pin.py`` exists to prevent, and
this module violated it on its first attempt). It's that pin which makes it legitimate
to rely on private names, and it has been verified that they exist in the PUBLISHED
wheel and not only in the working tree: a consumer can only use
what the index has.

⛔ NO FALLING BACK TO SOMEONE ELSE'S NODE. The temptation is to reuse the
``playwright`` package's ``node.exe``, if it happens to be installed: free, and
already on disk. It is exactly the fallback-to-the-host that rule 7
forbids, in miniature: two users would end up running two different Node
runtimes depending on what they had installed for other reasons, and no gate would
notice. One declared version, the same for everyone.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path

#: The version that Playwright 1.61.0 bundles in its driver. The driver is a
#: Node program like any other: it runs on any sufficiently recent runtime,
#: but declaring ONE is what makes the same session the same session on
#: two different machines.
NODE_VERSION = "v24.17.0"

BASE = "https://nodejs.org/dist/" + NODE_VERSION


class NodeError(RuntimeError):
    """Node is not available and could not be procured."""


def _target() -> tuple[str, str, str]:
    """(archive name, path to the binary inside the archive, file name)."""
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "win32":
        arch = "win-arm64" if arm else "win-x64"
        return ("node-%s-%s.zip" % (NODE_VERSION, arch),
                "node-%s-%s/node.exe" % (NODE_VERSION, arch), "node.exe")
    if sys.platform == "darwin":
        arch = "darwin-arm64" if arm else "darwin-x64"
        return ("node-%s-%s.tar.gz" % (NODE_VERSION, arch),
                "node-%s-%s/bin/node" % (NODE_VERSION, arch), "node")
    arch = "linux-arm64" if arm else "linux-x64"
    return ("node-%s-%s.tar.xz" % (NODE_VERSION, arch),
            "node-%s-%s/bin/node" % (NODE_VERSION, arch), "node")


def folder() -> Path:
    """Where the downloaded Node ends up. Under the same root as the engine."""
    from invisible_core.download import cache_root
    return cache_root() / "node" / NODE_VERSION


def _extract(archive: Path, inner: str, dest: Path) -> None:
    """Pulls ONE file out of the archive. Does not unpack the whole Node package.

    That's 50 MB of headers, npm and documentation we never run; we
    only need one executable.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z, open(dest, "wb") as out:
            with z.open(inner) as src:
                shutil.copyfileobj(src, out)
    else:
        with tarfile.open(archive) as t:
            src = t.extractfile(inner)
            if src is None:
                raise NodeError("%s does not contain %s" % (archive.name, inner))
            with open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    if sys.platform != "win32":
        dest.chmod(0o755)


def _download(progress=None) -> Path:
    from invisible_core.download import (_download_file, _parse_checksums,
                                         _sha256_file)

    archive_name, inner, bin_name = _target()
    dst = folder() / bin_name
    d = folder()
    d.mkdir(parents=True, exist_ok=True)

    # Checksums BEFORE the archive: if the list doesn't download, we don't download
    # an archive either that we could then not verify. An unverified download
    # is not a download that half-succeeded, it's an added risk.
    sums = d / "SHASUMS256.txt"
    _download_file(BASE + "/SHASUMS256.txt", sums)
    expected_all = _parse_checksums(sums.read_text(encoding="utf-8", errors="replace"))
    expected = expected_all.get(archive_name)
    if not expected:
        raise NodeError(
            "SHASUMS256.txt of %s does not list %s. Either the declared version "
            "no longer exists on nodejs.org, or this platform doesn't have an "
            "official build." % (NODE_VERSION, archive_name))

    archive = d / archive_name
    _download_file(BASE + "/" + archive_name, archive, progress=progress)
    got = _sha256_file(archive)
    if got.lower() != expected.lower():
        archive.unlink(missing_ok=True)
        sums.unlink(missing_ok=True)
        raise NodeError(
            "the checksum of %s doesn't match: expected %s, got %s. The archive was "
            "thrown away." % (archive_name, expected[:16], got[:16]))

    try:
        _extract(archive, inner, dst)
    finally:
        # Even when it fails: a half-downloaded archive and an orphaned checksum
        # list are 30 MB of garbage that the next run downloads again
        # anyway. Measured while writing this module's known-bad arm,
        # which left SHASUMS256.txt behind on every rejection.
        archive.unlink(missing_ok=True)
        sums.unlink(missing_ok=True)
    return dst


def node_path(progress=None) -> str:
    """The Node to use. Downloads it if missing.

    The order is declared on purpose, and the two variables aren't the same thing:
    ``INVPW_NODE_PATH`` is ours, ``PLAYWRIGHT_NODEJS_PATH`` exists because
    whoever comes from Playwright already knows it and it would be cruel to ignore it.
    """
    for var in ("INVPW_NODE_PATH", "PLAYWRIGHT_NODEJS_PATH"):
        chosen = os.environ.get(var)
        if chosen:
            if not Path(chosen).is_file():
                raise NodeError("%s points to %s, which is not a file." % (var, chosen))
            return chosen

    _, _, bin_name = _target()
    already = folder() / bin_name
    if already.is_file():
        return str(already)
    return str(_download(progress=progress))
