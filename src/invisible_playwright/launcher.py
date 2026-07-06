"""Sync Playwright launcher for invisible_playwright."""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any, Dict, Optional, Union

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright

from ._fpforge import Profile, generate_profile
from ._webgl_personas import forced_gpu_class
from ._geo import prepare_session_geo
from ._headless import cloak_prefs, make_virtual_display
from ._proxy import configure_proxy as _configure_proxy_shared
from .download import ensure_binary
from .prefs import translate_profile_to_prefs


def _patch_sync_new_page_sleep(ctx: Any) -> None:
    """Wrap ctx.new_page() to add a brief settle after tab creation.

    FF150 with Fission emits an about:newtab navigation ~100ms after a tab
    is created.  If goto() is called immediately, it races with that internal
    navigation and raises "Navigation interrupted by about:newtab".  A short
    sleep breaks the race without requiring every call-site to know about it.
    """
    import time as _time
    original_new_page = ctx.new_page

    def patched_new_page(**kw):
        page = original_new_page(**kw)
        _time.sleep(0.4)
        return page

    ctx.new_page = patched_new_page  # type: ignore[assignment]


# Window-chrome and taskbar offsets measured empirically on a headed
# Firefox 150 (no compositor). Used to derive the default new_context
# viewport so it fits inside the spoofed screen without out-of-bounds.
_CHROME_W  = 14
_CHROME_H  = 91
_TASKBAR_H = 40

# IANA → POSIX TZ mapping. Linux glibc accepts IANA names directly via
# /usr/share/zoneinfo, but Windows MSVCRT only understands the POSIX form
# ("EST5EDT") — convert here so ``TZ`` works on both platforms when the
# binary runs on Windows. Common US zones cover the vast majority of
# residential proxies; everything else falls through to its IANA name.
_IANA_TO_POSIX_TZ = {
    "America/New_York":            "EST5EDT",
    "America/Detroit":              "EST5EDT",
    "America/Indiana/Indianapolis": "EST5EDT",
    "America/Kentucky/Louisville":  "EST5EDT",
    "America/Chicago":              "CST6CDT",
    "America/Denver":               "MST7MDT",
    "America/Los_Angeles":          "PST8PDT",
    # Arizona (except Navajo Nation) does NOT observe DST. Mapping it to
    # MST7MDT made libc apply DST → Date.getTimezoneOffset() returned -360
    # in summer (Denver-like) instead of -420 (true Phoenix), and FP Pro
    # deduced vpn_origin_timezone="America/Denver" → timezone_mismatch.
    "America/Phoenix":              "MST7",
    "America/Anchorage":            "AKST9AKDT",
    # Hawaii does not observe DST.
    "Pacific/Honolulu":             "HST10",
}


def _tz_env(timezone: str) -> str:
    """Return the value to set in ``TZ`` for the given IANA zone."""
    return _IANA_TO_POSIX_TZ.get(timezone, timezone)


