<p>
  <a href="https://github.com/feder-cr/invisible_playwright/actions/workflows/tests.yml"><img src="https://github.com/feder-cr/invisible_playwright/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="LICENSE"><img src="docs/badges/license.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="docs/badges/python.svg" alt="Python 3.11+"></a>
  <a href="https://github.com/feder-cr/firefox_antidetect_patch/releases"><img src="docs/badges/firefox.svg" alt="Firefox 150.0.1"></a>
  <a href="https://github.com/feder-cr/invisible_playwright/stargazers"><img src="docs/badges/stars.svg" alt="GitHub stars"></a>
  <a href="https://github.com/feder-cr/firefox_antidetect_patch/releases/tag/usage-counter"><img src="docs/badges/launches.svg" alt="browser launches"></a>
</p>

<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/banner-dark.png">
  <img src="docs/banner-light.png" alt="invisible_playwright" width="620">
</picture>
</div>

<h3 align="center">A modified Firefox that passes every bot detection test.</h3>

![invisible_playwright - 5/5 detection suites passed](docs/screenshots/hero.gif)

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
pip install git+https://github.com/feder-cr/invisible_playwright.git
python -m invisible_playwright fetch      # one-time ~100 MB download, SHA256-verified
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

Full list of pinnable keys, how pinning interacts with the Bayesian sampler, and common patterns are in **[docs/pinning.md](docs/pinning.md)**.

---

## CLI

```bash
invisible_playwright fetch          # download the binary if missing
invisible_playwright fetch --force  # re-download even if cached
invisible_playwright path           # print the absolute path to the cached binary
invisible_playwright version        # wrapper and binary versions
invisible_playwright clear-cache    # remove all cached binaries
```

## Related projects

Related projects that cover similar ground:

- **[arkenfox/user.js](https://github.com/arkenfox/user.js)** - Firefox privacy hardening via prefs. invisible_playwright patches C++ where prefs are insufficient.
- **[LibreWolf](https://librewolf.net)** - Firefox fork with privacy defaults. LibreWolf ships a configured binary; invisible_playwright ships source patches + automation wrapper.
- **[Camoufox](https://github.com/daijro/camoufox)** - open-source anti-detect Firefox. Patches a wider surface and ships its own fingerprint database; invisible_playwright uses a Bayesian sampler.

---

## License

MIT - see [LICENSE](LICENSE). The patched Firefox binary is distributed under the MPL-2.0 (Firefox upstream license). The C++ patches against mozilla-central that produce that binary are at [feder-cr/firefox_antidetect_patch](https://github.com/feder-cr/firefox_antidetect_patch).

---

## Disclaimer

This project is for educational purposes only. It is provided as-is, with no warranties. I take no responsibility for how it is used. Use it at your own risk and in compliance with the laws of your jurisdiction.


---

<p align="center">
  Built by <a href="https://it.linkedin.com/in/federico-elia-5199951b6">Federico Elia</a>
  &nbsp;<a href="https://it.linkedin.com/in/federico-elia-5199951b6"><img src="docs/badges/linkedin.svg" alt="LinkedIn"></a>
</p>
