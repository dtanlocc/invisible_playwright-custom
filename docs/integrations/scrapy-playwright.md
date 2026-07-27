# Using invisible_playwright with scrapy-playwright

There are two ways in, and they are not equivalent. Take the first one.

Written against `scrapy-playwright` 0.0.48, `invisible-playwright` 0.4.2. Both routes
below are in that released version; the first needs 0.0.48 or newer.

`scrapy-playwright`'s own documentation already names this project in
[pluggable-browser-providers.md](https://github.com/scrapy-plugins/scrapy-playwright/blob/main/docs/pluggable-browser-providers.md),
alongside patchright and camoufox, and carries a worked provider example. That page
is the reference; this one explains which route to pick and what each one costs.

## Install

```bash
pip install "scrapy-playwright>=0.0.48" invisible-playwright
```

The patched Firefox is downloaded on first launch and cached. You do not need
`playwright install firefox`: this package brings its own engine.

## Route one: a browser provider, which gets you everything

`scrapy-playwright` has a `PLAYWRIGHT_BROWSER_PROVIDER` setting and a
`BrowserProvider` interface. A provider hands back a browser you launched yourself,
so you can use this package's own class instead of reassembling its parts.

```python
# myproject/providers.py
from contextlib import AsyncExitStack

from scrapy_playwright.handler import Config, PERSISTENT_CONTEXT_PATH_KEY


class InvisibleBrowserProvider:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.stack = AsyncExitStack()

    async def start(self) -> None:
        pass

    async def launch_browser(self):
        from invisible_playwright.async_api import InvisiblePlaywright

        return await self.stack.enter_async_context(
            InvisiblePlaywright(**self.config.launch_options)
        )

    async def launch_persistent_context(self, context_kwargs: dict):
        from invisible_playwright.async_api import InvisiblePlaywright

        return await self.stack.enter_async_context(
            InvisiblePlaywright(
                profile_dir=context_kwargs[PERSISTENT_CONTEXT_PATH_KEY],
                **self.config.launch_options,
            )
        )

    async def close(self) -> None:
        await self.stack.aclose()
```

```python
# settings.py
DOWNLOAD_HANDLERS = {
    'http': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
    'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
}
TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'

PLAYWRIGHT_BROWSER_PROVIDER = 'myproject.providers.InvisibleBrowserProvider'
PLAYWRIGHT_BROWSER_TYPE = 'firefox'

# These go to InvisiblePlaywright, not to playwright.launch(). Its own arguments:
# seed, proxy, headless, humanize, locale, timezone, pin, profile_dir.
PLAYWRIGHT_LAUNCH_OPTIONS = {
    'seed': 1,
    'headless': True,
}
```

Note what `PLAYWRIGHT_LAUNCH_OPTIONS` means here: with a custom provider it is
whatever your provider passes on, so in this shape it carries **this package's**
arguments rather than Playwright's. It is the convention in the upstream example
and it is worth knowing before it surprises you.

`launch_persistent_context` is wired too, so `PLAYWRIGHT_CONTEXTS` with a persistent
path keeps cookies and storage between runs, on the profile the seed pins.

## Route two: settings only, which gets you less

If you cannot add a provider class, `PLAYWRIGHT_LAUNCH_OPTIONS` is forwarded verbatim
into `browser_type.launch()`, so you can pass the binary and the preferences directly:

```python
from invisible_playwright import ensure_binary, get_default_stealth_prefs

PLAYWRIGHT_BROWSER_TYPE = 'firefox'
PLAYWRIGHT_LAUNCH_OPTIONS = {
    'executable_path': str(ensure_binary()),
    'firefox_user_prefs': get_default_stealth_prefs(seed=1, humanize=True),
    'headless': True,
}
```

**What this route does not give you**, and the difference is not cosmetic:

- **Humanised pointer motion.** The preference turns the feature on, but the paths
  are drawn by the driver from the seed. Without the wrapper the cursor still
  teleports.
- **Timezone and locale from the exit IP.** `timezone="auto"` and `locale="auto"`
  are resolved at launch by the wrapper, against the proxy you are actually leaving
  from. Here you get whatever the prefs were generated with, so a proxy in another
  country will disagree with the browser.
- **The pin check.** The wrapper refuses to run a binary that does not match the
  config that produced the prefs. Upgrade one and not the other and nothing warns
  you.

Use route two when route one is impossible. Otherwise it is strictly less.

## The spider is unchanged either way

```python
import scrapy


class QuotesSpider(scrapy.Spider):
    name = 'quotes'

    def start_requests(self):
        yield scrapy.Request('https://quotes.toscrape.com/', meta={'playwright': True})

    def parse(self, response):
        for quote in response.css('div.quote'):
            yield {'text': quote.css('span.text::text').get()}
```

## Three things to get right

**Do not set a user agent.** Not in `USER_AGENT`, not in `DEFAULT_REQUEST_HEADERS`,
not per request. It comes from the engine's real version and the seeded profile, and
overriding only that string is the classic way to make a browser contradict itself.

**Do not run another stealth layer.** If something else patches `navigator` from
inside the page, it is now arguing with an engine that has already answered.

**One seed per identity, not per run.** A fixed seed makes a failure reproducible,
which is the difference between bisecting a problem and guessing at it. For many
identities, run several processes with different seeds instead of rerolling inside
one crawl.

## Proxies

Scrapy's proxy middleware does not reach the browser, since the browser makes the
requests. On route one, pass `proxy` in `PLAYWRIGHT_LAUNCH_OPTIONS` as this package's
own argument; on route two, as Playwright's. `socks5://` goes through the patched
proxy path inside the engine, `http(s)://` through Playwright's.

On route one, leave locale and timezone on `auto` so they follow the exit. On route
two they cannot follow anything, which is the main reason to prefer route one when a
proxy is involved at all.

## When to use something else

If the target needs Chromium, use a Chromium backend. If a page does not need
JavaScript, plain Scrapy is an order of magnitude faster and no fingerprint is
involved at all.
