# Documentation

## Running it inside something else

Each page is written against that framework's current source and says which version
it was checked at, because these break quietly when an upstream signature changes.

| Framework | Page | What it takes |
|---|---|---|
| Scrapy, via `scrapy-playwright` | [integrations/scrapy-playwright.md](integrations/scrapy-playwright.md) | a browser provider, which reaches the whole wrapper |
| Crawlee for Python | [integrations/crawlee-python.md](integrations/crawlee-python.md) | a browser plugin, or one line for the engine alone |
| Crawlee for JavaScript | [integrations/crawlee-js.md](integrations/crawlee-js.md) | a launcher swap plus `useFingerprints: false` |
| CodeceptJS | [integrations/codeceptjs.md](integrations/codeceptjs.md) | a `firefox` block, forwarded verbatim |
| Robot Framework Browser | [integrations/robot-framework.md](integrations/robot-framework.md) | both halves as named keyword arguments |
| Cypress, WebdriverIO, TestCafe | [integrations/test-runners.md](integrations/test-runners.md) | two carry both halves, one carries only the engine |
| Playwright MCP | [integrations/playwright-mcp.md](integrations/playwright-mcp.md) | two flags on Microsoft's own MCP server |
| Go, Java, C#, Ruby, Rust | [integrations/other-languages.md](integrations/other-languages.md) | the engine is not Python |

The [integrations index](integrations/) also lists the frameworks this does not fit,
by name and with the reason, which is usually a launch path bound to Chromium or one
that only connects to a remote browser.

## How any of this works

Written to be useful whether or not you use this project. If they only made sense as
an advert for it they would not be worth reading.

| Page | Answers |
|---|---|
| [playwright-detected-as-bot.md](playwright-detected-as-bot.md) | detected on one site only, what to check and in what order |
| [playwright-stealth-levels.md](playwright-stealth-levels.md) | the three levels a stealth tool can work at, and what each cannot reach |
| [navigator-webdriver-explained.md](navigator-webdriver-explained.md) | why setting it to `false` is worse than leaving it alone |
| [webgl-renderer-strings.md](webgl-renderer-strings.md) | what ANGLE reports, and the software-rasterizer tell we shipped ourselves |
| [headless-fonts-differ.md](headless-fonts-differ.md) | why headless renders different fonts, and why more fonts is not the fix |
| [resist-fingerprinting.md](resist-fingerprinting.md) | what Firefox's own mode changes, and why this project turns it off |
| [cdc-variable-explained.md](cdc-variable-explained.md) | the ChromeDriver variable, and why renaming is not removing |
| [sannysoft-explained.md](sannysoft-explained.md) | row by row, including the canvas-in-iframe test nobody reads |
| [creepjs-explained.md](creepjs-explained.md) | four ways it detects tampering, and why blocking its probe is recorded |
| [firefox-prefs-not-applying.md](firefox-prefs-not-applying.md) | why a preference you set is silently ignored, in the order it happens |
| [botd-explained.md](botd-explained.md) | its twenty detectors, and why most check which engine you really are |
| [fingerprintjs-visitor-id.md](fingerprintjs-visitor-id.md) | why the ID changes, and why an ID that changes every run is a signal |

## Reference

| Page | Answers |
|---|---|
| [pinning.md](pinning.md) | which fingerprint fields can be pinned, and which raise if you try |

## The idea these pages keep returning to

Three things turn up on almost every page, so they are worth stating once here.

**Consistency beats rarity.** Detectors rarely ask whether a value is unusual. They
ask whether two values that must agree, do. A user agent claiming one platform on a
font set from another is caught by a comparison, not by a blocklist.

**Suppressing a signal is a signal.** A browser that refuses to answer is louder than
one that answers plainly, because refusing is rare. CreepJS literally records a
blocked probe as a lie.

**Server tells are not automation tells, and they need different fixes.** A software
WebGL renderer or a Linux font set under a Windows user agent says nothing about
automation and everything about where the browser is running. No stealth plugin
touches either.
