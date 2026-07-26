"""Async Playwright façade - mirrors sync_api but with async/await."""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Any, Dict, Optional, Union

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from ._cursor import (
    ENGINE_PYTHON,
    enable_for as _enable_cursor_engine,
    humanize_prefs as _humanize_prefs,
    max_seconds_for as _cursor_max_seconds,
    resolve_cursor_engine,
)
from ._fpforge import Profile, generate_profile
from ._webgl_personas import forced_gpu_class
from ._geo import prepare_session_geo
from ._headless import cloak_prefs, make_virtual_display
from ._engine import assert_wire_version, resolve_executable
from ._proxy import configure_proxy as _configure_proxy_shared
from ._reaper import SessionToken, guard_for
from .launcher import _CHROME_H, _CHROME_W, _TASKBAR_H, _tz_env
from .prefs import translate_profile_to_prefs


def _patch_new_page_sleep(ctx: Any) -> None:
    """Wrap ctx.new_page() to add a brief settle after tab creation.

    FF150 with Fission emits an about:newtab navigation ~100ms after a tab
    is created.  If goto() is called immediately, it races with that internal
    navigation and raises "Navigation interrupted by about:newtab".  A short
    sleep breaks the race without requiring every call-site to know about it.
    """
    original_new_page = ctx.new_page

    async def patched_new_page(**kw):
        page = await original_new_page(**kw)
        await asyncio.sleep(0.4)
        return page

    ctx.new_page = patched_new_page  # type: ignore[assignment]


