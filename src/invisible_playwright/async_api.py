"""Async Playwright façade - mirrors sync_api but with async/await."""
from __future__ import annotations

import asyncio
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

from invisible_playwright._pw.async_api import Browser, BrowserContext, Playwright, async_playwright

from . import _session
from ._cursor import (
    ENGINE_PYTHON,
    enable_for as _enable_cursor_engine,
    max_seconds_for as _cursor_max_seconds,
    resolve_cursor_engine,
)
from invisible_core._fpforge import Profile, generate_profile
from invisible_core import forced_gpu_class
from invisible_core import prepare_session_geo
from invisible_core import make_virtual_display
from ._engine import assert_wire_version, resolve_executable
from invisible_core import configure_proxy as _configure_proxy_shared
from ._reaper import SessionToken, guard_for
from .launcher import _CHROME_H, _CHROME_W, _TASKBAR_H


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
        #: La DECISIONE sul srflx, distinta dal fatto qui sopra.
        #: Parte da None come lui: `_build_env` puo' essere chiamata
        #: prima che il percorso geo abbia risolto, e in quel caso non
        #: si dichiara niente.
        self._srflx_dichiarato: Optional[str] = None
        #: Vedi il gemello in `launcher.py`: parte a 0 perche' il primo contesto
        #: deve poter controllare subito.
        self._ultimo_controllo_uscita: float = 0.0
        #: Sonde consecutive che non hanno risposto. Azzerato da ogni
        #: controllo riuscito, cosi' conta le raffiche e non il totale.
        self._uscite_non_misurabili: int = 0

    async def __aenter__(self) -> Union[Browser, BrowserContext]:
        # Resolve timezone="auto" AND discover the proxy egress IP in one
        # round-trip, off the event loop, before anything reads self._timezone
        # or builds prefs/env. Fail-early if a proxy is set but the egress
        # can't be resolved.
        _geo = await asyncio.to_thread(
            prepare_session_geo, self._timezone, self._proxy
        )
        self._timezone = _geo.timezone
        self._webrtc_egress_ip = _geo.egress_ip
        # ⛔ DUE COSE DIVERSE, e prima erano un campo solo.
        # `_webrtc_egress_ip` e' il FATTO: da dove usciamo. Serve alla
        # guardia contro la deriva, che confronta l'uscita di adesso con
        # quella del lancio.
        # `_srflx_dichiarato` e' la DECISIONE: cosa il motore deve
        # annunciare. Vale None quando l'uscita ha UDP dimostrato e
        # coerente, perche' li' il srflx vero nasce gia' giusto e
        # dichiararne uno aggiungerebbe un candidato senza allocazione
        # corrispondente - il segnale che un rilevatore con un TURN
        # proprio legge. Il core la prende in un punto solo.
        self._srflx_dichiarato = _geo.srflx_da_dichiarare()
        # Geo-aware locale: "auto" derives the language from the egress country (reusing
        # the egress IP just discovered), like timezone="auto". Keeps the browser language
        # consistent with the proxy's country instead of a fixed en-US.
        if (self._locale or "").strip().lower() == "auto":
            from invisible_core import resolve_session_locale
            self._locale = await asyncio.to_thread(
                resolve_session_locale, _geo.egress_ip, self._proxy
            )
        # binary_path= never reaches ensure_binary(), so the engine check lives
        # on the resolved executable rather than inside the fetcher.
        executable = resolve_executable(self._binary_path)
        # il risultato REALE di _resolve_headless (ha creato un desktop
        # alternativo o no?) deve essere noto PRIMA di comporre le prefs,
        # non dopo: B172, 2026-08-24.
        pw_headless = self._resolve_headless()
        prefs = self._build_prefs()
        playwright_proxy = _configure_proxy_shared(self._proxy, prefs)
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

    #: Gemello di `launcher._INTERVALLO_CONTROLLO_USCITA_S`. Le due classi
    #: devono restare uguali: e' il difetto che `_session.py` esiste per non
    #: ripetere, e che ha gia' prodotto tre bug.
    _INTERVALLO_CONTROLLO_USCITA_S = 120.0

    #: Quante volte di fila la sonda puo' non rispondere prima che la sessione
    #: venga rifiutata. Uno solo sarebbe troppo severo - un timeout capita - ma
    #: illimitati sarebbero cecita' dichiarata: dopo tre controlli muti a 120 s
    #: l'uno, sono sei minuti in cui nessuno sta confermando l'indirizzo che il
    #: motore annuncia a ogni pagina.
    _MAX_USCITE_NON_MISURABILI = 3

    async def _assert_uscita_invariata(self) -> None:
        """Rifiuta se l'IP di uscita e' cambiato dal lancio. Vedi il gemello
        sincrono in `launcher.py` per il perche' non si aggiorna al volo."""
        if not self._proxy or not self._webrtc_egress_ip:
            return
        adesso = time.monotonic()
        if adesso - self._ultimo_controllo_uscita < self._INTERVALLO_CONTROLLO_USCITA_S:
            return
        self._ultimo_controllo_uscita = adesso
        # La scoperta e' sincrona e fa rete: non deve bloccare il loop.
        esito, attuale = await asyncio.get_running_loop().run_in_executor(
            None, _session.egress_ancora_valido, self._proxy,
            self._webrtc_egress_ip)
        if esito == _session.USCITA_DERIVATA:
            raise _session.ProxyEgressDrifted(
                "l'IP di uscita del proxy e' cambiato durante la sessione: "
                "al lancio era %s, adesso e' %s. Il candidato WebRTC srflx "
                "dichiara ancora il primo, quindi da questo momento la pagina "
                "esce da un indirizzo e WebRTC ne annuncia un altro - e' il "
                "disaccordo che i rilevatori cercano. Questo proxy non tiene "
                "la sessione appiccicosa per la durata richiesta: usane uno "
                "che la garantisca, o accorcia la sessione."
                % (self._webrtc_egress_ip, attuale))
        if esito == _session.USCITA_NON_MISURABILE:
            # NON e' "regge", ed e' per questo che gli esiti sono tre. Una sonda
            # che cade UNA volta e' la rete; una che cade sempre e' cecita': da
            # quel momento il motore continua a dichiarare a ogni pagina un
            # indirizzo che nessuno sta piu' confermando. Si conta, invece di
            # ignorare, e si rifiuta solo se si ripete.
            self._uscite_non_misurabili += 1
            if self._uscite_non_misurabili >= self._MAX_USCITE_NON_MISURABILI:
                raise _session.ProxyEgressNonVerificabile(
                    "l'IP di uscita non e' stato verificabile per %d controlli "
                    "di fila. Non e' una deriva - la sonda non ha risposto "
                    "affatto - ma non e' nemmeno parita': da qui in avanti il "
                    "motore dichiarerebbe a ogni pagina un indirizzo che "
                    "nessuno conferma piu'. Controlla che il proxy sia "
                    "raggiungibile, poi rilancia la sessione."
                    % self._uscite_non_misurabili)
            return
        self._uscite_non_misurabili = 0

    def _patch_new_context_defaults(self, browser: Browser) -> None:
        """Both entry points, for the reason spelled out in the sync launcher:
        Playwright's `Browser.new_page` forwards to the IMPLEMENTATION object,
        whose own `new_page` calls `self.new_context` - itself - so a wrapper
        installed on the api object is never consulted, and
        `await browser.new_page()` opened a page with the stock viewport and
        colour scheme against a fingerprint claiming the profile's screen."""
        original = browser.new_context
        defaults = self._default_context_kwargs()
        prep = self._prep_recaptcha
        profile = self._profile  # pass the whole Profile (seed + browsing_history)
        loc = self._locale  # used by _recaptcha_seed for CONSENT lang+region

        async def patched(**kw):
            await self._assert_uscita_invariata()
            merged = dict(defaults)
            merged.update(kw)
            ctx = await original(**merged)
            if prep:
                from ._recaptcha_seed import seed_recaptcha_cookies_async
                await seed_recaptcha_cookies_async(ctx, profile, locale=loc)
            # ⛔ ANCHE `context.new_page`: stessa lacuna del percorso sincrono,
            # stessa correzione. La guardia stava su `browser.new_context` e
            # `browser.new_page`, e non sul modo NORMALE di aprire una scheda,
            # quindi una sessione che apre un contesto e poi N pagine faceva un
            # controllo solo. Misurato: al lancio l'uscita era una, nove schede
            # dopo un'altra, e comparivano insieme sulla stessa pagina.
            #
            # Correggerlo su un solo percorso avrebbe lasciato le due API a
            # dare garanzie diverse sulla stessa cosa.
            _new_page_ctx = ctx.new_page

            async def _new_page_sorvegliata(**kw2):
                await self._assert_uscita_invariata()
                return await _new_page_ctx(**kw2)

            ctx.new_page = _new_page_sorvegliata  # type: ignore[assignment]
            return ctx

        browser.new_context = patched  # type: ignore[assignment]

        original_page = browser.new_page

        async def patched_page(**kw):
            await self._assert_uscita_invariata()
            merged = dict(defaults)
            merged.update(kw)  # user-supplied wins, same rule as new_context
            page = await original_page(**merged)
            ctx = page.context
            if prep:
                from ._recaptcha_seed import seed_recaptcha_cookies_async
                await seed_recaptcha_cookies_async(ctx, profile, locale=loc)
            return page

        browser.new_page = patched_page  # type: ignore[assignment]

    def _default_context_kwargs(self) -> Dict[str, Any]:
        p = self._profile
        kwargs: Dict[str, Any] = {
            "viewport":            {"width":  p.screen.width  - p.screen.chrome_w,
                                     "height": (p.screen.height
                                                - p.screen.taskbar_px
                                                - p.screen.chrome_h)},
            "screen":              {"width": p.screen.width, "height": p.screen.height},
            # ⛔ device_scale_factor e color_scheme NON si passano piu'.
            # Erano una seconda fonte per due fatti che invisible_core gia'
            # dichiara (layout.css.devPixelsPerPx e
            # layout.css.prefers-color-scheme.content-override), e vinceva
            # questa: misurato, mettendo la pref a un valore diverso il browser
            # non si muoveva. Tenuto identico al ramo sincrono, che
            # test_async_default_context_kwargs_match_sync pretende - ed e' il
            # test che ha visto questa riga rimasta indietro.
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
        cancelled: BaseException | None = None

        async def _try(coro: Any) -> None:
            nonlocal cancelled
            try:
                await coro
            except asyncio.CancelledError as exc:
                # Catch it and store the exception for later
                cancelled = exc
            except Exception:
                pass

        try:
            if self._persistent_context is not None:
                await _try(self._persistent_context.close())
                self._persistent_context = None
            if self._browser is not None:
                await _try(self._browser.close())
                self._browser = None
            if self._pw is not None:
                await _try(self._pw.stop())
                self._pw = None
            if self._virtual_display is not None:
                try:
                    self._virtual_display.stop()
                except Exception:
                    pass
                self._virtual_display = None
        finally:
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

        if cancelled is not None:
            raise cancelled

    def _build_env(self, prefs: Dict[str, Any]) -> Dict[str, str]:
        """Same body as the sync class - it always was, character for character.

        The token stamp stays here: it is the one per-session part, and losing
        it is what made the reaper unable to find this API's browser tree.
        """
        return self._session_token.stamp(
            _session.build_env(timezone=self._timezone,
                               srflx_dichiarato=self._srflx_dichiarato,
                               profile=self._profile,
                               executable=resolve_executable(self._binary_path)))

    def _build_prefs(self) -> Dict[str, Any]:
        """Same body as the sync class, because it is the same body.

        These were twenty identical lines here and twenty in
        `launcher._build_prefs` - same calls, same order, differing only in
        their comments. Both delegate to `_session.build_prefs` now.
        """
        return _session.build_prefs(
            profile=self._profile,
            locale=self._locale,
            timezone=self._timezone,
            extra_prefs=self._extra_prefs,
            headless=self._headless,
            virtual_display=self._virtual_display is not None,
            cursor_engine=self._cursor_engine,
            humanize=self._humanize,
        )

    def _resolve_headless(self) -> bool:
        if not self._headless:
            return False
        # Opt-in TRUE headless. The default headful+cloak path intermittently
        # hangs launch_persistent_context ~40% on Windows (window/compositor
        # race with a persistent profile). True headless applies the IDENTICAL
        # fingerprint prefs (screen/viewport/canvas/webgl spoofed the same) and
        # is reliable (~2.3s). Read through `_session` so the sync class gets
        # it too: until 2026-07-27 this env var was honoured HERE ONLY, so a
        # documented knob worked or not depending on which entry point the
        # caller had picked.
        if _session.true_headless_requested():
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
