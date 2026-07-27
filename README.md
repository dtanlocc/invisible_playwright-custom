<p>
  <a href="https://github.com/feder-cr/invisible_playwright/actions/workflows/tests.yml"><img src="https://github.com/feder-cr/invisible_playwright/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="https://github.com/feder-cr/invisible_playwright/blob/main/LICENSE"><img src="https://raw.githubusercontent.com/feder-cr/invisible_playwright/main/docs/badges/license.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://raw.githubusercontent.com/feder-cr/invisible_playwright/main/docs/badges/python.svg" alt="Python 3.11+"></a>
  <a href="https://github.com/feder-cr/firefox_antidetect_patch/releases"><img src="https://raw.githubusercontent.com/feder-cr/invisible_playwright/main/docs/badges/firefox.svg" alt="Firefox 151.0"></a>
  <a href="https://github.com/feder-cr/invisible_playwright/stargazers"><img src="https://raw.githubusercontent.com/feder-cr/invisible_playwright/main/docs/badges/stars.svg" alt="GitHub stars"></a>
  <a href="https://github.com/feder-cr/firefox_antidetect_patch/releases/tag/usage-counter"><img src="https://raw.githubusercontent.com/feder-cr/invisible_playwright/main/docs/badges/launches.svg" alt="browser launches"></a>
</p>

<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/feder-cr/invisible_playwright/7a8693c6b4386e9a84dd93bedc479ca8654482e1/docs/banner-dark.png">
  <img src="https://raw.githubusercontent.com/feder-cr/invisible_playwright/7a8693c6b4386e9a84dd93bedc479ca8654482e1/docs/banner-light.png" alt="invisible_playwright" width="620">
</picture>
</div>

<h3 align="center">Undetected Playwright automation on a stealth-patched Firefox.<br>
Python, MIT, and it passes every bot detection test.</h3>