class InvisiblePlaywright:
    """Async context manager - see invisible_playwright.InvisiblePlaywright for the sync variant."""

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
        # See sync launcher: `zoom.stealth.fpp.hw_seed` is int32_t - clamp.
        self.seed: int = int(seed) if seed is not None else secrets.randbits(31)
        self._pin = pin
        self._headless = headless
        self._proxy = proxy
        self._extra_args = list(extra_args or [])
        self._humanize = humanize
        # See the sync launcher: who draws the cursor path (this package by
        # default, the browser under INVPW_CURSOR_ENGINE=binary, nobody when
        # humanize is falsy). Decided here because the prefs depend on it.
        self._cursor_engine = resolve_cursor_engine(humanize)
        self._locale = locale
        self._timezone = timezone
        self._extra_prefs = extra_prefs
        self._binary_path = binary_path
        self._profile_dir: Optional[Path] = Path(profile_dir) if profile_dir else None
        # reCAPTCHA pre-seed gated server-side; respect persistent profile.
        self._prep_recaptcha = bool(prep_recaptcha) and self._profile_dir is None
        self._profile: Profile = generate_profile(
            self.seed, pin=self._pin, fixed_gpu_class=forced_gpu_class(self.seed)
        )
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._persistent_context: Optional[BrowserContext] = None
        self._virtual_display: Any = None
        # Identity for this session's browser tree, and the guard that ties it
        # to this process's lifetime. Declared here rather than in __aenter__ so
        # _teardown - which runs on the failure path too - always finds them.
        #
        # THIS WAS MISSING ENTIRELY until 2026-07-26. The Windows process-leak
        # fix shipped in 0.4.0 and was described as fixed; it went to the sync
        # launcher only. Every async user kept the whole leak - a killed runner
        # left eight to twelve browsers behind - while the release notes said
        # otherwise. Nothing was red because no test enters this context manager.
        self._session_token = SessionToken()
        self._lifetime_guard = guard_for()
        # Proxy egress IP (WebRTC srflx override); discovered in __aenter__.
        self._webrtc_egress_ip: Optional[str] = None

    async def __aenter__(self) -> Union[Browser, BrowserContext]:
        import sys as _sys
        # Resolve timezone="auto" AND discover the proxy egress IP in one
        # round-trip, off the event loop, before anything reads self._timezone
        # or builds prefs/env. Fail-early if a proxy is set but the egress
        # can't be resolved.
        _geo = await asyncio.to_thread(
            prepare_session_geo, self._timezone, self._proxy
        )
        self._timezone = _geo.timezone
        self._webrtc_egress_ip = _geo.egress_ip
        # Geo-aware locale: "auto" derives the language from the egress country (reusing
        # the egress IP just discovered), like timezone="auto". Keeps the browser language
        # consistent with the proxy's country instead of a fixed en-US.
        if (self._locale or "").strip().lower() == "auto":
            from ._geo import resolve_session_locale
            self._locale = await asyncio.to_thread(
                resolve_session_locale, _geo.egress_ip, self._proxy
            )
        # binary_path= never reaches ensure_binary(), so the engine check lives
        # on the resolved executable rather than inside the fetcher.
        executable = resolve_executable(self._binary_path)
        prefs = translate_profile_to_prefs(
            self._profile,
            locale=self._locale,
            timezone=self._timezone,
            extra_prefs=self._extra_prefs,
            virtual_display=bool(self._headless and _sys.platform == "win32"),
        )
        # Windows & macOS hide the headless window via the binary's own cloak
        # (DWMWA_CLOAK / NSWindow alpha) - inject the pref so the patched build
        # cloaks its chrome windows. setdefault: an explicit user override wins.
        # (Mirrors launcher._build_prefs; the sync path always did this, async
        # didn't - so async headless=True never cloaked AND crashed below.)
        if self._headless and _sys.platform in ("win32", "darwin"):
            for _k, _v in cloak_prefs().items():
                prefs.setdefault(_k, _v)
        # stealthfox.* is the namespace the binary's Juggler reads (see launcher.py
        # note). The pref now selects WHICH generator runs, not whether motion is
        # on: it must be false while the wrapper draws the path, or every waypoint
        # we send would itself be expanded into a whole path.
        prefs.update(_humanize_prefs(self._cursor_engine, self._humanize))
        playwright_proxy = _configure_proxy_shared(self._proxy, prefs)
        pw_headless = self._resolve_headless()
        self._session_token = SessionToken.mint()
        env = self._build_env(prefs)
        try:
            self._pw = await async_playwright().start()
            if self._profile_dir is not None:
                # See sync launcher for the persistent-context rationale.
                self._profile_dir.mkdir(parents=True, exist_ok=True)
                # firefox-5 ships the C++ overrideTimezone IDL method (C7
                # chiusura), so locale + timezone_id now propagate cleanly
                # to the persistent context without hanging the launch.
                self._persistent_context = await self._pw.firefox.launch_persistent_context(
                    user_data_dir=str(self._profile_dir),
                    executable_path=str(executable),
                    headless=pw_headless,
                    firefox_user_prefs=prefs,
                    proxy=playwright_proxy,
                    args=self._extra_args,
                    env=env,
                    **self._default_context_kwargs(),
                )
                _patch_new_page_sleep(self._persistent_context)
                self._bind_process_tree()
                self._arm_cursor_engine(self._persistent_context)
                return self._persistent_context
            self._browser = await self._pw.firefox.launch(
                executable_path=str(executable),
                headless=pw_headless,
                firefox_user_prefs=prefs,
                proxy=playwright_proxy,
                args=self._extra_args,
                env=env,
            )
            # See the sync launcher: browser.version comes from the connection
            # initializer, costs no round trip, and cannot be spoofed by a pref.
            assert_wire_version(self._browser)
            self._bind_process_tree()
        except BaseException:
            await self._teardown()
            raise
        self._patch_new_context_defaults(self._browser)
        self._arm_cursor_engine(self._browser)
        return self._browser

    def _bind_process_tree(self) -> None:
        """Tie the browser tree to this process's lifetime, at the OS level.

        The same call the sync launcher makes. Its absence here is why the
        Windows leak survived 0.4.0 on this API: an exception out of the async
        block runs __aexit__ and Playwright cleans up, but a KILLED runner never
        reaches either, and only the kernel can act then.

        Best-effort: a failure leaves the pre-existing behaviour rather than
        breaking a launch that is otherwise fine.
        """
        try:
            self._lifetime_guard.bind(self._session_token)
        except Exception:
            pass

    def _arm_cursor_engine(self, owner: Any) -> None:
        """Register this session so its pages move through the Python generator.

        Same wiring as the sync launcher, and the same single hook point: the
        wrappers live on the shared implementation objects, so arming a session
        here covers ``await page.click(...)``, ``await locator.hover(...)`` and
        ``await page.mouse.move(...)`` without a second implementation.
        """
        if self._cursor_engine != ENGINE_PYTHON:
            return
        _enable_cursor_engine(
            owner, seed=self.seed, max_seconds=_cursor_max_seconds(self._humanize)
        )

    def _patch_new_context_defaults(self, browser: Browser) -> None:
        original = browser.new_context
        defaults = self._default_context_kwargs()
        prep = self._prep_recaptcha
        profile = self._profile  # pass the whole Profile (seed + browsing_history)
        tz = self._timezone  # used by _recaptcha_seed for CONSENT lang+region

        async def patched(**kw):
            merged = dict(defaults)
            merged.update(kw)
            ctx = await original(**merged)
            _patch_new_page_sleep(ctx)
            if prep:
                from ._recaptcha_seed import seed_recaptcha_cookies_async
                await seed_recaptcha_cookies_async(ctx, profile, timezone=tz)
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
        # Pass timezone via Playwright per-realm override (works for every
        # IANA name, including no-DST zones that Windows ICU silently drops
        # on the global pref path).
        if self._timezone:
            kwargs["timezone_id"] = self._timezone
        if self._locale:
            kwargs["locale"] = self._locale
        return kwargs

    async def __aexit__(self, *exc: Any) -> None:
        await self._teardown()

    async def _teardown(self) -> None:
        if self._persistent_context is not None:
            try:
                await self._persistent_context.close()
            except Exception:
                pass
            self._persistent_context = None
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
        if self._virtual_display is not None:
            try:
                self._virtual_display.stop()
            except Exception:
                pass
            self._virtual_display = None
        # Last, and unconditionally: whatever Playwright's close() managed or
        # did not, nothing carrying this session's token may outlive it. Each
        # step above is wrapped in `except: pass`, so before this existed a
        # browser that refused to close was swallowed and leaked in silence.
        if self._session_token:
            try:
                self._lifetime_guard.reap(self._session_token)
            except Exception:
                pass
            self._session_token = SessionToken()

    def _build_env(self, prefs: Dict[str, Any]) -> Dict[str, str]:
        import os as _os
        env = _os.environ.copy()
        if self._timezone:
            env["TZ"] = _tz_env(self._timezone)
        # Fonts need NO env: the patched binary is self-contained (always
        # bundle-only). No external font list / allow-list / system-ui.
        # WebRTC srflx override: feed nICEr's nr_stealth_bridge the proxy egress
        # IP (caller's explicit env var wins, else the IP auto-discovered in
        # __aenter__) and drop IPv6 from gathering behind a proxy.
        webrtc_ip = (
            _os.environ.get("STEALTHFOX_WEBRTC_PUBLIC_IP")
            or self._webrtc_egress_ip
        )
        if webrtc_ip:
            env["STEALTHFOX_WEBRTC_PUBLIC_IP"] = webrtc_ip
            env["STEALTHFOX_WEBRTC_DISABLE_IPV6"] = "1"
        # Stamp this session so teardown can find its own browser tree and only
        # its own. Children inherit the environment, so every process in the
        # tree carries it. See _reaper for why this is a token and not a search.
        return self._session_token.stamp(env)

    def _resolve_headless(self) -> bool:
        if not self._headless:
            return False
        # Opt-in TRUE headless. The default headful+cloak path intermittently
        # hangs launch_persistent_context ~40% on Windows (window/compositor
        # race with a persistent profile). True headless applies the IDENTICAL
        # fingerprint prefs (screen/viewport/canvas/webgl spoofed the same) and
        # is 100% reliable (~2.3s). Gated by env so other callers are unaffected.
        import os as _os
        if _os.environ.get("INVPW_TRUE_HEADLESS") == "1":
            return True
        vd = make_virtual_display()
        # Linux: Xvfb to start. Windows/macOS: make_virtual_display() returns
        # None (the binary self-cloaks via cloak_prefs injected in __aenter__),
        # so there is nothing to start - guarding the None was the missing piece
        # that made async headless=True crash with AttributeError on Windows.
        if vd is not None:
            vd.start()
            self._virtual_display = vd
        return False


__all__ = ["InvisiblePlaywright"]