class InvisiblePlaywright:
    """Context manager launching a patched Firefox with a deterministic profile.

    Usage:

        from invisible_playwright import InvisiblePlaywright

        # random seed (different fingerprint each call)
        with InvisiblePlaywright() as browser:
            page = browser.new_page()
            page.goto("https://example.com")

        # explicit seed → same profile every time
        with InvisiblePlaywright(seed=42) as browser:
            ...

        # human-like cursor motion (Bezier trajectory on every mousemove)
        with InvisiblePlaywright(humanize=True) as browser:
            ...

    Optional ``pin`` forces specific fingerprint fields while the rest still
    varies with ``seed``::

        with InvisiblePlaywright(seed=42, pin={"screen.width": 2560}) as browser:
            ...

    After construction, the chosen seed is available as ``self.seed`` — useful
    to reproduce a random run later.
    """

    def __init__(
        self,
        seed: Optional[int] = None,
        *,
        pin: Optional[Dict[str, Any]] = None,
        headless: bool = False,
        proxy: Optional[Dict[str, str]] = None,
        extra_args: Optional[list[str]] = None,
        humanize: Union[bool, float] = True,
        locale: str = "auto",
        timezone: str = "",
        extra_prefs: Optional[Dict[str, Any]] = None,
        binary_path: Optional[str] = None,
        profile_dir: Optional[Union[str, Path]] = None,
        prep_recaptcha: bool = False,
    ) -> None:
        """
        Args:
            seed: Integer seed driving the Bayesian fingerprint sampler.
                Same seed → same fingerprint. ``None`` = fresh random.
            pin: Force specific fingerprint fields (see docs/pinning.md).
            headless: When ``True``, browser renders on a hidden virtual
                display (Xvfb on Linux, ``CreateDesktop`` on Windows) so
                Firefox stays in *headed* mode (real rendering pipeline,
                coherent fingerprint) without showing windows.
            proxy: ``{"server": "...", "username": "...", "password": "..."}``.
                ``socks5://`` / ``socks4://`` go through the patched
                ``nsProtocolProxyService``; ``http(s)://`` go through
                Playwright's own ``proxy=`` kwarg.
            extra_args: Extra command-line args forwarded to Firefox.
            humanize: Every mouse move is expanded by the patched Juggler
                into a Bezier trajectory with ~10 ms between waypoints.
                Default ``True`` (~1.5 s max motion). ``False`` disables;
                a float caps the motion in seconds.
            locale: BCP-47 tag (e.g. ``"en-US"``) or ``"auto"`` (default).
                ``"auto"`` derives the locale from the egress country — the proxy
                egress IP, or the host's public IP without a proxy — exactly like
                ``timezone="auto"``, keeping the browser language consistent with the
                exit country (a French proxy → ``fr-FR``). Drives
                ``intl.accept_languages`` → both ``navigator.language``/``languages``
                AND the q-valued ``Accept-Language`` header (the patched binary builds
                the header from the pref, never from the raw Playwright locale override,
                so the two never diverge — see nsHttpHandler STEALTHFOX note).
            timezone: IANA zone (e.g. ``"America/New_York"``) — used as-is
                when set, the only way to force a specific zone. ``""``
                (default) or ``"auto"`` ALWAYS resolves from the egress IP:
                through the proxy when one is set, otherwise from the host's
                own public IP (one lookup + an offline mmdb). On failure: with
                a proxy it raises (a foreign proxy on the host TZ is the
                ``timezone_mismatch`` signal); without a proxy it falls back to
                the host TZ so a transient lookup failure can't break launch.
            extra_prefs: Optional dict of Firefox prefs overlayed on top
                of the generated profile — useful for niche tweaks
                without monkey-patching the package.
            profile_dir: Path to a persistent Firefox profile directory.
                When set, the session uses ``launch_persistent_context()``
                so cookies, localStorage, sessionStorage, extensions, cache
                and prefs are kept on disk between runs. ``__enter__``
                returns a ``BrowserContext`` (not a ``Browser``) — use it
                directly: ``with InvisiblePlaywright(profile_dir=p) as ctx:
                page = ctx.new_page()``. First run creates the dir;
                subsequent runs reuse it. Pair with a stable ``seed=`` to
                also pin the fingerprint identity across runs.
        """
        # Constrain to int31 — Firefox's `zoom.stealth.fpp.hw_seed` and
        # related stealth prefs are declared as ``int32_t`` in
        # ``StaticPrefList.yaml``. A 32-bit seed risks the high bit being
        # interpreted as negative on the C++ side, where the noise hooks
        # bail out on ``seed <= 0`` — which produces bit-identical audio
        # / canvas fingerprints across half the sessions.
        self.seed: int = int(seed) if seed is not None else secrets.randbits(31)
        self._pin = pin
        self._headless = headless
        self._proxy = proxy
        self._extra_args = list(extra_args or [])
        self._humanize = humanize
        self._locale = locale
        self._timezone = timezone
        self._extra_prefs = extra_prefs
        self._binary_path = binary_path
        self._profile_dir: Optional[Path] = Path(profile_dir) if profile_dir else None
        # reCAPTCHA cookie pre-seed — opt-in. Gated server-side: if a
        # persistent profile_dir is in use, respect its existing cookies
        # and DON'T enable pre-seed (the profile owns its own state).
        self._prep_recaptcha = bool(prep_recaptcha) and self._profile_dir is None
        self._profile: Profile = generate_profile(
            self.seed, pin=self._pin, fixed_gpu_class=forced_gpu_class(self.seed)
        )
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._persistent_context: Optional[BrowserContext] = None
        self._virtual_display: Any = None
        # Proxy egress IP, discovered at launch (see __enter__). Feeds the
        # WebRTC srflx override so the candidate matches the proxy IP, not the
        # real host IP. None when no proxy is set.
        self._webrtc_egress_ip: Optional[str] = None

    def __enter__(self) -> Union[Browser, BrowserContext]:
        # Resolve timezone="auto" (and the proxy-set-but-unset default) to a
        # concrete IANA zone AND discover the proxy egress IP — one round-trip,
        # before anything reads self._timezone or builds prefs/env. Fail-early
        # if a proxy is set but the egress can't be resolved.
        _geo = prepare_session_geo(self._timezone, self._proxy)
        self._timezone = _geo.timezone
        self._webrtc_egress_ip = _geo.egress_ip
        # Geo-aware locale: "auto" derives the language from the egress country (reusing
        # the egress IP already discovered above), like timezone="auto". Keeps the browser
        # language consistent with the proxy's country instead of a fixed en-US.
        if (self._locale or "").strip().lower() == "auto":
            from ._geo import resolve_session_locale
            self._locale = resolve_session_locale(_geo.egress_ip, self._proxy)
        executable = self._binary_path or ensure_binary()
        prefs = self._build_prefs()
        playwright_proxy = _configure_proxy_shared(self._proxy, prefs)
        pw_headless = self._resolve_headless()
        env = self._build_env(prefs)

        try:
            self._pw = sync_playwright().start()
            if self._profile_dir is not None:
                # Persistent context — cookies / localStorage / extensions /
                # prefs all live on disk between runs. Stealth prefs are
                # re-injected via firefox_user_prefs on every launch (Playwright
                # writes them to user.js, which overrides anything in
                # prefs.js inside the persistent dir).
                self._profile_dir.mkdir(parents=True, exist_ok=True)
                self._persistent_context = self._pw.firefox.launch_persistent_context(
                    user_data_dir=str(self._profile_dir),
                    executable_path=str(executable),
                    headless=pw_headless,
                    firefox_user_prefs=prefs,
                    proxy=playwright_proxy,
                    args=self._extra_args,
                    env=env,
                    **self._persistent_context_kwargs(),
                )
                _patch_sync_new_page_sleep(self._persistent_context)
                return self._persistent_context
            self._browser = self._pw.firefox.launch(
                executable_path=str(executable),
                headless=pw_headless,
                firefox_user_prefs=prefs,
                proxy=playwright_proxy,
                args=self._extra_args,
                env=env,
            )
        except BaseException:
            # Python doesn't call __exit__ when __enter__ raises — clean up
            # the virtual display + Playwright manually so we don't leak Xvfb
            # / desktop handles into the user's process.
            self._teardown()
            raise
        self._patch_new_context_defaults(self._browser)
        return self._browser

    def _persistent_context_kwargs(self) -> Dict[str, Any]:
        """Context-level kwargs accepted by launch_persistent_context.

        Identical to ``_default_context_kwargs``: viewport / screen / DPR /
        color-scheme / locale / timezone_id. Up to firefox-4 we had to drop
        locale and timezone_id because Playwright's per-realm overrides
        called IDL methods (``docShell.languageOverride``,
        ``docShell.overrideTimezone``) that weren't exposed by our patched
        build, causing launch_persistent_context to hang for 180s. From
        firefox-5 (C7 chiusura), the C++ ``overrideTimezone`` method is
        present and ``languageOverride`` was already there, so the
        per-realm overrides land and the persistent context starts in
        ~20s like the non-persistent path.
        """
        return self._default_context_kwargs()

    def _patch_new_context_defaults(self, browser: Browser) -> None:
        """Wrap ``browser.new_context`` so its defaults derive from the
        profile (viewport, screen, DPR, color-scheme). Users get a
        coherent context for free; explicit kwargs still override.
        """
        original = browser.new_context
        defaults = self._default_context_kwargs()
        prep = self._prep_recaptcha
        profile = self._profile  # pass the whole Profile (seed + browsing_history)
        tz = self._timezone  # used by _recaptcha_seed for CONSENT lang+region

        def patched(**kw):
            merged = dict(defaults)
            merged.update(kw)  # user-supplied wins
            ctx = original(**merged)
            _patch_sync_new_page_sleep(ctx)
            if prep:
                from ._recaptcha_seed import seed_recaptcha_cookies_sync
                seed_recaptcha_cookies_sync(ctx, profile, timezone=tz)
            return ctx

        browser.new_context = patched  # type: ignore[assignment]

    def _default_context_kwargs(self) -> Dict[str, Any]:
        p = self._profile
        kwargs: Dict[str, Any] = {
            "viewport":            {"width":  p.screen.width  - _CHROME_W,
                                     "height": p.screen.height - _TASKBAR_H - _CHROME_H},
            "screen":              {"width": p.screen.width, "height": p.screen.height},
            "device_scale_factor": p.screen.dpr,
            "color_scheme":        "dark" if p.dark_theme else "light",
        }
        # Pass timezone via Playwright's per-realm override (docShell.overrideTimezone
        # → JS::SetRealmTimezoneOverride). The juggler.timezone.override pref path
        # uses JS::SetTimeZoneOverride globally, which is broken on Windows ICU for
        # no-DST IANA names (America/Phoenix, Pacific/Honolulu, ...) — those silently
        # fall back to the host system TZ. The per-realm path works for every zone.
        if self._timezone:
            kwargs["timezone_id"] = self._timezone
        if self._locale:
            kwargs["locale"] = self._locale
        return kwargs

    def __exit__(self, *exc: Any) -> None:
        self._teardown()

    def _teardown(self) -> None:
        if self._persistent_context is not None:
            try:
                self._persistent_context.close()
            except Exception:
                pass
            self._persistent_context = None
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None
        if self._virtual_display is not None:
            try:
                self._virtual_display.stop()
            except Exception:
                pass
            self._virtual_display = None

    # ── helpers ─────────────────────────────────────────────────────────

    def _build_prefs(self) -> Dict[str, Any]:
        """Fingerprint prefs plus humanize toggle (always set explicitly)."""
        import sys as _sys
        prefs = translate_profile_to_prefs(
            self._profile,
            locale=self._locale,
            timezone=self._timezone,
            extra_prefs=self._extra_prefs,
            virtual_display=bool(self._headless and _sys.platform == "win32"),
        )
        # Windows & macOS hide the headless window via the binary's own cloak
        # (DWMWA_CLOAK / NSWindow alpha) — inject the pref so the patched build
        # cloaks its chrome windows. setdefault: an explicit user override wins.
        if self._headless and _sys.platform in ("win32", "darwin"):
            for _k, _v in cloak_prefs().items():
                prefs.setdefault(_k, _v)
        # Pref namespace MUST be stealthfox.* — that's what the binary's Juggler
        # reads (PageHandler.js gates the Bezier mouse path on `stealthfox.humanize`).
        # The old `invisible_playwright.*` name was a dead no-op (nothing read it), so
        # humanize silently never fired and every click teleported the cursor.
        prefs["stealthfox.humanize"] = bool(self._humanize)
        if self._humanize:
            prefs["stealthfox.humanize.maxTime"] = str(self._humanize_max_seconds())
        return prefs

    def _build_env(self, prefs: Dict[str, Any]) -> Dict[str, str]:
        """Env vars passed to the Firefox subprocess.

        ``TZ`` tunes the libc clock the content process reads for
        ``Date`` / ``Intl.DateTimeFormat`` so the JS-visible timezone
        matches ``self._timezone`` regardless of the host TZ.
        ``STEALTHFOX_WEBRTC_PUBLIC_IP`` is propagated when the calling
        process has set it — read by nICEr's nr_stealth_bridge to inject
        a synthetic srflx candidate matching the proxy egress IP, avoiding
        the StaticPref IPC propagation timing issue between parent and
        socket processes.
        Fonts need NO env: the patched binary is self-contained (always
        bundle-only, exposing exactly the bundled standard-Windows families;
        system-ui + generics baked in C++). No external font list / allow-list.
        """
        import os as _os
        env = _os.environ.copy()
        if self._timezone:
            env["TZ"] = _tz_env(self._timezone)
        # WebRTC srflx override: feed nICEr's nr_stealth_bridge the proxy egress
        # IP so the srflx candidate matches the proxy (not the real host the
        # UDP STUN would otherwise leak). An explicit env var set by the caller
        # wins; otherwise we use the egress IP auto-discovered in __enter__.
        # Behind a proxy we also drop IPv6 from gathering (the disableIPv6 pref
        # is dead on FF150 — the bridge filter is the real switch).
        webrtc_ip = (
            _os.environ.get("STEALTHFOX_WEBRTC_PUBLIC_IP")
            or self._webrtc_egress_ip
        )
        if webrtc_ip:
            env["STEALTHFOX_WEBRTC_PUBLIC_IP"] = webrtc_ip
            env["STEALTHFOX_WEBRTC_DISABLE_IPV6"] = "1"
        return env

    def _resolve_headless(self) -> bool:
        """Translate the user's ``headless`` flag.

        When ``True``, Firefox stays in headed mode (real rendering pipeline →
        coherent fingerprint) and the window is hidden: on Linux via a fresh
        Xvfb spawned here; on Windows/macOS via the binary's own window cloak
        (the ``zoom.stealth.cloak_windows`` pref added in ``_build_prefs``), so
        ``make_virtual_display()`` returns ``None`` and nothing is spawned.
        """
        if not self._headless:
            return False
        vd = make_virtual_display()
        if vd is not None:
            vd.start()
            self._virtual_display = vd
        return False

    def _humanize_max_seconds(self) -> float:
        if self._humanize is True:
            return 1.5
        return float(self._humanize)

