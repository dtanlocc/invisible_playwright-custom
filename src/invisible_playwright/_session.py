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

from invisible_core import compose_session_prefs
from invisible_core.launch import (FontManifestMismatch,
                                   cached_font_manifest_path,
                                   verify_font_manifest)

from ._cursor import (
    ENGINE_BINARY,
    max_seconds_for as _cursor_max_seconds,
)

__all__ = ["build_prefs", "true_headless_requested", "TRUE_HEADLESS_ENV",
           "ProxyEgressDrifted", "egress_ancora_valido"]

#: Opt-in to real headless. Read HERE rather than in one of the two classes,
#: because reading it in one of them is exactly how it came to work on the async
#: API only.
#:
#: ⛔ THE REASON THIS USED TO BE A WORKAROUND IS NOW KNOWN, AND FIXED. This
#: comment said: "the default headful+cloak path intermittently hangs
#: launch_persistent_context on Windows (~40%, a window/compositor race with a
#: persistent profile); true headless ... is reliable". It had the right
#: neighbourhood - window and compositor - and no mechanism, so it stood as an
#: escape hatch for months.
#:
#: The mechanism, measured 2026-08-14: Windows declared the chrome window FULLY
#: OCCLUDED and in the hanging runs the verdict was never revoked
#: (`nsWindow::NotifyOcclusionState() mIsFullyOccluded 1` with no later 0). An
#: inactive BrowsingContext never paints, so delayed startup never finishes,
#: `browser-delayed-startup-finished` never fires, no target is created and the
#: launch times out at 180 s. True headless was reliable for a reason nobody had
#: named: there is no window to occlude.
#:
#: Fixed by `widget.windows.window_occlusion_tracking.enabled=false`, applied to
#: EVERY session by invisible_core - 24 relaunches out of 24 against 6 hangs in 9.
#: So this variable is no longer a workaround for that hang; it remains as a
#: deliberate choice of a different rendering path. Full account:
#: `71-bug-archive.md` [B150].
TRUE_HEADLESS_ENV = "INVPW_TRUE_HEADLESS"


def true_headless_requested(env: Optional[Dict[str, str]] = None) -> bool:
    return (env if env is not None else os.environ).get(TRUE_HEADLESS_ENV) == "1"


#: The IANA -> POSIX conversion comes from the core, which is where the table
#: lives. It was duplicated here byte-for-byte - ten entries, including the
#: Phoenix row that exists because mapping Arizona to MST7MDT made libc apply
#: DST and an identification service deduce a Denver origin. The core's own
#: comment admitted its copy had been "copied verbatim from the wrapper", so
#: the two had a documented keep-in-sync obligation and nothing enforcing it.
#: `tz_env` was made public in the core for exactly this reason. (No version
#: number here on purpose: the pin lives in pyproject.toml and a test
#: forbids a second copy of it anywhere in src/, prose included.)
#
#: GUARDED, because an import that fails must say WHY. Taking these names
#: unguarded meant that an environment holding an older core died with
#: `ImportError: cannot import name 'IANA_TO_POSIX_TZ' from 'invisible_core'` -
#: a message about a symbol, from a package the user did not choose the version
#: of, on the browser launch path. The pin machinery exists to explain exactly
#: this, and a bare module-level import walks straight past it. Reported by a
#: user within minutes of the change.
try:
    from invisible_core import (  # noqa: F401 - the import IS the probe
        IANA_TO_POSIX_TZ as _IANA_TO_POSIX_TZ,
        tz_env,
    )
except ImportError as _exc:  # pragma: no cover - exercised by the old-core probe
    from ._pin import declared_core_pin as _declared_core_pin

    try:
        _want = _declared_core_pin() or "a newer version"
    except Exception:
        _want = "a newer version"
    raise ImportError(
        f"invisible-playwright needs invisible-core {_want}: the installed one "
        f"does not provide the timezone conversion this version imports "
        f"({_exc}). Upgrade with `pip install -U invisible-playwright`, which "
        f"pulls the core it was built against."
    ) from _exc

#: The proxy egress IP fed to nICEr's bridge as the srflx override. An explicit
#: caller-supplied value wins over the one discovered at launch.
WEBRTC_IP_ENV = "STEALTHFOX_WEBRTC_PUBLIC_IP"
WEBRTC_NO_IPV6_ENV = "STEALTHFOX_WEBRTC_DISABLE_IPV6"


#: The engine reads this at startup; see build_env for why a pref cannot
#: work here. Never rename: it is part of the binary contract.
FONT_MANIFEST_ENV = "STEALTHFOX_FONT_MANIFEST"


