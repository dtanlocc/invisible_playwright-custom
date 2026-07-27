"""Session logic shared by the sync and async entry points.

WHY THIS FILE EXISTS. There are two `InvisiblePlaywright` classes, and the only
thing keeping them equal was somebody remembering. Measured 2026-07-27: 203 of
252 normalised lines of `async_api.py` also appear in `launcher.py` - 80.6% -
and `__init__`, `_teardown`, `_build_env` and `_default_context_kwargs` are 100%
identical once the word `await` is deleted. So the duplication is not the price
of async; async was the excuse for it.

That is a defect GENERATOR, and it has already produced three:

  * the 0.4.0 process-leak fix reached the sync class only, and shipped to the
    other half of the users under a release note saying it was fixed;
  * `INVPW_TRUE_HEADLESS`, a documented env var, worked on the async API alone;
  * `_build_prefs` was a method on one side and twenty inline lines on the other.

Anything here must stay free of Playwright imports: it is the part that has
nothing to do with which API a caller picked. What legitimately differs between
the two classes is `await`, and nothing else belongs in this file.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

from invisible_core import cloak_prefs, translate_profile_to_prefs

from ._cursor import humanize_prefs as _humanize_prefs

__all__ = ["build_prefs", "true_headless_requested", "TRUE_HEADLESS_ENV"]

#: Opt-in to real headless. The default headful+cloak path intermittently hangs
#: `launch_persistent_context` on Windows (~40%, a window/compositor race with a
#: persistent profile); true headless applies the IDENTICAL fingerprint prefs and
#: is reliable. Read HERE rather than in one of the two classes, because reading
#: it in one of them is exactly how it came to work on the async API only.
TRUE_HEADLESS_ENV = "INVPW_TRUE_HEADLESS"


def true_headless_requested(env: Optional[Dict[str, str]] = None) -> bool:
    return (env if env is not None else os.environ).get(TRUE_HEADLESS_ENV) == "1"


#: IANA -> POSIX TZ. Linux glibc reads IANA names from /usr/share/zoneinfo, but
#: Windows MSVCRT only understands the POSIX form, so the conversion has to
#: happen before `TZ` is set. Common US zones cover the vast majority of
#: residential proxies; anything else falls through to its IANA name.
#:
#: Lived in `launcher.py` until 2026-07-27, which meant `async_api` imported it
#: FROM the sync module - a dependency that exists for no reason other than that
#: is where it was first written. `invisible_core.launch` carries a copy too,
#: with a comment admitting it was "copied verbatim from the wrapper"; folding
#: those two together needs a core release and is tracked separately.
_IANA_TO_POSIX_TZ = {
    "America/New_York":             "EST5EDT",
    "America/Detroit":              "EST5EDT",
    "America/Indiana/Indianapolis": "EST5EDT",
    "America/Kentucky/Louisville":  "EST5EDT",
    "America/Chicago":              "CST6CDT",
    "America/Denver":               "MST7MDT",
    "America/Los_Angeles":          "PST8PDT",
    # Arizona (outside the Navajo Nation) does NOT observe DST. Mapping it to
    # MST7MDT made libc apply DST, so getTimezoneOffset() returned -360 in
    # summer instead of -420, and the identification service deduced a Denver
    # origin - a timezone_mismatch produced by our own conversion table.
    "America/Phoenix":              "MST7",
    "America/Anchorage":            "AKST9AKDT",
    # Hawaii does not observe DST either.
    "Pacific/Honolulu":             "HST10",
}

#: The proxy egress IP fed to nICEr's bridge as the srflx override. An explicit
#: caller-supplied value wins over the one discovered at launch.
WEBRTC_IP_ENV = "STEALTHFOX_WEBRTC_PUBLIC_IP"
WEBRTC_NO_IPV6_ENV = "STEALTHFOX_WEBRTC_DISABLE_IPV6"


def tz_env(timezone: str) -> str:
    """The value to put in ``TZ`` for an IANA zone."""
    return _IANA_TO_POSIX_TZ.get(timezone, timezone)


def build_env(
    *,
    timezone: Optional[str],
    egress_ip: Optional[str],
    base_env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """The environment the Firefox subprocess is launched with, minus the token.

    The session token is stamped by the caller, because it is the one part that
    is genuinely per-session; everything here was written twice, identically,
    in `launcher._build_env` and `async_api._build_env`.

    Fonts need no env: the patched binary is bundle-only and self-contained.
    """
    env = dict(base_env if base_env is not None else os.environ)
    if timezone:
        env["TZ"] = tz_env(timezone)
    # WebRTC srflx override, plus dropping IPv6 from gathering behind a proxy.
    webrtc_ip = env.get(WEBRTC_IP_ENV) or egress_ip
    if webrtc_ip:
        env[WEBRTC_IP_ENV] = webrtc_ip
        env[WEBRTC_NO_IPV6_ENV] = "1"
    return env


def build_prefs(
    *,
    profile: Any,
    locale: Optional[str],
    timezone: Optional[str],
    extra_prefs: Optional[Dict[str, Any]],
    headless: bool,
    cursor_engine: str,
    humanize: Any,
) -> Dict[str, Any]:
    """Fingerprint prefs plus the humanize toggle, which is always set explicitly.

    Takes values rather than a session object so it stays callable from a test
    without constructing either class - and so that adding a field to one class
    cannot silently change what the other one builds.
    """
    prefs = translate_profile_to_prefs(
        profile,
        locale=locale,
        timezone=timezone,
        extra_prefs=extra_prefs,
        virtual_display=bool(headless and sys.platform == "win32"),
    )
    # Windows and macOS hide the headless window through the binary's own cloak
    # (DWMWA_CLOAK / NSWindow alpha), so the pref has to reach the build.
    # setdefault: an explicit user override wins.
    if headless and sys.platform in ("win32", "darwin"):
        for key, value in cloak_prefs().items():
            prefs.setdefault(key, value)
    # The namespace MUST be stealthfox.* - that is what the binary's Juggler
    # reads, and it gates its own mouse-path expansion on `stealthfox.humanize`.
    # An earlier `invisible_playwright.*` spelling was a dead no-op, so humanize
    # never fired and every click teleported the cursor.
    #
    # The pref selects WHICH generator runs, not whether motion happens. While
    # the wrapper draws the path it must be false, or each waypoint we send would
    # itself be expanded into a whole path by the browser.
    prefs.update(_humanize_prefs(cursor_engine, humanize))
    return prefs
