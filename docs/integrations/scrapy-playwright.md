# Using invisible_playwright with Scrapy, through scrapy-playwright

This is the cleanest integration of the lot: two settings, no subclassing, and the
full seeded profile rather than just the binary. `scrapy-playwright` splats
`PLAYWRIGHT_LAUNCH_OPTIONS` straight into `browser_type.launch()`, so anything
Playwright accepts, it accepts.

Written against `scrapy-playwright` on `main` as of 2026-07-27
(`provider.py`: `await self.browser_type.launch(**self.config.launch_options)`),
with `invisible-playwright` 0.4.2.

`scrapy-playwright`'s own docs already mention this project in
`docs/pluggable-browser-providers.md`, as one of several Playwright-compatible
backends. This page is the part that belongs on our side: how to actually wire it.

## Install

```bash
pip install scrapy scrapy-playwright invisible-playwright
```

The patched Firefox is downloaded on first launch and cached. Note that you do not
need `playwright install firefox`: this package brings its own engine and the point
is to use it instead of the bundled one.

## settings.py

```python
from invisible_playwright import ensure_binary, get_default_stealth_prefs

DOWNLOAD_HANDLERS = {
    'http': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
    'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
}
TWISTED_REACTOR = 'twisted.internet.asyncioreactor.AsyncioSelectorReactor'

PLAYWRIGHT_BROWSER_TYPE = 'firefox'
PLAYWRIGHT_LAUNCH_OPTIONS = {
    'executable_path': str(ensure_binary()),
    # The whole identity, derived from one seed. Same seed, same machine, every run.
    'firefox_user_prefs': get_default_stealth_prefs(seed=1, humanize=True),
    'headless': True,
}
```

That is the entire integration. Both halves are present here, which is worth saying
explicitly because most integrations only manage one: `executable_path` gives you the
patched engine, and `firefox_user_prefs` gives you the seeded profile. Elsewhere the
prefs are the part that gets dropped, and a build without them means every user of
that build shares one identity.

`ensure_binary()` downloads on first call, so the first `scrapy crawl` after an
upgrade is slow. If you would rather not pay that during a run, call it once in your
deploy step.

## The spider is unchanged

```python
import scrapy


class QuotesSpider(scrapy.Spider):
    name = 'quotes'

    def start_requests(self):
        yield scrapy.Request(
            'https://quotes.toscrape.com/',
            meta={'playwright': True},
        )

    def parse(self, response):
        for quote in response.css('div.quote'):
            yield {'text': quote.css('span.text::text').get()}
```

Nothing about `meta={'playwright': True}`, page methods, or the response API changes.
The engine swap is invisible to your spider code, which is the point.

## Four things to get right

**Do not set a user agent.** Not in `DEFAULT_REQUEST_HEADERS`, not in `USER_AGENT`,
not per request. The user agent comes from the engine's real version and from the
same seeded profile as the rest of the fingerprint. Overriding only that string is
the classic way to build a browser whose stated identity and observable behaviour
disagree, and that disagreement is what a detector reads.

**Turn off any other fingerprint or stealth middleware.** If you already run
something that patches `navigator` properties from the page, it will now be arguing
with an engine that has already answered. Two independent opinions about who this
browser is are worse than either one alone.

**One seed per identity, not per run.** With `seed=1` above, every crawl is the same
machine, which is what you want when you are debugging: a failure is reproducible and
you can tell the site changing from the identity changing. If you need many
identities, run several spider processes with different seeds rather than rerolling
inside one crawl, since the launch options are read once at startup.

**`PLAYWRIGHT_LAUNCH_OPTIONS` is ignored if you connect to a remote browser.**
`scrapy-playwright` logs a warning and drops it when `cdp_url` or `connect_url` is
set. There is no way to send prefs down a CDP connection, so a remote browser cannot
carry this profile. Local launch only.

## Proxies

Scrapy's own proxy middleware does not reach the browser, since the browser makes the
requests. Put the proxy in the launch options:

```python
PLAYWRIGHT_LAUNCH_OPTIONS = {
    'executable_path': str(ensure_binary()),
    'firefox_user_prefs': get_default_stealth_prefs(seed=1, humanize=True),
    'proxy': {'server': 'http://host:port', 'username': 'u', 'password': 'p'},
    'headless': True,
}
```

`socks5://` goes through the patched proxy path inside the engine, `http://` and
`https://` through Playwright's own handling. Either way, leave locale and timezone
on their defaults: they resolve from the exit IP rather than from the machine running
Scrapy, which is what keeps the JS timezone, the language list and the IP in
agreement.

## When to use something else

If the target needs Chromium, use a Chromium backend and do not fight it. Some sites
serve different code to Firefox.

If you are crawling at high concurrency, remember you are running real browsers:
`CONCURRENT_REQUESTS` and `PLAYWRIGHT_MAX_PAGES_PER_CONTEXT` now cost hundreds of
megabytes each rather than a socket. For pages that do not need JavaScript at all,
plain Scrapy is faster by an order of magnitude and no fingerprint is involved.
