# Using invisible_playwright with Robot Framework Browser

The cleanest fit of any framework here. `Browser`'s `New Browser` keyword takes both
halves as documented named arguments, so there is no subclassing, no provider class
and no configuration dictionary to reverse-engineer.

Verified against `MarketSquare/robotframework-browser` on `main`
(`Browser/keywords/playwright_state.py`):

```python
def new_browser(
    browser: SupportedBrowsers = SupportedBrowsers.chromium,
    ...
    executablePath: str | None = None,
    firefoxUserPrefs: dict[str, str | int | float | bool] | None = None,
)
```

Written against `invisible-playwright` 0.4.2.

## The two values

The engine and the identity come from the Python package, which suits Robot Framework
since it is Python underneath anyway.

```bash
pip install robotframework-browser invisible-playwright
rfbrowser init
invisible-playwright fetch
invisible-playwright path
python -c "import json;from invisible_playwright import get_default_stealth_prefs;print(json.dumps(get_default_stealth_prefs(seed=1, humanize=True)))" > prefs.json
```

Regenerate `prefs.json` when you upgrade the package. Keep the seed written next to
it: that number is the identity, and losing it means losing the ability to reproduce
a run.

## The suite

```robotframework
*** Settings ***
Library     Browser

*** Variables ***
${BINARY}       /absolute/path/from/invisible-playwright path

*** Keywords ***
Open Stealth Browser
    ${prefs}=    Evaluate    json.load(open('prefs.json'))    modules=json
    New Browser
    ...    firefox
    ...    headless=True
    ...    executablePath=${BINARY}
    ...    firefoxUserPrefs=${prefs}

*** Test Cases ***
The page loads as a real browser
    Open Stealth Browser
    New Page    https://example.com
    Get Title    ==    Example Domain
```

`firefox` as the first argument is not optional: `New Browser` defaults to Chromium,
and pointing `executablePath` at a Firefox build while the keyword still thinks it is
launching Chromium fails in a way that is confusing to read.

## Reading the prefs without a file

If you would rather not ship `prefs.json` alongside the suite, generate them inline.
Robot Framework can call Python directly:

```robotframework
*** Keywords ***
Open Stealth Browser
    ${prefs}=    Evaluate
    ...    __import__('invisible_playwright').get_default_stealth_prefs(seed=1, humanize=True)
    ${binary}=    Evaluate    str(__import__('invisible_playwright').ensure_binary())
    New Browser    firefox    headless=True    executablePath=${binary}    firefoxUserPrefs=${prefs}
```

This has the advantage that the prefs can never drift from the installed package,
which is the failure mode a checked-in JSON file eventually produces. The cost is
that `ensure_binary()` may download on the first run of a suite, so a CI job with a
short timeout wants the `invisible-playwright fetch` step separately.

## Three things to get right

**Do not pass `userAgent`.** `New Browser` and `New Context` both accept one, and it
is exactly the value that must not be set by hand: it comes from the engine's real
version and from the same seeded profile as everything else.

**Be careful with `New Context` overrides.** `timezoneId`, `locale`, `viewport` and
`colorScheme` are all available there, and each one you set by hand is a value that
now has to agree with the profile rather than being derived from it. If you are
using a proxy, setting `timezoneId` to your own machine's zone is the classic way to
break a session that was otherwise fine.

**One seed per identity, not per suite run.** A fixed seed makes a failing test
reproducible: you can separate the site changing from the browser changing. If you
need several identities in one suite, open several browsers with different seeds
rather than rerolling.

## What this route gives up

Same as every route that is not the Python wrapper, and worth stating plainly:

- **Humanised pointer motion.** The preference switches it on, but the paths are
  drawn from the seed by the Python driver. Through Robot Framework the pointer still
  teleports between coordinates.
- **Timezone and locale from the proxy exit.** The wrapper resolves those at launch
  against the IP you are actually leaving from. Here you get whatever the prefs were
  generated with.

For a test suite this is usually the right trade, because a test suite is normally
not going through a residential proxy and does not need the pointer to be convincing.
It is the wrong trade if the suite is pointed at something that scores behaviour.

## Checking it worked

```robotframework
*** Test Cases ***
The engine is the patched one
    Open Stealth Browser
    New Page    https://example.com
    ${ua}=    Evaluate JavaScript    ${None}    () => navigator.userAgent
    Should Contain    ${ua}    Firefox
    ${gpu}=    Evaluate JavaScript    ${None}
    ...    () => { const g = document.createElement('canvas').getContext('webgl'); const d = g.getExtension('WEBGL_debug_renderer_info'); return g.getParameter(d.UNMASKED_RENDERER_WEBGL); }
    Should Not Contain    ${gpu}    Basic Render
```

The second assertion is the one people skip and should not: a basic or software
renderer means the machine has no GPU, and that is a stronger signal than anything
the automation itself leaks.
