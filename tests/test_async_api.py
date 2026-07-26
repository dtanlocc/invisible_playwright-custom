"""Constructor-parity tests for the async ``InvisiblePlaywright``.

The async API mirrors the sync launcher (same prefs pipeline, same
profile generation, same proxy handling). The only async-specific
surface is ``__aenter__`` / ``__aexit__`` and an awaitable ``new_page``
patch - both require a real Firefox binary to exercise meaningfully and
are covered by the sync E2E tests via parity arguments.

What we test here without launching a browser: the constructor builds
the same eager Profile, clamps the seed identically, and surfaces pin
validation errors at construction time. These guards keep the async
class from silently drifting away from the sync class as features land.
"""
from __future__ import annotations

import pytest

from invisible_playwright.async_api import InvisiblePlaywright as AsyncIP
from invisible_playwright.launcher import InvisiblePlaywright as SyncIP


@pytest.mark.unit
def test_async_explicit_seed_is_stored():
    ip = AsyncIP(seed=42)
    assert ip.seed == 42


@pytest.mark.unit
def test_async_random_seed_is_positive_int31():
    """Same int31 contract as sync: the C++ side rejects ``seed <= 0`` and
    a 32-bit value risks the high bit looking negative."""
    ip = AsyncIP()
    assert isinstance(ip.seed, int)
    assert 0 < ip.seed < 2**31


@pytest.mark.unit
def test_async_random_seed_varies_across_instances():
    seeds = {AsyncIP().seed for _ in range(5)}
    assert len(seeds) > 1


@pytest.mark.unit
def test_async_profile_built_eagerly_in_constructor():
    """Pin validation must fire before ``__aenter__`` - otherwise a user
    only learns their pin is wrong when the browser launch starts."""
    ip = AsyncIP(seed=42)
    assert ip._profile is not None
    assert ip._profile.seed == 42


@pytest.mark.unit
def test_async_invalid_pin_raises_in_constructor():
    with pytest.raises(ValueError):
        AsyncIP(seed=42, pin={"not_a_real_field": 1})


@pytest.mark.unit
def test_async_and_sync_share_seed_for_same_input():
    """Same seed → identical Profile across the two APIs. Both lean on
    ``generate_profile(seed)``; if they diverge it means one of them
    started doing extra sampling."""
    seed = 12345
    a = AsyncIP(seed=seed)
    s = SyncIP(seed=seed)
    assert a._profile == s._profile


@pytest.mark.unit
def test_async_seed_coerced_from_float():
    """``int(seed)`` truncation - matches sync clamping behaviour."""
    ip = AsyncIP(seed=42.9)
    assert ip.seed == 42


@pytest.mark.unit
def test_async_default_context_kwargs_match_sync():
    """The two ``_default_context_kwargs`` implementations must produce
    the same dict for the same inputs. Guards against the async copy
    drifting away when sync adds new keys."""
    a = AsyncIP(seed=42, timezone="America/New_York", locale="de-DE")
    s = SyncIP(seed=42, timezone="America/New_York", locale="de-DE")
    assert a._default_context_kwargs() == s._default_context_kwargs()


# ── parity with the sync launcher, driven rather than declared ───────────────

def test_the_async_api_stamps_the_session_token_into_the_browser_env():
    """The gap that shipped a "fixed" leak to half the users.

    The Windows process-leak fix went into 0.4.0 and was described as fixed. It
    reached the sync launcher only: this module did not import _reaper at all,
    so the browser tree was never marked, could never be found, and a killed
    runner left eight to twelve browsers behind for every async user. Nothing
    was red - no test enters this context manager, and the file's own docstring
    claimed parity while testing the constructor.

    Asserted on the env the browser would actually receive, because that is the
    only thing the guard can key on.
    """
    from invisible_playwright import _reaper
    from invisible_playwright.async_api import InvisiblePlaywright as Async

    session = Async(seed=42)
    session._session_token = _reaper.SessionToken.mint()
    env = session._build_env({})
    assert env.get(_reaper.TOKEN_VAR) == session._session_token.value, (
        "the async API does not stamp INVPW_SESSION_TOKEN, so the reaper can "
        "never identify its browser tree")


def test_both_apis_declare_the_same_lifetime_machinery():
    """Structural parity, so the next feature cannot land on one side only.

    This is deliberately about NAMES, not behaviour: the behaviour is covered
    by test_reaper.py, and what failed here was that one module simply never
    grew the attributes. A test comparing outputs would have passed on two
    objects that share nothing.
    """
    from invisible_playwright import async_api, launcher

    sync_session = launcher.InvisiblePlaywright(seed=1)
    async_session = async_api.InvisiblePlaywright(seed=1)
    for attr in ("_session_token", "_lifetime_guard", "_bind_process_tree"):
        assert hasattr(sync_session, attr), f"sync lost {attr}"
        assert hasattr(async_session, attr), (
            f"the async API has no {attr}; the two entry points have drifted "
            f"and whichever one a user picked decides whether they are covered")


def test_the_async_teardown_reaps():
    """`__aexit__` must reap, not merely close.

    Driven through the real `_teardown` with a recording guard: every close
    step is individually wrapped in `except: pass`, so a browser that refuses
    to close is swallowed - the reap is the only thing left that can act.
    """
    import asyncio

    from invisible_playwright import _reaper
    from invisible_playwright.async_api import InvisiblePlaywright as Async

    reaped = []

    class Recording(_reaper.NullGuard):
        def reap(self, token, *, timeout: float = 5.0) -> int:
            reaped.append(token.value)
            return 0

    session = Async(seed=7)
    session._session_token = _reaper.SessionToken.mint()
    session._lifetime_guard = Recording()
    expected = session._session_token.value

    asyncio.run(session._teardown())
    assert reaped == [expected], (
        "async teardown did not reap the session's tree")
