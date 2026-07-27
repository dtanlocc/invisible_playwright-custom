# Integrations

How to run this engine inside frameworks that already drive a browser, without
forking anything. Each page is written against the framework's current source and
says which version it was checked at, because these break quietly when an upstream
signature changes.

| Framework | Page | What it takes |
|---|---|---|
| Scrapy, via `scrapy-playwright` | [scrapy-playwright.md](scrapy-playwright.md) | a browser provider, which reaches the whole wrapper |
| Crawlee for Python | [crawlee-python.md](crawlee-python.md) | a plugin subclass for the full profile, or one line for the engine alone |
| Playwright MCP | [playwright-mcp.md](playwright-mcp.md) | two flags on Microsoft's own MCP server |
| Go, Java, C#, Ruby, Rust | [other-languages.md](other-languages.md) | the two launch options every Playwright binding already has |

## The distinction every one of these turns on

There are two halves to this package. The **engine** is a Firefox patched in its C++
source, and you point at it with `executable_path`. The **profile** is the identity,
generated from a seed and delivered as `firefox_user_prefs`.

A framework that forwards arbitrary launch options can carry both. A framework that
only exposes a "browser path" setting can carry the first and not the second, and
that matters more than it sounds: without the prefs there is no per-session identity,
so every user of that build looks the same as every other, which is its own signal.

Each page says which case it is, in those words, rather than leaving you to find out.

## Frameworks that can host this and have no page yet

Verified from source as accepting a custom Firefox binary, but not written up:
Cypress (`--browser <path>`), Crawlee for JavaScript (`launchContext.launchOptions`),
ScrapeGraphAI, CodeceptJS, TestCafe, WebdriverIO, Robot Framework's
`robotframework-browser` (which exposes a `firefoxUserPrefs` keyword directly),
SeleniumLibrary, Nightwatch (`firefox_binary` plus `moz:firefoxOptions.prefs`) and
BackstopJS (`engineOptions` forwarded verbatim).

If you use one of these and want a page for it, open an issue. If you have already
wired it, a pull request adding your page is more useful than an issue asking for
one.

## Frameworks this does not fit, and why

Some projects cannot run this engine at all today, and it is fairer to say so than to
let someone discover it after an hour:

- **Anything Chromium-only.** If a project's launch path names Chromium, or connects
  over CDP, a patched Firefox is the wrong engine and no configuration changes that.
- **Anything that only connects to a remote browser.** Prefs cannot travel down a CDP
  connection, so a remote endpoint cannot carry the profile even when it can carry
  the engine.
- **Frameworks with no way to pass a browser path at all.** Several large ones build
  their launch arguments as a fixed dictionary. There is no integration to write
  until that changes upstream, and it is not worth pretending otherwise.
