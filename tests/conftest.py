import os
import random
import sys
from pathlib import Path

import pytest

from invisible_playwright._fpforge import generate_profile
from invisible_playwright.constants import BINARY_ENTRY_REL


@pytest.fixture
def deterministic_rng():
    """Seeded RNG for reproducible tests."""
    return random.Random(42)


@pytest.fixture
def sample_profile():
    """A Profile generated from seed=42 for reuse across tests."""
    return generate_profile(seed=42)


@pytest.fixture(scope="session")
def firefox_binary():
    """Locate the patched Firefox binary for E2E tests, or skip cleanly.

    Single source of truth for every E2E test (previously each test file had its
    own copy - and three of them silently ignored INVPW_BINARY_PATH, so they kept
    testing whatever was in the cache even when you pointed the suite at a
    specific build: a false-confidence trap). Lookup order:

      1. ``INVPW_BINARY_PATH`` env var - point the whole suite at a local build
         or a freshly-extracted release (this is how the full-suite gate runs).
      2. Cached binary under ``cache_dir_for_version()`` (post ``fetch``).
      3. Skip - we never trigger an implicit multi-hundred-MB network download
         inside a test run.
    """
    env_path = os.environ.get("INVPW_BINARY_PATH")
    if env_path:
        if Path(env_path).exists():
            return env_path
        pytest.skip(f"INVPW_BINARY_PATH={env_path!r} does not exist")

    if sys.platform not in BINARY_ENTRY_REL:
        pytest.skip(f"unsupported platform: {sys.platform}")
    from invisible_playwright.download import cache_dir_for_version
    entry = cache_dir_for_version() / BINARY_ENTRY_REL[sys.platform]
    if not entry.exists():
        pytest.skip(
            "patched Firefox binary not cached and INVPW_BINARY_PATH unset; "
            "set INVPW_BINARY_PATH=<firefox binary> or run `invisible-playwright fetch`"
        )
    return str(entry)