![invisible_playwright - 5/5 detection suites passed](https://raw.githubusercontent.com/feder-cr/invisible_playwright/7a8693c6b4386e9a84dd93bedc479ca8654482e1/docs/screenshots/hero.gif)

## How it works

Anti-bots ask two questions. invisible_playwright answers yes to both.

**1. Is this a real browser?** Yes. It is Firefox, patched at the C++ source level.

- Fingerprint set inside the engine, not injected into the page: Navigator, screen, GPU/WebGL, Canvas, fonts, audio, WebRTC, timezone, network.
- No JS shim, no override, no seam to read.

**2. Is a real person using it?** Yes. The actions are humanized in the driver.

- Every click, hover and drag follows a natural mouse path with human timing, no teleporting cursor.
- Each input is byte-identical to a real mouse: real input source, pressure, trusted events.

Driven by the standard Playwright API. Full breakdown: [feder-cr/firefox_antidetect_patch](https://github.com/feder-cr/firefox_antidetect_patch).

---

## Still seeing captchas or anti-bot? It's the proxy.
Once the browser is handled it stops being the variable. If you are still getting challenged, the tell is no longer the browser, it is the IP you come from. Around 90% of proxies are public: anyone can rent the same address, so it is already known and sits on the blocked-IP lists sites check. A perfect browser on a known IP still loses.

> The fix is the clean 10%, residential IPs that aren't already known. For those we recommend [sx.org](https://sx.org/?c=invisible_playwright), who filter for and serve only IPs that aren't already on those lists.

---

## Install

```bash
pip install invisible-playwright
python -m invisible_playwright fetch      # one-time ~238 MB download (~544 MB unpacked), sha256-verified
```

Supported platforms: **Windows x86_64**, **Linux x86_64 / arm64**, **macOS arm64 / x86_64**. On macOS the app is ad-hoc signed (not notarized): if Gatekeeper complains, clear the quarantine flag once with `xattr -dr com.apple.quarantine` on the cached `Firefox.app`.

---

## Usage
### Random fingerprint per session
**100% Playwright-compatible** - sync and async, all methods, zero API changes. If you already use Playwright, switching is two lines:

```diff
- from playwright.sync_api import sync_playwright
- with sync_playwright() as p:
-     browser = p.firefox.launch()
+ from invisible_playwright import InvisiblePlaywright
+ with InvisiblePlaywright() as browser:
```

Every session gets a distinct fingerprint (GPU, audio, fonts, screen, ~400 fields) and Bezier-curve mouse motion.

**Sync**
```python
from invisible_playwright import InvisiblePlaywright

with InvisiblePlaywright(proxy={"server": "socks5://...", "username": "u", "password": "p"}) as browser:
    page = browser.new_page()
    page.goto("https://example.com")
    page.click("#submit")   # mouse arcs to the button on a Bezier curve
```

**Async**
```python
from invisible_playwright.async_api import InvisiblePlaywright

async with InvisiblePlaywright(proxy={"server": "socks5://...", "username": "u", "password": "p"}) as browser:
    page = await browser.new_page()
    await page.goto("https://example.com")
    await page.click("#submit")
```

The `browser` object is a `playwright.sync_api.Browser` / `playwright.async_api.Browser` - every Playwright method works as-is.

Log the seed to replay a run:

```python
sf = InvisiblePlaywright()
with sf as browser:
    print("seed =", sf.seed)
    # ...
```

### Reproducible fingerprint

```python
with InvisiblePlaywright(seed=42) as browser:
    ...   # same GPU, same canvas hash, same audio context, every run
```

### Proxies

```python
proxy = {
    "server": "socks5://gate.example.com:1080",
    "username": "user",
    "password": "pass",
}
with InvisiblePlaywright(proxy=proxy) as browser:
    ...
```

Schemes supported: `socks5`, `socks4`, `http`, `https`. DNS is routed through the proxy by default, no local leak.

Around 90% of proxies are public, so their IPs are already known and blocked. For the clean 10%, residential IPs that aren't already known, we recommend [sx.org](https://sx.org/?c=invisible_playwright), who filter for and serve only IPs that aren't already on those lists.

### Timezone

The browser timezone follows `timezone=`:

```python
# default: timezone is auto-derived from the egress IP (proxy egress if a
# proxy is set, otherwise the host's own public IP)
with InvisiblePlaywright(proxy=proxy) as browser:
    ...

# explicit IANA zone always wins, the only way to force a specific zone
with InvisiblePlaywright(proxy=proxy, timezone="America/New_York") as browser:
    ...
```

### Pinning specific fingerprint fields

By default everything comes from `seed`. To force specific values while the rest stays seed-derived:

```python
with InvisiblePlaywright(
    seed=42,
    pin={
        "gpu.renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 Direct3D11)",
        "gpu.vendor":   "Google Inc. (NVIDIA)",
        "screen.width":  2560,
        "screen.height": 1440,
        "hardware.concurrency": 16,
    },
) as browser:
    ...
```

Full list of pinnable keys, how pinning interacts with the Bayesian sampler, and common patterns are in **[docs/pinning.md](https://feder-cr.github.io/invisible_playwright/pinning.html)**.

---

## CLI

The installed command is `invisible-playwright`, with a hyphen. `python -m
invisible_playwright` works identically and needs nothing on PATH.

```bash
invisible-playwright fetch          # download the engine if missing
invisible-playwright fetch --force  # re-download even if cached
invisible-playwright path           # absolute path to the cached engine (downloads it if absent)
invisible-playwright version        # wrapper, core and engine versions
invisible-playwright clear-cache    # remove cached engine trees
invisible-playwright doctor         # check every cached engine against the seal
```

### Where the engine lives, and how big it is

The first launch downloads one archive for your platform - **238 MB on Windows,
217-232 MB elsewhere** - and unpacks it to about **544 MB** on disk. It is
verified against a sha256 shipped inside `invisible-core`, so a truncated or
substituted download is refused rather than used.

It is cached, so this happens once per engine version. Set
`INVISIBLE_PLAYWRIGHT_CACHE_DIR` to put it somewhere else - a different drive,
a shared location, a path your CI already caches:

```bash
export INVISIBLE_PLAYWRIGHT_CACHE_DIR=/mnt/big/engines
```

Other environment variables you may want:

| variable | what it does |
|---|---|
| `INVISIBLE_PLAYWRIGHT_CACHE_DIR` | where engines are cached |
| `INVPW_BINARY_PATH` | use a specific binary and skip the download entirely |
| `STEALTHFOX_GITHUB_TOKEN` | authenticate the download, for rate-limited or corporate networks |
| `INVISIBLE_PLAYWRIGHT_SKEW=allow` | run a Playwright outside the tested range anyway |
| `INVPW_CURSOR_ENGINE` | `python` (default), `binary`, or `off` |

## Guides and explainers

All of it reads better, and is searchable, at
**[feder-cr.github.io/invisible_playwright](https://feder-cr.github.io/invisible_playwright/)**.
Same pages, same repo, with a search box.

Running it inside something else:

- [Scrapy, via scrapy-playwright](https://feder-cr.github.io/invisible_playwright/integrations/scrapy-playwright.html) - two settings, engine and profile both
- [Crawlee for Python](https://feder-cr.github.io/invisible_playwright/integrations/crawlee-python.html) - a browser plugin, or one line for the engine alone
- [Playwright MCP](https://feder-cr.github.io/invisible_playwright/integrations/playwright-mcp.html) - two flags on Microsoft's own MCP server
- [Go, Java, C#, Ruby, Rust](https://feder-cr.github.io/invisible_playwright/integrations/other-languages.html) - the engine is not Python
- [CodeceptJS](https://feder-cr.github.io/invisible_playwright/integrations/codeceptjs.html) - a `firefox` block in the helper config
- [Robot Framework Browser](https://feder-cr.github.io/invisible_playwright/integrations/robot-framework.html) - `executablePath` and `firefoxUserPrefs` are keyword arguments
- [Crawlee for JavaScript](https://feder-cr.github.io/invisible_playwright/integrations/crawlee-js.html) - a launcher swap, plus `useFingerprints: false`
- [Cypress, WebdriverIO, TestCafe, Nightwatch](https://feder-cr.github.io/invisible_playwright/integrations/test-runners.html) - and which of the four cannot carry the profile
- [All of them, and the ones it does not fit](https://feder-cr.github.io/invisible_playwright/integrations/) - including why, by name

How any of this works, whether or not you use this project. [Full index](https://feder-cr.github.io/invisible_playwright/):

- [navigator.webdriver is not the tell you think it is](https://feder-cr.github.io/invisible_playwright/navigator-webdriver-explained.html) - why setting it to `false` is worse than leaving it alone
- [Three ways to make Playwright undetected](https://feder-cr.github.io/invisible_playwright/playwright-stealth-levels.html) - page, driver, engine, and what each one cannot reach
- [Detected on one site only: the checklist](https://feder-cr.github.io/invisible_playwright/playwright-detected-as-bot.html) - in order, with the proxy seventh rather than first
- [Firefox WebGL renderer strings](https://feder-cr.github.io/invisible_playwright/webgl-renderer-strings.html) - what ANGLE reports, and the software-rasterizer tell we shipped ourselves
- [Your renderer string says NVIDIA, your pixels say software](https://feder-cr.github.io/invisible_playwright/renderer-string-vs-render.html) - a detection flag we chased in the wrong direction, and what a GPU claim cannot fake
- [WebRTC leaks with a proxy](https://feder-cr.github.io/invisible_playwright/webrtc-leak-proxy.html) - why disabling WebRTC is the wrong fix, and the dead preference everyone still recommends
- [speechSynthesis.getVoices() returns an empty array](https://feder-cr.github.io/invisible_playwright/speech-synthesis-voices.html) - the async gotcha, and the reason the list is a statement about your operating system
- [AudioContext fingerprinting](https://feder-cr.github.io/invisible_playwright/audiocontext-fingerprinting.html) - the seven values that have to agree, and the measurement that made us turn our own noise off
- [Playwright timezone does not match the proxy IP](https://feder-cr.github.io/invisible_playwright/timezone-proxy-mismatch.html) - nine values that have to agree, and why the environment variable does not work on Windows
- [Playwright SOCKS5 proxy with authentication](https://feder-cr.github.io/invisible_playwright/playwright-socks5-proxy-authentication.html) - the credentials are documented for HTTP proxies only, and the upstream request has been open since 2021
- [JA3 and JA4 TLS fingerprints](https://feder-cr.github.io/invisible_playwright/ja3-ja4-tls-fingerprint.html) - decided before any JavaScript exists, so no stealth layer can reach it
- [Human-like mouse movement in Playwright](https://feder-cr.github.io/invisible_playwright/human-mouse-movement.html) - the curve is the easy half, the event fields are the half that gets checked
- [Canvas fingerprint noise](https://feder-cr.github.io/invisible_playwright/canvas-fingerprint-noise.html) - why randomising per call is caught in four lines, and the solid-fill probe nobody knows about
- [Screen size and viewport tells in headless browsers](https://feder-cr.github.io/invisible_playwright/screen-size-headless-tells.html) - availHeight, outerHeight and the relationships that have to hold
- [Playwright in Docker: it runs and still gets blocked](https://feder-cr.github.io/invisible_playwright/playwright-docker-detection.html) - six things a container says about itself, and why the official image is a cohort
- [hardwareConcurrency, deviceMemory and storage quota](https://feder-cr.github.io/invisible_playwright/hardware-concurrency-device-memory.html) - three numbers about the machine, and the worker check that catches page-level spoofing
- [Function.prototype.toString and the [native code] check](https://feder-cr.github.io/invisible_playwright/tostring-native-code-detection.html) - why every JavaScript override carries its own source, and the four ways that is found
- [reCAPTCHA v3 score: why a fresh browser scores badly](https://feder-cr.github.io/invisible_playwright/recaptcha-v3-score.html) - the score is about history, and a fresh profile has none
- [Execution context was destroyed](https://feder-cr.github.io/invisible_playwright/execution-context-destroyed.html) - the ordinary race, and the case where the site navigated you somewhere else
- [Why an attached debugger makes automation detectable](https://feder-cr.github.io/invisible_playwright/debugger-timing-detection.html) - a debugger disables the JIT, and timing is a fingerprint too
- [Browser extensions are a fingerprint surface](https://feder-cr.github.io/invisible_playwright/browser-extension-fingerprint.html) - three ways a page finds one, and why a stealth extension argues with a stealth engine
- [Headless vs headful: what is actually being detected](https://feder-cr.github.io/invisible_playwright/headless-vs-headful.html) - rarely headlessness, usually the machine it runs on, plus the third option nobody mentions
- [WebGL parameters: the numbers are the same on every GPU](https://feder-cr.github.io/invisible_playwright/webgl-parameters-are-identical.html) - the most repeated advice here is backwards, and randomising them removed us from the report
- [Playwright persistent profile](https://feder-cr.github.io/invisible_playwright/persistent-profiles.html) - what it fixes, and the stored permission that disables your WebRTC protection
- [CSS fingerprinting without JavaScript](https://feder-cr.github.io/invisible_playwright/css-media-query-fingerprinting.html) - media queries and system colours identify a machine with no script, so no page-level layer applies
- [Codec fingerprinting: canPlayType and MediaCapabilities](https://feder-cr.github.io/invisible_playwright/codec-fingerprinting.html) - three surfaces in one API, including whether your machine has a hardware decoder
- [BFCache and pageshow.persisted under automation](https://feder-cr.github.io/invisible_playwright/bfcache-pageshow-persisted.html) - drivers disable the back/forward cache, so every back navigation is a full reload
- [Why you should not set the user agent](https://feder-cr.github.io/invisible_playwright/playwright-user-agent.html) - rotating the string does not rotate the browser, it only creates contradictions
- [browser-use gets detected](https://feder-cr.github.io/invisible_playwright/browser-use-detection.html) - what its BrowserProfile reaches, and the tell specific to agent-driven sessions
- [AI browser agents and stealth](https://feder-cr.github.io/invisible_playwright/ai-browser-agents-stealth.html) - browser-use, Stagehand, Skyvern, crawl4ai and Maxun checked from source, and what applies whichever you picked
- [How to test whether your browser is detected](https://feder-cr.github.io/invisible_playwright/how-to-test-bot-detection.html) - what each suite proves, the false pass, and the comparison that replaces the verdict
- [Playwright proxy per context: what it does not isolate](https://feder-cr.github.io/invisible_playwright/playwright-proxy-per-context.html) - a context isolates storage, not hardware, so five proxies on one browser is one machine in five countries
- [Permissions API: the two answers that must agree](https://feder-cr.github.io/invisible_playwright/permissions-api-consistency.html) - the two-line headless check, and why granting everything makes a browser nobody has
- [Service workers and storage partitioning](https://feder-cr.github.io/invisible_playwright/service-workers-storage-partitioning.html) - a registration survives clearing cookies, and blocking them removes a capability every real browser has
- [Web Workers: where page-level patches fail](https://feder-cr.github.io/invisible_playwright/web-workers-fingerprint.html) - a worker is a separate realm, and OffscreenCanvas fingerprints the canvas from inside one
- [WebRTC ICE candidate spoofing](https://feder-cr.github.io/invisible_playwright/webrtc-ice-candidate-spoofing.html) - the address is the easy field; the priority, the foundation and the arrival time are the ones that give it away
- [Firefox or Chromium for anti-detect](https://feder-cr.github.io/invisible_playwright/firefox-vs-chromium-antidetect.html) - no CDP surface and one identity instead of three, against being a small share of real traffic
- [Client Hints and Sec-Fetch: headers that must agree](https://feder-cr.github.io/invisible_playwright/client-hints-sec-fetch.html) - three copies of one identity, plus the headers that describe how the request was initiated
- [crawl4ai stealth and custom browser engines](https://feder-cr.github.io/invisible_playwright/crawl4ai-stealth-custom-browser.html) - browser_type accepts firefox but there is no executable_path; where the adapter seam is
- [Why headless browsers render different fonts](https://feder-cr.github.io/invisible_playwright/headless-fonts-differ.html) - the three causes, the per-platform font sets, and why the fix is not installing more fonts
- [What privacy.resistFingerprinting really does](https://feder-cr.github.io/invisible_playwright/resist-fingerprinting.html) - and why this project sets it to false on purpose
- [The ChromeDriver cdc_ variable](https://feder-cr.github.io/invisible_playwright/cdc-variable-explained.html) - why renaming it is not removing it, and what that generalises to
- [What bot.sannysoft.com actually checks](https://feder-cr.github.io/invisible_playwright/sannysoft-explained.html) - row by row, and the canvas-in-iframe test nobody reads
- [How CreepJS decides you are lying](https://feder-cr.github.io/invisible_playwright/creepjs-explained.html) - four detection techniques, and why blocking the probe is itself recorded
- [Firefox preferences that silently do nothing](https://feder-cr.github.io/invisible_playwright/firefox-prefs-not-applying.html) - five reasons, starting with the one that cost us a real bug
- [What BotD actually detects](https://feder-cr.github.io/invisible_playwright/botd-explained.html) - twenty detectors, and why most are not about bots at all
- [Why a FingerprintJS visitor ID changes](https://feder-cr.github.io/invisible_playwright/fingerprintjs-visitor-id.html) - it is a hash of 41 components, so one moving moves all of it

## Related projects

The open-source neighbours, and what each one is for.

**On the Firefox side**

- **[Camoufox](https://github.com/daijro/camoufox)** - an anti-detect Firefox that also patches at the C++ level. It covers a wider surface and ships its own fingerprint database; this project derives a fingerprint from a seed with a Bayesian sampler, so one number reproduces one machine.
- **[LibreWolf](https://librewolf.net)** - a Firefox fork with privacy defaults. It ships a configured binary for people to browse with; this ships source patches plus an automation wrapper.
- **[arkenfox/user.js](https://github.com/arkenfox/user.js)** - Firefox hardening through preferences. Where a preference is enough, use it; this project patches C++ where one is not.

**On the Chromium side**

- **[Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)** - a patched Playwright fork, so the stealth work lands in the driver rather than in the browser binary.
- **[nodriver](https://github.com/ultrafunkamsterdam/nodriver)** - the successor to `undetected-chromedriver`, driving Chrome over CDP directly and removing the WebDriver-flavoured tells.

Which of these fits depends on the layer your problem is at, and on whether you need Firefox or Chromium. [Three ways to make Playwright undetected](https://feder-cr.github.io/invisible_playwright/playwright-stealth-levels.html) works through what each layer can and cannot reach, including what this one costs.

If you are picking between engines rather than tools, note that a large share of AI agent frameworks drive Chromium over CDP, which decides the question for you: [AI browser agents and stealth](https://feder-cr.github.io/invisible_playwright/ai-browser-agents-stealth.html).

---

## License

MIT - see [LICENSE](https://github.com/feder-cr/invisible_playwright/blob/main/LICENSE). The patched Firefox binary is distributed under the MPL-2.0 (Firefox upstream license). The C++ patches against mozilla-central that produce that binary are at [feder-cr/firefox_antidetect_patch](https://github.com/feder-cr/firefox_antidetect_patch).

---

## Disclaimer

This project is for educational purposes only. It is provided as-is, with no warranties. I take no responsibility for how it is used. Use it at your own risk and in compliance with the laws of your jurisdiction.


---

<p align="center">
  Built by <a href="https://it.linkedin.com/in/federico-elia-5199951b6">Federico Elia</a>
  &nbsp;<a href="https://it.linkedin.com/in/federico-elia-5199951b6"><img src="https://raw.githubusercontent.com/feder-cr/invisible_playwright/main/docs/badges/linkedin.svg" alt="LinkedIn"></a>
</p>