def build_env(
    *,
    timezone: Optional[str],
    #: The address to DECLARE as srflx, or None to declare nothing and let the
    #: real one through. ⛔ This is NOT the egress IP: it is a DECISION the
    #: core makes in a single place, looking at the capabilities of the egress
    #: (`SessionGeo.srflx_da_dichiarare`). The old name, `egress_ip`, said
    #: something else and made the rule look like "there's a proxy -> declare
    #: it", which is the wrong question.
    srflx_dichiarato: Optional[str],
    profile: Any = None,
    executable: Optional[str] = None,
    base_env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """The environment the Firefox subprocess is launched with, minus the token.

    The session token is stamped by the caller, because it is the one part that
    is genuinely per-session; everything here was written twice, identically,
    in `launcher._build_env` and `async_api._build_env`.

    Fonts DO need an env, and only an env will do. The engine builds its font
    list during app startup, inside InitSharedFontListForPlatform, and on this
    path the prefs never reach the profile at all - Playwright sends them over
    the wire and JS applies them once the browser is already running. Measured
    2026-08-08: the pref of the same name always read empty there, so the
    engine's packaged copy won and the manifest this package declares was
    inert. An environment variable is set at process creation and inherited by
    every content process.

    `profile=None` sets nothing, which leaves the engine on its own copy - the
    floor that keeps a browser launched without this package rendering.
    """
    env = dict(base_env if base_env is not None else os.environ)
    if timezone:
        env["TZ"] = tz_env(timezone)
    manifest = getattr(getattr(profile, "font", None), "manifest", "")
    if manifest:
        # Refuse rather than hand the engine metrics for faces it does not
        # carry. That failure is not an error at runtime - it is a page laid
        # out a few pixels wrong, which nothing observes. A browser that will
        # not start is at least loud, and the engine still has its own copy to
        # fall back to if this variable is simply absent.
        if executable:
            missing = verify_font_manifest(manifest, executable)
            # `None` means the engine has no fonts/ beside it, so there was
            # nothing to check against - not that the check passed. Proceeding
            # is right anyway: an engine with no bundled fonts cannot be made
            # worse by a manifest naming files it does not have either way, and
            # refusing would reject every layout that is not ours.
            if missing:
                raise FontManifestMismatch(
                    f"the font manifest this package declares names "
                    f"{len(missing)} face file(s) the engine does not carry "
                    f"(e.g. {missing[:3]}). Engine: {executable}. The metrics "
                    f"would describe fonts that are not there.")
        path = cached_font_manifest_path(manifest)
        if path is not None:
            # setdefault: an already-set value wins, same rule as the WebRTC IP.
            env.setdefault(FONT_MANIFEST_ENV, str(path))
    # WebRTC srflx override, plus dropping IPv6 from gathering.
    webrtc_ip = env.get(WEBRTC_IP_ENV) or srflx_dichiarato
    if webrtc_ip:
        env[WEBRTC_IP_ENV] = webrtc_ip
        # ONLY behind a proxy, and the reason is a measurement.
        #
        # A retail Firefox on a dual-stack connection emits an IPv6 srflx with
        # the REAL global address, in the clear: mDNS obfuscation only covers
        # host candidates. Behind an IPv4 proxy that address would be a leak
        # and, worse, an inconsistency - HTTP goes out through the proxy and
        # WebRTC shows home. So there the filter is needed.
        #
        # Without a proxy it protects against NOTHING and costs form: measured
        # on 2026-08-25 against the retail install on the same connection, the
        # retail emits 6 candidates (host UDP x2, host TCP x2, srflx v4, srflx
        # v6) while we were emitting 3. We looked like an IPv4-only machine
        # where the reference is dual-stack.
        #
        # Before today this `if` was not involved: the filter was always
        # turned on by the pref `zoom.stealth.webrtc.disable_ipv6`, which the
        # environment only overrode. With the second source removed, the
        # condition became expressible in one line.
        env[WEBRTC_NO_IPV6_ENV] = "1"
    return env


def build_prefs(
    *,
    profile: Any,
    locale: Optional[str],
    timezone: Optional[str],
    extra_prefs: Optional[Dict[str, Any]],
    headless: bool,
    virtual_display: bool,
    cursor_engine: str,
    humanize: Any,
    show_cursor: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fingerprint prefs plus the humanize toggle, which is always set explicitly.

    Takes values rather than a session object so it stays callable from a test
    without constructing either class - and so that adding a field to one class
    cannot silently change what the other one builds.
    """
    # The core composes it. This was the third of
    # three places that stacked layers on top of translate_profile_to_prefs in
    # its own order, and nothing compared the results: the one in
    # get_default_stealth_prefs never called configure_proxy at all, so a caller
    # driving Playwright themselves with a SOCKS endpoint got no network.proxy.*
    # pref and went out on the host's own address.
    #
    # What stays here is this path's DELIVERY and its two decisions:
    #
    #   cloak      Windows and macOS hide the headless window through the
    #              binary's own cloak (DWMWA_CLOAK / NSWindow alpha), so the
    #              pref has to reach the build. The composer applies it with
    #              setdefault, which is the precedence it had here: an explicit
    #              user override wins.
    #   humanize   The pref selects WHICH generator runs, not whether motion
    #              happens. While the wrapper draws the path it must be false,
    #              or every waypoint we send would itself be expanded into a
    #              path by the browser. `max_seconds_for` is applied HERE rather
    #              than passing `humanize` through, because a falsy-but-numeric
    #              cap with the binary engine selected has to mean the default,
    #              not "off".
    #   show_cursor  Passed through UNTRANSLATED, and that is the difference
    #              from the line above: `humanize` needs a decision here
    #              because two engines compete for it, while the visible dot
    #              has exactly one meaning and the core owns it. Anything this
    #              function computed about it would be a second place that
    #              knows, which is the defect the paragraph above is about.
    #
    # The namespace MUST be stealthfox.* - that is what the binary's Juggler
    # reads. An earlier `invisible_playwright.*` spelling was a dead no-op, so
    # humanize never fired and every click teleported the cursor.
    return compose_session_prefs(
        profile,
        locale=locale,
        timezone=timezone,
        extra_prefs=extra_prefs,
        # The REAL value, not a guess: B172, 2026-08-24. The caller
        # passes the actual result of make_virtual_display() - if it
        # created nothing (always the case on Windows, where the cloak
        # has replaced the alternate desktop), this is False here, and
        # the sandbox workarounds meant for that desktop do not apply.
        virtual_display=virtual_display,
        cloak=bool(headless and sys.platform in ("win32", "darwin")),
        humanize=(_cursor_max_seconds(humanize)
                  if cursor_engine == ENGINE_BINARY else False),
        show_cursor=show_cursor,
    ).prefs


class ProxyEgressDrifted(RuntimeError):
    """The egress IP changed MID-SESSION.

    This is not a condition the product can recover from, and it is deliberate
    that it is an error instead of a silent update.

    The IP we declare to the engine for the WebRTC srflx candidate is
    discovered ONCE, at launch. If the egress changes afterwards, the page
    exits from one address and WebRTC announces another: it is exactly the
    comparison detectors make ("WebRTC IP doesn't match your Remote IP"), and
    no Firefox on a real connection produces it.

    Updating the value on the fly would be worse, not better: the site would
    see the WebRTC IP change before its own eyes mid-session, which is just as
    unnatural a signal. If the egress does not hold for the duration of the
    session, that proxy is not sticky and is not usable for this purpose.

    Measured on 2026-08-25: the two providers tried both declare sessions
    sticky by TIME (60 minutes at most for one, a sliding timeout for the
    other, which decays even earlier if the residential peer disconnects), so
    on a long enough session the drift is not a risk: it is a certainty.
    """


class ProxyEgressNonVerificabile(RuntimeError):
    """The egress could not be MEASURED, repeatedly.

    This is not drift and it is not parity: it is absence of measurement. A
    proxy that does not answer the probe for several checks in a row is not a
    proxy that holds, it is a proxy we are flying blind on while the engine
    keeps declaring to every page an address that nobody is confirming any
    more.
    """


#: The three outcomes of the check. There are THREE and not two on purpose:
#: see why in the docstring of `egress_ancora_valido`.
USCITA_REGGE = "regge"
USCITA_DERIVATA = "derivata"
USCITA_NON_MISURABILE = "non_misurabile"


def egress_ancora_valido(proxy: Optional[Dict[str, str]],
                         atteso: Optional[str],
                         *, timeout: int = 20) -> "tuple[str, Optional[str]]":
    """(outcome, current_ip), with outcome among the three `USCITA_*`.

    ⛔ THERE ARE THREE OUTCOMES BECAUSE TWO LIE. Until 2026-08-25 this function
    returned `(True, None)` when the probe FAILED, with a comment that argued
    the right half of the thing well - "a failed discovery is not a drift",
    and that is true, a network problem is not turned into an accusation
    against the proxy. But the returned value said `regge` (holds), i.e. it
    **asserted parity on the basis of a measurement that had not taken
    place**.

    It is the same class of defect this project has already paid for twice
    and fixed twice:

    - `fppro_consistency.py` printed CONSISTENCY PASS when `visitor_id` was
      mute in BOTH runs, because two `None`s come out identical. It has had a
      third outcome since 2026-08-15, exit code 2 = NOT INTERPRETABLE.
    - `repair_core` set `verdict = None` under a handler that said "a broken
      probe is not a licence", above a test `verdict is not None` that then
      let the reinstall proceed.

    The caller now distinguishes: on `USCITA_DERIVATA` it refuses right away,
    on `USCITA_NON_MISURABILE` it counts and refuses only if it repeats,
    because a probe that fails once is the network and one that always fails
    is blindness.

    The case with no proxy or no expected value stays `USCITA_REGGE`, and it
    is different from the other two: there is nothing to betray there, no
    measurement was missed.
    """
    if not proxy or not atteso:
        return USCITA_REGGE, None
    from invisible_core import _geo
    try:
        attuale = _geo.discover_egress_ip(proxy, timeout=timeout)
    except Exception:
        return USCITA_NON_MISURABILE, None
    return (USCITA_REGGE if attuale == atteso else USCITA_DERIVATA), attuale
