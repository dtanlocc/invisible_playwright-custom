# Using invisible_playwright with Cypress, WebdriverIO and TestCafe

Three test runners, three mechanisms, and they do not all carry the same amount.
Verified from source on 2026-07-27. None of the three mentions this project, so
nothing here is a correction of somebody else's page.

| Runner | Engine | Seeded prefs | Mechanism |
|---|---|---|---|
| Cypress | yes | **yes** | `--browser <path>` plus `before:browser:launch` |
| WebdriverIO | yes | **yes** | `moz:firefoxOptions` with `binary` and `prefs` |
| TestCafe | yes | **no** | the `path:` browser provider |

Get the two values first, the same way for all three:

```bash
pip install invisible-playwright
invisible-playwright fetch
invisible-playwright path
python -c "import json;from invisible_playwright import get_default_stealth_prefs;print(json.dumps(get_default_stealth_prefs(seed=1, humanize=True)))" > prefs.json
```

## Cypress

Cypress launches Firefox through geckodriver and builds a `moz:firefoxOptions` with
`binary: browser.path` and `prefs: launchOptions.preferences`
(`packages/server/lib/browsers/firefox.ts`). Both halves are reachable: the binary
from the command line, the preferences from the launch hook.

```js
// cypress.config.js
const { defineConfig } = require('cypress')
const prefs = require('./prefs.json')

module.exports = defineConfig({
  e2e: {
    setupNodeEvents(on) {
      on('before:browser:launch', (browser, launchOptions) => {
        if (browser.family === 'firefox') {
          Object.assign(launchOptions.preferences, prefs)
        }
        return launchOptions
      })
    },
  },
})
```

```bash
npx cypress run --browser /absolute/path/from/invisible-playwright path
```

**The Cypress-specific trap:** do not set `userAgent` in the config. Cypress reads it
and writes `general.useragent.override` into the same preference set
(`firefox.ts`, the `if (ua)` branch), so it silently wins over the profile's own user
agent and produces a browser whose stated identity disagrees with everything else it
reports. Leave it unset and the engine's own value stands.

Cypress also version-sniffs a browser given by path to place it in a known family. A
patched Firefox reports a normal Firefox version, so this works, but if a future
build changed the version string, this is the step that would break first.

## WebdriverIO

The cleanest of the three. `moz:firefoxOptions` is a W3C capability and it takes both
values directly, so this is standard WebDriver rather than anything runner-specific.

```js
// wdio.conf.js
const prefs = require('./prefs.json')

exports.config = {
  capabilities: [{
    browserName: 'firefox',
    'moz:firefoxOptions': {
      binary: '/absolute/path/from/invisible-playwright path',
      prefs,
      args: ['-headless'],
    },
  }],
}
```

WebdriverIO merges its own defaults into `prefs` before launching
(`packages/wdio-utils/src/node/startWebDriver.ts`), so if you find a value not
behaving as expected, that merge is the first place to look rather than the profile.

## TestCafe

TestCafe can run any browser given a path, through its `path:` provider:

```bash
npx testcafe "path:/absolute/path/from/invisible-playwright path" tests/
```

**This carries the engine and not the identity.** A search of the TestCafe source
for a Firefox preference mechanism returns nothing: there is no supported way to
inject `firefoxUserPrefs`, so the browser reports the build's own defaults rather
than a seeded profile.

That means every run of the same build looks identical, on every machine that runs
it. For a test suite pointed at your own staging environment, that is fine and you
should not care. For anything where the identity matters, this is the wrong layer,
and one of the other two runners will do the job properly.

If you need it anyway, the workaround is the same as everywhere else: write the prefs
into a profile's `user.js` once and pass that profile's directory. It pins one
identity for that profile rather than one per session, and it is a workaround rather
than a supported path.

## What all three give up

The two things no route outside the Python wrapper carries:

- **Humanised pointer motion.** The preference enables it; the paths are drawn from
  the seed by the driver. In all three runners the pointer teleports.
- **Timezone and locale resolved from the proxy exit.** Computed at launch by the
  wrapper. Here you get whatever the prefs file was generated with.

For test suites both are usually irrelevant, because a suite normally runs against a
known environment and does not need to convince anything. Say so out loud when
choosing: the reason to use this engine in a test runner is a realistic rendering and
font stack, not evasion.
