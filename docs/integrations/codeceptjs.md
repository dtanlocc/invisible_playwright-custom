# Using invisible_playwright with CodeceptJS

CodeceptJS spreads whatever you put under the browser's own key straight into
Playwright's launch options, so a `firefox` block carries both halves: the patched
binary and the seeded preferences.

Written against CodeceptJS 4.x (`lib/helper/Playwright.js`,
`_getOptionsForBrowser` returns `{ ...config[config.browser] }`) and
`invisible-playwright` 0.4.2.

CodeceptJS's own [Playwright docs](https://github.com/codeceptjs/CodeceptJS/blob/4.x/docs/playwright.md)
already mention this project as an example of pointing at a custom executable. This
page is the full wiring.

## The two values

The engine and the identity come from the Python package even though the tests are
JavaScript. Get them once:

```bash
pip install invisible-playwright
invisible-playwright fetch
invisible-playwright path    # prints the binary path
python -c "import json;from invisible_playwright import get_default_stealth_prefs;print(json.dumps(get_default_stealth_prefs(seed=1, humanize=True)))" > prefs.json
```

Regenerate `prefs.json` when you upgrade the package: the pref set moves with the
engine. Keep the seed written down next to it, because that number is the identity.

## codecept.conf.js

```js
const fs = require('fs')

exports.config = {
  helpers: {
    Playwright: {
      url: 'https://example.com',
      browser: 'firefox',
      show: false,
      firefox: {
        executablePath: '/absolute/path/from/invisible-playwright path',
        firefoxUserPrefs: JSON.parse(fs.readFileSync('prefs.json', 'utf8')),
      },
    },
  },
  tests: './*_test.js',
}
```

That is the whole integration. Everything under `firefox` is forwarded verbatim, so
any Playwright launch option belongs there too, including `proxy`.

## Your tests do not change

```js
Feature('search')

Scenario('finds a thing', async ({ I }) => {
  I.amOnPage('/')
  I.fillField('q', 'codeceptjs')
  I.click('Search')
  I.see('results')
})
```

The helper API is unchanged. That is the point of doing it at this layer.

## Three things to get right

**Do not set a user agent in the helper config.** It comes from the engine's real
version and from the same seeded profile as everything else. Overriding only that
string is the standard way to make a browser contradict itself, and CodeceptJS makes
it easy to do by accident because `userAgent` sits right next to the options above.

**One seed per identity, not per run.** A fixed seed makes a failing test
reproducible: you can tell the site changing from the browser changing. Rerolling per
run means every red test has two possible causes and no way to separate them, which
is the opposite of what a test suite is for.

**`restart` and `keepBrowserState` interact with the profile.** CodeceptJS can keep a
browser between scenarios. That is fine and usually what you want, but note the
session then accumulates cookies and storage across tests, which is a correlation
surface if the suite is pointed at a real site rather than a staging one.

## What you give up compared to driving it from Python

The same two things every non-Python route gives up, and they are worth knowing
before you pick this layer:

- **Humanised pointer motion.** The preference enables it, but the paths are drawn
  by the Python driver from the seed. From CodeceptJS the pointer still teleports.
- **Timezone and locale resolved from the proxy exit.** Those are computed at launch
  by the Python wrapper. Here you get whatever `prefs.json` was generated with, so a
  proxy in another country will disagree with the browser unless you regenerate per
  proxy.

If the suite is JavaScript and rewriting it is not on the table, this is the right
trade. If you are choosing freely and the fingerprint has to hold up against
something that looks at behaviour, drive it from Python.

## Checking it worked

Add a scenario that visits a fingerprint page and asserts on the user agent and the
WebGL renderer. The user agent should say Firefox and the version should match
`invisible-playwright version`. If the renderer comes back as a software or basic
renderer, either the prefs did not load or the machine has no GPU, and both are worth
knowing before the suite reports green.
