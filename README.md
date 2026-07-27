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

### If you got here from a search

You are probably looking for one of these, and this is the same category:

- a **stealth Firefox for Playwright**, where the fingerprint is in the engine rather than in an injected script
- an **undetected browser automation** library for **Python**, as an alternative to `undetected-chromedriver` or `nodriver`
- an **anti-detect browser** you can drive from code instead of clicking around a GUI
- something to try when **Playwright is detected as a bot** on one site and works everywhere else

The nearest open-source neighbours are [Camoufox](https://github.com/daijro/camoufox), which also patches Firefox, and [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) and [nodriver](https://github.com/ultrafunkamsterdam/nodriver), which take the Chromium side. [Three ways to make Playwright undetected](https://feder-cr.github.io/invisible_playwright/playwright-stealth-levels.html) explains what each approach can and cannot reach, including the costs of this one.

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
- [Why headless browsers render different fonts](https://feder-cr.github.io/invisible_playwright/headless-fonts-differ.html) - the three causes, the per-platform font sets, and why the fix is not installing more fonts
- [What privacy.resistFingerprinting really does](https://feder-cr.github.io/invisible_playwright/resist-fingerprinting.html) - and why this project sets it to false on purpose
- [The ChromeDriver cdc_ variable](https://feder-cr.github.io/invisible_playwright/cdc-variable-explained.html) - why renaming it is not removing it, and what that generalises to
- [What bot.sannysoft.com actually checks](https://feder-cr.github.io/invisible_playwright/sannysoft-explained.html) - row by row, and the canvas-in-iframe test nobody reads
- [How CreepJS decides you are lying](https://feder-cr.github.io/invisible_playwright/creepjs-explained.html) - four detection techniques, and why blocking the probe is itself recorded
- [Firefox preferences that silently do nothing](https://feder-cr.github.io/invisible_playwright/firefox-prefs-not-applying.html) - five reasons, starting with the one that cost us a real bug
- [What BotD actually detects](https://feder-cr.github.io/invisible_playwright/botd-explained.html) - twenty detectors, and why most are not about bots at all
- [Why a FingerprintJS visitor ID changes](https://feder-cr.github.io/invisible_playwright/fingerprintjs-visitor-id.html) - it is a hash of 41 components, so one moving moves all of it

## Related projects

Related projects that cover similar ground:

- **[arkenfox/user.js](https://github.com/arkenfox/user.js)** - Firefox privacy hardening via prefs. invisible_playwright patches C++ where prefs are insufficient.
- **[LibreWolf](https://librewolf.net)** - Firefox fork with privacy defaults. LibreWolf ships a configured binary; invisible_playwright ships source patches + automation wrapper.
- **[Camoufox](https://github.com/daijro/camoufox)** - open-source anti-detect Firefox. Patches a wider surface and ships its own fingerprint database; invisible_playwright uses a Bayesian sampler.

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
