# Playwright detected as a bot on one site: a checklist

A troubleshooting order for when automation gets a different page than a human does.
It is written for Playwright but almost none of it is Playwright-specific.

The order matters. Most people start at the bottom of this list, buy a better proxy,
and find out three days later that the problem was a user agent they set themselves.

## 0. Prove it is actually detection

Before anything else, open the same URL by hand from the same machine and the same
network. Not from your laptop, from the machine that runs the automation.

If the manual visit also gets the wrong page, this is not a browser fingerprint
problem: it is the IP, the ASN, or the country. Nothing in the rest of this list will
help, and the fix is a different exit.

If the manual visit works and the automated one does not, the difference is the
browser or the behaviour, and the list below is in the order that difference usually
lives.

## 1. Check what you overrode yourself

This is the most common cause and the most embarrassing one.

Every value you set by hand is a value that now has to agree with every value you did
not. A user agent claiming one platform, on a browser reporting another. A timezone
you pinned, against an IP on a different continent. A language list from your own
machine, on an exit somewhere else.

Grep your own code for `user_agent`, `locale`, `timezone_id`, `viewport`,
`extra_http_headers` and any stealth plugin you installed. Then remove all of them
and try again. If it starts working, add them back one at a time and stop at the one
that breaks it.

Detectors rarely check whether a value is unusual. They check whether two values that
should agree, do.

## 2. Check whether you are running two spoofers at once

If you use a patched browser or a stealth build **and** a JavaScript stealth plugin,
they are both answering the same questions and they will not give the same answer.
Two disguises produce a contradiction that neither produces alone.

Pick one layer. If the engine handles the fingerprint, turn off the page-level
patching and any header generator the framework offers.

## 3. Check the machine, not the browser

Open a fingerprinting page and read the report instead of the verdict. The things
that most often give away a server:

- **A software WebGL renderer.** If the GPU string mentions a basic, software or
  llvmpipe renderer, the browser has announced it is running somewhere without
  graphics hardware. No amount of property patching hides that.
- **A screen that does not exist.** Odd resolutions, a device pixel ratio that no
  real display has, an available height equal to the full height, meaning no
  taskbar.
- **Font lists that do not match the claimed platform.** Claiming Windows with a
  Linux font set is a one-line check.
- **Hardware concurrency and device memory** that pair oddly with the claimed
  machine.

None of these are automation flags. They are all "this is a datacenter" flags, and
they survive every stealth plugin ever written because they are not in JavaScript's
gift to change.

## 4. Only now, check the automation tells

`navigator.webdriver`, leftover automation globals, a headless user agent, a missing
or malformed `chrome` object on a Chromium build. These are worth checking and they
are almost never still the problem in 2026, because every tool fixes them first.

If you find one, note that setting it to `false` is not the fix: a clean browser
reports `undefined`, and `false` is a value with its own signature.

## 5. Check the behaviour

Some sites do not fingerprint at all, they watch.

A pointer that jumps from coordinate to coordinate without passing through the space
between. Keystrokes at a perfectly uniform interval. A form filled in eighty
milliseconds. A page that is never scrolled. A session with no mouse movement at all
before a click.

If the block appears only after an interaction, and only on some pages, this is the
one. It also explains blocks that arrive minutes into a session rather than at the
first request.

## 6. Check the network layer

TLS fingerprints, HTTP/2 settings frames, header order. A real browser's handshake is
distinctive and a mismatch between "I am Firefox" in the user agent and a handshake
that is not Firefox's is decisive.

You cannot fix this from JavaScript. Either the browser is real, or the request is
made by something that impersonates the handshake too.

## 7. Now consider the exit

If everything above is clean and it still fails, the IP is a reasonable next
suspicion. Datacenter ranges, an ASN with a bad reputation, an exit that a thousand
other people are using this minute, a country that does not match the rest of the
session.

It is seventh on this list, not first, because it is the expensive fix and the least
likely single cause.

## The debugging habit that saves the most time

Fix the identity so a failure is reproducible.

If every run gets a different fingerprint, a failing run tells you nothing: you
cannot tell the site changing from the machine changing. Whatever tool you use, find
its way to pin the identity across runs, and change it deliberately rather than
accidentally.

It is the single biggest difference between debugging this and guessing at it, and
it is why this project derives every surface from one seed: the same seed gives the
same machine every time, so a bisect is a bisect.

**See also:** [WebGL renderer strings](webgl-renderer-strings.md) and [why headless renders different fonts](headless-fonts-differ.md) for step three, and [what sannysoft actually checks](sannysoft-explained.md) before you trust a green table.

---

*Written while maintaining [invisible_playwright](https://github.com/feder-cr/invisible_playwright),
a Firefox patched at the C++ level driven by stock Playwright. Steps 1, 2, 3 and 5
above are all mistakes I have made.*
