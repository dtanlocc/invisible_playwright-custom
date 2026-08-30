---
title: "Testing and Troubleshooting"
description: "What to check, and in what order, when automation is detected or a preference silently does nothing - before assuming a fix worked, and before buying a better proxy."
parent: "Guides"
has_children: true
nav_order: 7
---


# Testing and Troubleshooting

The order you check things in matters more than most of the individual checks. A
green result from a shallow test and a green result from real usage are not the same
claim, and a check that only ever asserts the absence of a leak can stay green while
the feature it's supposed to protect is completely broken. This group is about
telling the difference before you ship a fix, not after.

## Verifying stealth without a false pass

- [How to test bot detection without a false pass](how-to-test-bot-detection.md) - what each public suite proves, and why a passing verdict can hide a broken feature.
- [Can You Run Playwright Without Being Detected?](can-you-run-playwright-without-being-detected.md) - what removing browser-level tells clears, and the three signals it does not fix.
- [Is Playwright Headless Detectable?](is-playwright-headless-detectable.md) - classic headless leaks its user agent, WebGL, window metrics and fonts; why output parity beats per-tell patching.
- [Does Playwright Trigger reCAPTCHA More Often?](does-playwright-trigger-recaptcha.md) - how reCAPTCHA scores fingerprint, IP, session age and behaviour, and which inputs an engine can move.
- [net::ERR_SSL_PROTOCOL_ERROR in Playwright](err-ssl-protocol-error-playwright.md) - The TLS handshake itself broke, before any certificate was evaluated; why `ignoreHTTPSErrors` does not fix it.
- [net::ERR_CONNECTION_TIMED_OUT in Playwright](err-connection-timed-out-playwright.md) - The browser's own network stack giving up, a separate mechanism from Playwright's configurable `TimeoutError`.
- [net::ERR_NETWORK_CHANGED in Playwright](err-network-changed-playwright.md) - Fires when the OS reports a network interface change mid-request; common and usually transient in CI.
- [TimeoutError: Timeout 30000ms Exceeded](playwright-timeout-30000ms-exceeded.md) - The client giving up on waiting for an action or navigation; why raising the number is usually the wrong first move.
- [Playwright "Frame Was Detached" Error](playwright-frame-was-detached-error.md) - The iframe itself was removed from the page's frame tree, usually by a framework remounting a widget.
- [Playwright "Protocol Error (Page.navigate)"](playwright-protocol-error-page-navigate.md) - An internal navigation command rejected on Chromium and Firefox alike, not the same failure as TargetClosedError.
- [Playwright Strict Mode Violation: Resolved to N Elements](playwright-strict-mode-violation.md) - Playwright refuses to guess which matching element you meant; the fix is a more specific locator.
- [Playwright "Element Is Not Attached to the DOM"](playwright-element-not-attached-to-dom.md) - A framework re-render swaps the element out in the gap between resolution and action.
- [Playwright "Subtree Intercepts Pointer Events"](playwright-element-click-intercepted.md) - Something else sits on top of the target; `force:true` clicks through it instead of finding out what.
- [Content-Security-Policy Blocks Playwright's Injected Scripts](content-security-policy-blocks-playwright-scripts.md) - A page's CSP can refuse `addInitScript`; what `bypassCSP` fixes and what it changes about the test.
- [Playwright "Executable Doesn't Exist" After Install](playwright-executable-doesnt-exist.md) - The most common first-run error, and its Docker, CI and serverless variants.
- [Playwright "Page Crashed" Error](playwright-page-crashed-error.md) - An OOM-killed content process versus an actual engine bug, and how to tell them apart.

## When you get blocked or detected

- [Playwright detected as a bot on one site: a checklist](playwright-detected-as-bot.md) - a checklist that checks the free fixes first, before buying a better proxy on day one.
- [Why Does My Playwright Script Get Blocked?](why-does-my-playwright-script-get-blocked.md) - a four-layer diagnostic across fingerprint, IP reputation, rate and quota, and behaviour.
- [Why am I blocked with a clean fingerprint?](why-blocked-with-a-clean-fingerprint.md) - you pass CreepJS, BotD and sannysoft and still get blocked; how to isolate which of four layers is failing.
- [Why Playwright Works Locally but Fails in the Cloud](why-playwright-works-locally-fails-in-cloud.md) - the same script fails on CI because the exit IP moved from residential to datacenter, not because your code changed.

## Launch, process and preference problems

- [Slow browser launch: a per-request timeout is not a budget](slow-browser-launch-timeout-budget.md) - one launch in six was randomly slow; the fix is a total step budget, not a shorter per-request timeout.
- [Playwright TargetClosedError: the causes and the fixes](playwright-targetclosederror-causes.md) - usually not a timeout; three specific Firefox and Juggler causes, their symptoms, and how to tell them apart.
- [Firefox preferences that silently do nothing](firefox-prefs-not-applying.md) - a preference you set can be silently ignored with no error; the reasons in order, and how to confirm which one you hit.

## Canvas, screenshots and fingerprint noise

- [Canvas fingerprint changes every run: use a seed](canvas-fingerprint-changes-every-run.md) - canvas, WebGL and audio hashes change each run; pass a fixed seed to make readbacks byte-identical.
- [Playwright screenshot returns noise: readback fix](playwright-screenshot-returns-noise.md) - why page.screenshot() returned a noise PNG, and the principal-split canvas readback fix that made captures clean.
