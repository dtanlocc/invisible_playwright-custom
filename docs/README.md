# Browser fingerprinting and bot detection, from the source

Documentation for [invisible_playwright](https://github.com/feder-cr/invisible_playwright),
plus a set of standalone explainers. Each one is written against the current source of
the thing it describes, and several of them record something we got wrong first.

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
| [renderer-string-vs-render.md](renderer-string-vs-render.md) | a flag we chased in the wrong direction: the GPU you claim vs the pixels you draw |
| [webrtc-leak-proxy.md](webrtc-leak-proxy.md) | what leaks through a proxy, and why disabling WebRTC is a louder signal than the leak |
| [speech-synthesis-voices.md](speech-synthesis-voices.md) | `getVoices()` empty: the async gotcha, and the OS the voice list describes |
| [audiocontext-fingerprinting.md](audiocontext-fingerprinting.md) | the seven values that must agree, and why adding noise made us more detectable |
| [timezone-proxy-mismatch.md](timezone-proxy-mismatch.md) | timezone set and still flagged: the nine surfaces, and deriving it from the exit |
| [playwright-socks5-proxy-authentication.md](playwright-socks5-proxy-authentication.md) | the credentials are for HTTP proxies, the SOCKS request is still open upstream, and the DNS half nobody mentions |
| [ja3-ja4-tls-fingerprint.md](ja3-ja4-tls-fingerprint.md) | what the ClientHello gives away, why JA3 decayed, and why no page-level layer can touch it |
| [human-mouse-movement.md](human-mouse-movement.md) | Bezier paths are the visible half; what a page reads is whether the event says it came from a device |
| [canvas-fingerprint-noise.md](canvas-fingerprint-noise.md) | per-call randomisation is caught by reading twice, and there is a second check almost nobody knows |
| [screen-size-headless-tells.md](screen-size-headless-tells.md) | a headless browser has no display, so every screen value it reports was decided by something else |
| [playwright-docker-detection.md](playwright-docker-detection.md) | the container starts fine and still gets a different page, in six places at once |
| [hardware-concurrency-device-memory.md](hardware-concurrency-device-memory.md) | three one-line reads, checked against each other and from a worker |
| [tostring-native-code-detection.md](tostring-native-code-detection.md) | every override is a function, and every function carries its source |
| [recaptcha-v3-score.md](recaptcha-v3-score.md) | why a fresh profile scores badly, and why a deprecated cookie is worse than a missing one |
| [execution-context-destroyed.md](execution-context-destroyed.md) | the usual race condition, and the case where a challenge redirected you mid-evaluation |
| [debugger-timing-detection.md](debugger-timing-detection.md) | four leaks from the automation layer, and the one that ran in the page realm before the page |
| [browser-extension-fingerprint.md](browser-extension-fingerprint.md) | web-accessible resources, what it does to the DOM, and the traces any override leaves |
| [headless-vs-headful.md](headless-vs-headful.md) | what actually differs between the modes, and running headed but hidden |
| [webgl-parameters-are-identical.md](webgl-parameters-are-identical.md) | ANGLE clamps to the feature level, so a flagship and an old integrated chip report the same block |
| [persistent-profiles.md](persistent-profiles.md) | storageState vs a profile, the seed pairing rule, and the permission that undoes WebRTC masking |
| [css-media-query-fingerprinting.md](css-media-query-fingerprinting.md) | what media features expose, and the system-colour palette that gives away the host OS |
| [codec-fingerprinting.md](codec-fingerprinting.md) | codec support identifies the build and platform; powerEfficient identifies the machine |
| [bfcache-pageshow-persisted.md](bfcache-pageshow-persisted.md) | why persisted is always false under automation, and what turning it back on costs |
| [playwright-user-agent.md](playwright-user-agent.md) | what the string has to agree with, and why rotation links sessions instead of separating them |
| [browser-use-detection.md](browser-use-detection.md) | Chrome/CDP only, what configuration reaches, and the agent rhythm no fingerprint work fixes |
| [ai-browser-agents-stealth.md](ai-browser-agents-stealth.md) | five agent frameworks verified from their source, the CDP split, and the tell specific to agent pacing |
| [how-to-test-bot-detection.md](how-to-test-bot-detection.md) | what each public suite proves, why a green result can mean the feature is broken, and the method that catches it |
| [playwright-proxy-per-context.md](playwright-proxy-per-context.md) | what a context separates, what it cannot, and the timezone mismatch the recommended pattern creates |
| [permissions-api-consistency.md](permissions-api-consistency.md) | the notification mismatch, the permission set as a fingerprint, and the grant that disables WebRTC masking |
| [service-workers-storage-partitioning.md](service-workers-storage-partitioning.md) | what partitioning changed, why a worker outlives your cookie clear, and what a context does not separate |
| [web-workers-fingerprint.md](web-workers-fingerprint.md) | the two-line test that finds any page-level tool ceiling, and why OffscreenCanvas bypasses element hooks |
| [webrtc-ice-candidate-spoofing.md](webrtc-ice-candidate-spoofing.md) | what has to be replaced, the two ways to do it, and the three fields we shipped wrong before getting them right |
| [firefox-vs-chromium-antidetect.md](firefox-vs-chromium-antidetect.md) | four structural arguments for Firefox, the one serious argument against it, and what neither fixes |
| [chromium-is-not-chrome.md](chromium-is-not-chrome.md) | what Playwright actually ships, the two capability checks, and why spoofing the UA makes it a provable lie |
| [client-hints-sec-fetch.md](client-hints-sec-fetch.md) | Sec-CH-UA against the user agent against userAgentData, and why Firefox not sending them is correct |
| [crawl4ai-stealth-custom-browser.md](crawl4ai-stealth-custom-browser.md) | the one missing field, the undocumented adapter seam, and the workaround with its cost |
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
