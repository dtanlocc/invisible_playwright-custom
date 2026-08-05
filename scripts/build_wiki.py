#!/usr/bin/env python3
"""Render the Jekyll docs/ tree into a GitHub wiki checkout.

Usage: build_wiki.py <docs_dir> <out_dir>

A GitHub wiki is a flat set of <Page>.md files with no Jekyll front matter and a
_Sidebar.md for navigation. This converter, for every docs/*.md:
  - strips the YAML front matter (the body already starts with the H1),
  - rewrites internal links [x](slug.md[#a]) -> [x](slug[#a]) (wiki has no .md),
  - names the page by its slug (stable URLs matching the docs site), except
    index.md -> Home.md (the wiki landing page),
and then generates _Sidebar.md mirroring the parent/has_children/nav_order tree.
"""
import os, re, sys

DOCS = sys.argv[1]
OUT = sys.argv[2]

def parse(path):
    t = open(path, encoding="utf-8").read()
    fm, body = {}, t
    m = re.match(r'^---\n(.*?)\n---\n?(.*)$', t, re.S)
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r'([A-Za-z_]+):\s*(.*?)\s*$', line)
            if mm:
                v = mm.group(2)
                if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                    v = v[1:-1]
                fm[mm.group(1)] = v
        body = m.group(2)
    return fm, body.lstrip("\n")

pages = {}
for f in sorted(os.listdir(DOCS)):
    if not f.endswith(".md"):
        continue
    slug = f[:-3]
    pages[slug] = parse(os.path.join(DOCS, f))

valid = set(pages.keys())

def rewrite(body):
    def repl(m):
        target, anchor = m.group(1), (m.group(2) or "")
        # only rewrite links that point at a real doc page
        if target in valid:
            return "](" + ("Home" if target == "index" else target) + anchor + ")"
        return m.group(0)
    return re.sub(r'\]\(([a-z0-9\-]+)\.md(#[A-Za-z0-9\-]+)?\)', repl, body)

os.makedirs(OUT, exist_ok=True)
written = 0
for slug, (fm, body) in pages.items():
    name = "Home" if slug == "index" else slug
    open(os.path.join(OUT, name + ".md"), "w", encoding="utf-8", newline="\n").write(rewrite(body) + "\n")
    written += 1

def title_of(slug):
    return pages[slug][0].get("title", slug)

def link(slug):
    return "[%s](%s)" % (title_of(slug), "Home" if slug == "index" else slug)

def children_of(group_title):
    kids = [(s, fm) for s, (fm, b) in pages.items() if fm.get("parent") == group_title]
    kids.sort(key=lambda x: int(x[1].get("nav_order", "999")))
    return kids

toplevel = [(s, fm) for s, (fm, b) in pages.items() if not fm.get("parent") and s != "index"]
toplevel.sort(key=lambda x: int(x[1].get("nav_order", "999")))

lines = ["### " + link("index"), ""]
for slug, fm in toplevel:
    t = title_of(slug)
    lines.append("**%s**" % t)
    for cs, cfm in children_of(t):
        if cfm.get("has_children") == "true":
            lines.append("- %s" % link(cs))
            for gs, gfm in children_of(cfm.get("title", cs)):
                lines.append("  - %s" % link(gs))
        else:
            lines.append("- %s" % link(cs))
    lines.append("")
open(os.path.join(OUT, "_Sidebar.md"), "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")

print("wrote %d pages + _Sidebar.md to %s" % (written, OUT))
