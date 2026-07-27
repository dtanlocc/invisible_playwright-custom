# The ChromeDriver `cdc_` variable: what it is, why renaming it is not removing it

If you have automated Chrome with Selenium and been detected, you have probably met
this check:

```js
Object.getOwnPropertyNames(document).find(k => k.startsWith('cdc_'))
```

or the same thing scanning `window`. It is a two-line test, it is in every
bot-detection script, and understanding why it works explains a lot about how this
whole category of tell comes to exist.

## What the variable is

ChromeDriver, the binary Selenium talks to, needs to run its own JavaScript inside
the page: that is how it finds elements, reads text, and executes your `execute_script`
calls. To do that it keeps some state on the page's own objects, under names derived
from a fixed string compiled into the binary. Historically they look like this:

```
cdc_adoQpoasnfa76pfcZLmcfl_Array
cdc_adoQpoasnfa76pfcZLmcfl_Promise
cdc_adoQpoasnfa76pfcZLmcfl_Symbol
```

The prefix is stable across installations because it is a literal in the executable,
which is exactly what makes it a reliable signal. A page that finds one of those
property names is not guessing: nothing else puts them there.

Note what this is not. It is not a flag someone forgot to remove, and it is not the
same class of thing as `navigator.webdriver`. It is working state that the tool needs
in order to function.

## Why the usual fix is a rename

The well-known remedy, and what `undetected-chromedriver` does, is to patch the
binary and replace that literal with a different random-looking string of the same
length. Same length matters: it is an in-place patch of a compiled file, so the
replacement has to fit.

That works against the check at the top of this page, because the check greps for
`cdc_`. It does not work against a slightly better one.

The variables are still there, still on `document`, still a set of three related
names appearing together, still matching a shape no page author would produce. A
detector that looks for *the pattern* instead of the prefix, three own properties on
`document` with a common random-looking stem and typed suffixes, finds them again.
And because the patch has to preserve length, the shape of the replacement is
constrained in ways that make it recognisable.

So: renaming raises the bar, it does not remove the surface. That distinction is the
whole point of this page, and it applies far beyond this one variable.

## The general shape of the problem

Any automation tool that needs to run code in the page needs somewhere to keep state.
The options are:

1. **Put it on page objects under a known name.** Easy, and detectable by name.
2. **Put it on page objects under a randomised name.** Harder, and detectable by
   shape.
3. **Do not put it on page objects at all.** Keep the state on the driver side of the
   boundary, or in an execution context the page cannot enumerate.

Option three is the only one that removes the surface instead of obscuring it, and
it is a design decision made long before anyone runs a detection test. It is also why
"which stealth plugin should I use" is often the wrong question: no plugin can move
state out of the page after the fact.

## Where Firefox differs, and where it does not

Firefox's automation does not use ChromeDriver, so `cdc_` does not exist there. That
is a fact about the protocol, not a virtue: Firefox's automation surfaces are
simply different ones.

What Firefox does still do by default is set `navigator.webdriver` to `true` when a
session is under automation control, because the WebDriver specification requires it.
So a stock Playwright Firefox is trivially detectable too, just by a different
two-line check, and anyone claiming Firefox is inherently undetected is selling
something.

The useful difference is architectural, not moral. Firefox's automation
protocol runs in privileged code with its own execution contexts, so the state a
driver needs does not have to live where the page can enumerate it. Whether a given
tool takes advantage of that is a separate question from whether the engine allows
it.

## What to actually check

If you are debugging a detection problem on a Chromium-based stack, check in this
order:

1. `Object.getOwnPropertyNames(document)` and the same for `window`, looking for
   groups of related unfamiliar names, not one specific prefix.
2. `navigator.webdriver`, remembering that `false` is not the same answer as
   `undefined`, and a clean browser gives the latter.
3. Whether anything you loaded has patched a built-in: print
   `Function.prototype.toString.call(navigator.__lookupGetter__('webdriver'))` and
   see whether it says `[native code]`.
4. The non-automation signals, which is usually where the real problem is by the time
   you have got this far: the GPU string, the font set, the timezone against the IP.

Number four catches more sessions than one to three combined, and it is the one
nobody checks first.

**See also:** [why setting `navigator.webdriver` to false is worse than leaving it alone](navigator-webdriver-explained.md), and [the three levels a stealth tool can work at](playwright-stealth-levels.md), since where the state lives is a level-two decision.

---

*From the notes of [invisible_playwright](https://github.com/feder-cr/invisible_playwright),
a Firefox patched at the C++ level. Firefox-based, so `cdc_` was never our problem,
but the general shape of it is everybody's.*
