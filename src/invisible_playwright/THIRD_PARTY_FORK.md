# Playwright fork bundled in this package

This package includes and redistributes a MODIFIED copy of
[Playwright](https://github.com/microsoft/playwright), by Microsoft Corporation,
under the **Apache-2.0** license. The `invisible_playwright` code that is not
in the two folders below stays **MIT**; `pyproject.toml` declares it as
`license = "MIT AND Apache-2.0"`, because saying MIT alone would misstate what
the user receives.

## What is vendored

| folder | what it is | license |
|---|---|---|
| `_pw/` | Playwright's Python client, version **1.61.1** | Apache-2.0 (`_pw/LICENSE`) |
| `_driver/` | Playwright's Node driver | Apache-2.0 (`_driver/package/LICENSE`, `NOTICE`, `ThirdPartyNotices.txt` - upstream, untouched) |

The client's namespace is `invisible_playwright._pw` instead of `playwright`, so
it does not collide with a stock `playwright` that might be installed alongside it.

## The changes relative to upstream Playwright

They are in the driver bundle (`_driver/package/lib/coreBundle.js`), not in the client:

- **[B177]** fixed `set_content`, which in the stock driver did not wait for
  loading in the way a page driven indistinguishably needs.
- **Removed ~643 KB** of subsystems we don't use and that only widen the
  surface: android and electron support, the bidi protocol, the recorder, and
  the chromium and webkit engines (this package drives only a Firefox).
- **Neutralized `_exposeConsoleApi`**: the stock driver exposed a console API
  that a page could observe.
- **Removed `console.debug`** from the injected code, for the same reason.

## Why it is in git

Without these two folders the package **installs but does not import**: the
`launcher.py` imports from `invisible_playwright._pw`, and a wheel built from a
checkout that does not contain them raises `ImportError` on every `import
invisible_playwright`. Leaving them out of git was a broken package that only
the user would see. The full story of the decision is in the workbench, in
`docs/firefox-stealth-architecture/72-next-steps.md`, entry 23.
