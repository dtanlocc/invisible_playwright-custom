---
title: "Scraping with Playwright"
description: "Practical how-tos for real scraping problems - blocked headless browsers, infinite scroll, proxy rotation, sessions behind a login - written against a real patched Firefox driven by stock Playwright."
parent: "Guides"
has_children: true
nav_order: 8
---

# Scraping with Playwright

The rest of the Guides explain how a single surface gives you away. This group is the
other direction: a concrete task, in order, with the code that does it and the specific
thing that breaks it.

Every page here is written against a real browser rather than a generic recipe. The
launch is a two-line change from stock Playwright, the browser returned is a real
Playwright `Browser` with no wrapped subset to learn, and each how-to carries at least one
mistake we made first, measured and fixed rather than assumed.

Start with [how to scrape without getting blocked](how-to-scrape-without-getting-blocked.md)
for the model that orders the rest, then pick the task you have.
