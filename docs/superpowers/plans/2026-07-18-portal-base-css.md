# Portal base stylesheet + `web_include_css` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a globally-injected, bleed-safe portal stylesheet (`web_include_css`), resolve the `.wide-layout-wrapper` conflict to one definition, lift the small set of genuinely-shared portal-unique rules, and land the two low-risk CSS-consistency fixes (TPL-3, TPL-4 Case A).

**Architecture:** Add a `web_include_css` hook (already a live merged list in this frappe: `['erpnext-web.bundle.css']`) pointing at a new hand-written `portal_base.css`. Because that sheet loads on *every* website page, it contains **only** verenigingen-portal-unique class selectors with byte-identical bodies — never framework/Bootstrap names — so it cannot restyle frappe's own pages. Verification is server-side page rendering via `frappe.utils.get_html_for_route`, run as a committed re-runnable script through `bench execute`.

**Tech Stack:** Frappe v16 website hooks (`web_include_css`), Jinja templates, plain CSS, Python verification harness, Playwright (visual spot-check only).

Design: `docs/superpowers/specs/2026-07-18-portal-base-css-design.md`.

## Global Constraints

- **Bleed-safety rule (load-bearing):** `portal_base.css` may contain ONLY (a) verenigingen-portal-unique class selectors — never Bootstrap/frappe names (`.btn`, `.btn-primary`, `.form-group`, `.form-control`, `.alert*`, `.card*`, `.page-header`, `.container`, `.row`, `.badge`, `.hidden`, `.loading`), never bare element selectors, never `!important` element overrides — AND (b) rules byte-identical across every current occurrence.
- **`.wide-layout-wrapper` canonical body** (owner decision — uniform 1600px):
  ```css
  .wide-layout-wrapper {
      width: 90vw;
      max-width: 1600px;
      margin-left: calc(-45vw + 50% - 2.5vw);
      margin-right: calc(-45vw + 50% + 2.5vw);
      padding: 0 2rem;
      box-sizing: border-box;
  }
  @media (max-width: 1200px) {
      .wide-layout-wrapper {
          width: 95vw;
          margin-left: calc(-47.5vw + 50% - 2.5vw);
          margin-right: calc(-47.5vw + 50% + 2.5vw);
          padding: 0 1rem;
      }
  }
  ```
- **Symlinks:** `templates/pages/me.html` and `me.py` are git symlinks to `member_portal.*`. NEVER edit `me.*` directly (writes are refused); editing `member_portal.html` covers both routes.
- **Asset path:** hook path is `/assets/verenigingen/css/portal_base.css`; the source file lives at `verenigingen/public/css/portal_base.css` (frappe symlinks `public/` → `/assets/verenigingen/`).
- **Verification invocation:** `cd ~/frappe-bench && bench --site veg11.veganisme.org execute verenigingen.tests.portal_css.verify_portal_base_css.run`. veg11 is used for **rendering/inspection only** (its real data gives best fidelity); do NOT run `bench run-tests` on veg11.
- **Commit style:** Conventional Commits; branch `refactor/portal-base-css` (already created).
- **Deferred to a follow-up (do NOT do here):** TPL-4 Case B — `my_dues_schedule.html`, `membership_adjustment.html`, `volunteer/expenses.html` currently render with NO tailwind; adding `super()` restores it (a real visual change) and needs per-page review.

---

### Task 1: Hook + `portal_base.css` + verification harness (assert injection & no bleed)

**Files:**
- Create: `verenigingen/public/css/portal_base.css`
- Create: `verenigingen/tests/portal_css/__init__.py`
- Create: `verenigingen/tests/portal_css/verify_portal_base_css.py`
- Modify: `verenigingen/hooks/assets.py` (add `web_include_css`)
- Modify: `verenigingen/hooks/__init__.py:21-26` (re-export it)

**Interfaces:**
- Produces: `verenigingen.tests.portal_css.verify_portal_base_css.run()` — renders portal pages as the appropriate user, prints a result table, and raises `AssertionError` on any violation (missing sheet link, bleed selector, inline wrapper survivor). Later tasks re-run it unchanged.

- [ ] **Step 1: Write the harness (the failing test first).**

Create `verenigingen/tests/portal_css/__init__.py` (empty file).

Create `verenigingen/tests/portal_css/verify_portal_base_css.py`:

```python
"""Re-runnable verification for portal_base.css (TPL-1/3/4 slice).

Run:  bench --site veg11.veganisme.org execute \
      verenigingen.tests.portal_css.verify_portal_base_css.run
"""
import glob
import os
import re

import frappe
from frappe.utils import get_html_for_route

PORTAL_CSS_LINK = "/assets/verenigingen/css/portal_base.css"

# (route, who) — who in {"admin","member","guest"}
PAGES = [
    ("member_portal", "member"),
    ("chapter_dashboard", "admin"),
    ("mollie_payments_debug", "admin"),
    ("mollie_payment_processing", "admin"),
    ("ponto_api_debug", "admin"),
    ("admin_tools", "admin"),
    ("board/document_upload", "admin"),
    ("board/document_browser", "admin"),
    ("volunteer/dashboard", "member"),
    ("address_change", "member"),
    ("contact_request", "member"),
    ("my_teams", "member"),
]

# Framework/Bootstrap class names that must never appear in portal_base.css.
FRAMEWORK = {
    "btn", "btn-primary", "btn-secondary", "btn-success", "btn-danger", "btn-warning",
    "btn-info", "btn-default", "btn-link", "btn-sm", "btn-lg", "btn-block", "btn-group",
    "form-group", "form-control", "form-label", "form-check", "form-select", "form-row",
    "form-text", "alert", "alert-success", "alert-danger", "alert-warning", "alert-info",
    "alert-primary", "card", "card-body", "card-header", "card-footer", "card-title",
    "container", "row", "col", "badge", "table", "nav", "navbar", "modal", "dropdown",
    "list-group", "page-header", "page-content", "input-group", "text-muted", "d-flex",
    "d-none", "d-block", "hidden", "loading",
}


def _member_user():
    rows = frappe.get_all("Member", filters={"user": ["!=", ""]}, fields=["user"], limit=1)
    return rows[0].user if rows else "Administrator"


def _render(route, who):
    user = {"admin": "Administrator", "guest": "Guest", "member": _member_user()}[who]
    frappe.set_user(user)
    try:
        return get_html_for_route(route)
    finally:
        frappe.set_user("Administrator")


def _sheet_selectors():
    path = frappe.get_app_path("verenigingen", "public", "css", "portal_base.css")
    css = open(path, encoding="utf-8").read()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return set(re.findall(r"\.([A-Za-z][\w-]*)\s*\{", css)) | set(
        re.findall(r"\.([A-Za-z][\w-]*)[\s,:]", css)
    )


def _frappe_website_classes():
    base = os.path.join(frappe.utils.get_bench_path(), "sites", "assets", "frappe", "dist", "css")
    classes = set()
    for f in glob.glob(os.path.join(base, "website.bundle.*.css")):
        css = open(f, encoding="utf-8", errors="replace").read()
        classes |= set(re.findall(r"\.([A-Za-z][\w-]*)", css))
    return classes


def run():
    errors = []

    # --- B. Bleed disjointness (static) ---
    sel = _sheet_selectors()
    print("portal_base.css selectors:", sorted(sel))
    hits = sel & FRAMEWORK
    if hits:
        errors.append(f"BLEED: framework-named selectors in portal_base.css: {sorted(hits)}")
    fw = _frappe_website_classes()
    if fw:
        overlap = sel & fw
        if overlap:
            errors.append(f"BLEED: selectors also used by frappe website.bundle.css: {sorted(overlap)}")
    else:
        print("WARN: frappe website.bundle.*.css not found; skipped compiled-CSS overlap check")

    # --- B. Guest/non-portal page must not contain any sheet selector as a class ---
    login_html = _render("login", "guest")
    login_classes = set(re.findall(r'class="([^"]*)"', login_html))
    login_tokens = set(tok for c in login_classes for tok in c.split())
    guest_hits = sel & login_tokens
    if guest_hits:
        errors.append(f"BLEED: /login uses sheet selectors: {sorted(guest_hits)}")

    # --- A. Render assertions on portal pages ---
    print(f"\n{'route':32} {'ok':>3} {'sheet':>6} {'inlineWrap':>10}")
    for route, who in PAGES:
        try:
            html = _render(route, who)
            ok = "<head" in html.lower() and len(html) > 2000
        except Exception as e:  # noqa: BLE001
            print(f"{route:32} {'ERR':>3}  ({type(e).__name__}: {e})")
            errors.append(f"RENDER: {route} raised {type(e).__name__}: {e}")
            continue
        has_sheet = PORTAL_CSS_LINK in html
        inline_wrap = ".wide-layout-wrapper" in html and "<style" in html and \
            bool(re.search(r"<style[^>]*>[^<]*\.wide-layout-wrapper", html, re.S))
        print(f"{route:32} {str(ok):>3} {str(has_sheet):>6} {str(inline_wrap):>10}")
        if not ok:
            errors.append(f"RENDER: {route} did not render a full page")
        if ok and not has_sheet:
            errors.append(f"INJECT: {route} missing {PORTAL_CSS_LINK}")

    if errors:
        raise AssertionError("VERIFY FAILED:\n  " + "\n  ".join(errors))
    print("\nVERIFY OK")
```

- [ ] **Step 2: Run the harness — expect FAIL (no hook, no sheet yet).**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute \
  verenigingen.tests.portal_css.verify_portal_base_css.run
```
Expected: raises — `portal_base.css` does not exist (the `_sheet_selectors()` open() fails) OR, if it gets past that, `INJECT: ... missing /assets/verenigingen/css/portal_base.css`. Either way, non-zero / traceback. This proves the harness detects the missing sheet.

- [ ] **Step 3: Create `portal_base.css`.**

Create `verenigingen/public/css/portal_base.css`:

```css
/*
 * portal_base.css — shared verenigingen portal styles.
 *
 * Injected on EVERY website page via the web_include_css hook. Therefore this
 * file MUST contain ONLY verenigingen-portal-unique class selectors with
 * byte-identical bodies lifted from the templates. Never add framework/
 * Bootstrap names (.btn, .form-group, .alert, .card, .page-header, .hidden,
 * .loading, ...), bare element selectors, or !important element overrides —
 * they would restyle frappe's own website pages. See
 * docs/superpowers/specs/2026-07-18-portal-base-css-design.md.
 */

/* Wide layout wrapper — breaks portal content out of Frappe's narrow container.
   Canonical single definition; replaces 12 drifting inline copies. */
.wide-layout-wrapper {
    width: 90vw;
    max-width: 1600px;
    margin-left: calc(-45vw + 50% - 2.5vw);
    margin-right: calc(-45vw + 50% + 2.5vw);
    padding: 0 2rem;
    box-sizing: border-box;
}

@media (max-width: 1200px) {
    .wide-layout-wrapper {
        width: 95vw;
        margin-left: calc(-47.5vw + 50% - 2.5vw);
        margin-right: calc(-47.5vw + 50% + 2.5vw);
        padding: 0 1rem;
    }
}

/* Admin/debug console output (mollie_payments_debug, mollie_payment_processing,
   ponto_api_debug). Byte-identical across all three. */
.result-area {
    background: #000;
    color: #0f0;
    border: 2px solid #000;
    padding: 1rem;
    margin-top: 1rem;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.875rem;
    white-space: pre-wrap;
    max-height: 24rem;
    overflow-y: auto;
}

.form-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 1rem;
}

.api-mode-box {
    margin-top: 1rem;
    padding: 0.75rem 1rem;
    border: 2px solid #000;
    background: color-mix(in srgb, var(--brand-warning) 20%, transparent);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.02em;
}
```

- [ ] **Step 4: Register the hook.**

In `verenigingen/hooks/assets.py`, after the `web_include_js = [...]` block (around line 31), add:

```python
# CSS files loaded on web pages (www/ and templates/pages/).
# NOTE: injected on EVERY website page — portal_base.css is bleed-safe by
# construction (portal-unique class selectors only). See the file header.
web_include_css = [
    "/assets/verenigingen/css/portal_base.css",
]
```

In `verenigingen/hooks/__init__.py`, change the import block at lines 21-26 to add `web_include_css`:

```python
from verenigingen.hooks.assets import (
    app_include_css,
    app_include_js,
    email_css,
    web_include_css,
    web_include_js,
)
```

- [ ] **Step 5: Clear cache so the new hook + asset resolve.**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache
```
Then sanity-check the hook resolves:
```bash
bench --site veg11.veganisme.org execute frappe.get_hooks --kwargs '{"hook":"web_include_css"}'
```
Expected: a list that now includes `/assets/verenigingen/css/portal_base.css` (alongside `erpnext-web.bundle.css`).

- [ ] **Step 6: Run the harness — expect PASS.**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute \
  verenigingen.tests.portal_css.verify_portal_base_css.run
```
Expected: prints the selector list + per-page table with `sheet=True` on every rendered page, and ends `VERIFY OK`. If any page shows `sheet=False`, the hook is not injecting — stop and debug before continuing. If a lifted selector (`result-area`/`form-grid`/`api-mode-box`) is flagged as a BLEED overlap with frappe's website CSS, remove that one rule from `portal_base.css` and leave its inline copies (the wrapper is the essential lift); re-run.

- [ ] **Step 7: Commit.**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/public/css/portal_base.css verenigingen/hooks/assets.py \
  verenigingen/hooks/__init__.py verenigingen/tests/portal_css/
git commit -m "feat(portal): add web_include_css + bleed-safe portal_base.css with verify harness"
```

---

### Task 2: Consolidate `.wide-layout-wrapper` — delete 12 inline copies

**Files (each: remove the `.wide-layout-wrapper` base rule AND its `@media (max-width: 1200px)` sibling from the inline `<style>`):**
- `templates/pages/member_portal.html` (covers `me.html` via symlink)
- `templates/pages/chapter_dashboard.html`
- `templates/pages/mollie_payment_processing.html`
- `templates/pages/mollie_payments_debug.html`
- `templates/pages/mollie_bulk_payment_creation.html`
- `templates/pages/mollie_subscription_recreation.html`
- `templates/pages/board/document_browser.html` (outlier: was `max-width:1400px`, `margin: calc(-45vw + 50%)`)
- `templates/pages/board/document_upload.html` (outlier: was `max-width:1200px`)
- `templates/pages/ponto_api_debug.html` (outlier: was `max-width:1400px`)
- `templates/pages/volunteer/expenses.html`
- `templates/pages/volunteer/expense_claim_new.html`
- `templates/pages/volunteer/dashboard.html`

**Interfaces:**
- Consumes: harness from Task 1.

**Margin unification note (surfaced by Task 1 review):** most inline copies use
`margin: calc(-45vw + 50% - 2.5vw / + 2.5vw)`, but `mollie_bulk_payment_creation.html`,
`board/document_browser.html`, and `board/document_upload.html` use the shorter
`calc(-45vw + 50%)` (no `∓ 2.5vw`). Deleting all copies unifies them to the canonical margins — an
intended consequence of the owner's "force uniform" decision, but it shifts those 3 pages'
horizontal centering by ~2.5vw (on top of the max-width widening for the 2 board pages). This is a
4th visually-changed page (`mollie_bulk_payment_creation`) beyond the documented widenings — it is
covered by the Task 6 screenshot review. `mollie_payment_processing.html` and
`mollie_payments_debug.html` used `padding:0` on the wrapper; consolidation adds the canonical
`padding:0 2rem` — a minor inset on those 2 admin/debug pages, within the uniform decision.

- [ ] **Step 1: Confirm the survivor count is 12 (13 minus the me.html symlink) before editing.**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen/verenigingen
grep -rln "^\.wide-layout-wrapper {\|^    \.wide-layout-wrapper {" templates/pages | grep -v "/me.html"
```
Expected: the 12 files above (the indented match catches `volunteer/dashboard.html` and `volunteer/expense_claim_new.html` where the rule sits inside the block with extra indentation).

- [ ] **Step 2: Delete the inline wrapper rule + its media sibling in each of the 12 files.**

For each file use the Edit tool to remove the whole `.wide-layout-wrapper { ... }` rule and the immediately-following `@media (max-width: 1200px) { .wide-layout-wrapper { ... } }` block. The canonical text is in Global Constraints; the 3 outliers differ only in `max-width`/`margin` values — delete them regardless of exact values. Leave the surrounding `<style>` element and all other rules intact. Do NOT touch `me.html`.

- [ ] **Step 3: Verify zero inline definitions remain.**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen/verenigingen
grep -rn "wide-layout-wrapper {" templates/pages www | grep -v "/me.html"
```
Expected: no output (the class is still *referenced* as `class="wide-layout-wrapper"` in markup — that's correct — but no longer *defined* in any inline `<style>`).

- [ ] **Step 4: Add the inline-wrapper assertion to the harness and run it.**

In `verify_portal_base_css.py`, inside `run()`'s page loop, promote the existing `inline_wrap` observation to a hard error. Change:
```python
        if ok and not has_sheet:
            errors.append(f"INJECT: {route} missing {PORTAL_CSS_LINK}")
```
to:
```python
        if ok and not has_sheet:
            errors.append(f"INJECT: {route} missing {PORTAL_CSS_LINK}")
        if ok and inline_wrap:
            errors.append(f"WRAPPER: {route} still defines .wide-layout-wrapper inline")
```
Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache && \
  bench --site veg11.veganisme.org execute \
  verenigingen.tests.portal_css.verify_portal_base_css.run
```
Expected: table shows `inlineWrap=False` on every page; ends `VERIFY OK`.

- [ ] **Step 5: Commit.**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/templates/pages verenigingen/tests/portal_css/verify_portal_base_css.py
git commit -m "refactor(portal): consolidate .wide-layout-wrapper into portal_base.css (uniform 1600px)"
```

---

### Task 3: Delete lifted-rule inline copies (`.result-area`, `.form-grid`, `.api-mode-box`)

**Files:** `templates/pages/mollie_payments_debug.html`, `templates/pages/mollie_payment_processing.html`, `templates/pages/ponto_api_debug.html`.

- [ ] **Step 1: Re-confirm byte-identity before deleting (equivalence check C).**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen/verenigingen
for f in mollie_payments_debug mollie_payment_processing ponto_api_debug; do
  for sel in result-area form-grid api-mode-box; do
    awk -v s=".$sel" 'index($0,s" {")==1{p=1} p{print} p&&/^}/{exit}' templates/pages/$f.html \
      | tr -d '[:space:]' | md5sum | cut -c1-8 | tr '\n' ' '
  done; echo "  <= $f"
done
```
Expected: identical triplet on each row (`badcc651 97c7c64f 21120df5`), matching `portal_base.css`. If any differs, do NOT delete that rule from that file — investigate.

- [ ] **Step 2: Delete the three inline rules from each of the 3 files** with the Edit tool (remove the whole `.result-area { ... }`, `.form-grid { ... }`, `.api-mode-box { ... }` rules; leave everything else).

- [ ] **Step 3: Verify none remain inline.**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen/verenigingen
grep -rn "^\.result-area {\|^\.form-grid {\|^\.api-mode-box {" templates/pages
```
Expected: no output.

- [ ] **Step 4: Run the harness — expect PASS** (pages still render, sheet present).

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache && \
  bench --site veg11.veganisme.org execute \
  verenigingen.tests.portal_css.verify_portal_base_css.run
```
Expected: `VERIFY OK`.

- [ ] **Step 5: Commit.**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/templates/pages
git commit -m "refactor(portal): lift shared .result-area/.form-grid/.api-mode-box into portal_base.css"
```

---

### Task 4: TPL-3 — 4 admin tools use the `brand_css()` macro

**Files:** `templates/pages/admin_tools.html`, `mollie_payments_debug.html`, `mollie_payment_processing.html`, `ponto_api_debug.html`. Each currently has, near the top, the line:
`<link href="/css/brand_colors.css?v={{ frappe.utils.now() }}" rel="stylesheet">` — byte-identical to what `templates/macros/brand_css.html::brand_css()` emits.

- [ ] **Step 1: In each file, replace the hand-copied `<link>` with the macro.**

Replace the line
```
<link href="/css/brand_colors.css?v={{ frappe.utils.now() }}" rel="stylesheet">
```
with
```
{% from "templates/macros/brand_css.html" import brand_css %}
{{ brand_css() }}
```
(Place the `{% from %}` import at the top of the template body / inside the same block the link was in. If the template already imports `brand_css`, only add the `{{ brand_css() }}` call.)

- [ ] **Step 2: Assert the brand link still renders on all 4 pages.** All four routes are already in the harness `PAGES` list (`admin_tools`, `mollie_payments_debug`, `mollie_payment_processing`, `ponto_api_debug`, all `"admin"`). Add a brand-link assertion to the harness so a Jinja import error or a dropped call is caught. In `run()`, inside the page loop after the `has_sheet` computation, add:
```python
        if ok and route in ("admin_tools", "mollie_payments_debug",
                            "mollie_payment_processing", "ponto_api_debug"):
            if html.count("/css/brand_colors.css") != 1:
                errors.append(f"BRAND: {route} brand_colors.css link count != 1")
```
Because `brand_css()` emits a string byte-identical to the old hand-copied `<link>`, a successful render with exactly one brand link proves equivalence. Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache
bench --site veg11.veganisme.org execute verenigingen.tests.portal_css.verify_portal_base_css.run
```
Expected: all 4 render `ok=True`; `VERIFY OK`.

- [ ] **Step 3: Commit.**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/templates/pages verenigingen/tests/portal_css/verify_portal_base_css.py
git commit -m "refactor(portal): route 4 admin tools through the brand_css macro (TPL-3)"
```

---

### Task 5: TPL-4 Case A — restore `super()` on 4 tailwind-linked children

**Files (each extends `templates/base_portal.html` and overrides `head_include` WITHOUT `super()`, re-linking tailwind):**
- `templates/pages/address_change.html`
- `templates/pages/contact_request.html`
- `templates/pages/my_teams.html`
- `templates/pages/volunteer/dashboard.html`

`super()` here resolves to base_portal's `head_include` = `{{ head_include or "" }}` + the tailwind link, so adding `super()` and removing the child's own tailwind link yields tailwind exactly once with no visual change.

- [ ] **Step 1: In each of the 4 files, edit the `head_include` block:** insert `{{ super() }}` as the first line inside the block, and delete the child's own `<link href="/assets/verenigingen/css/tailwind.css" rel="stylesheet">` line. Keep the `brand_css` import/call and the `<style>` block. Example (`address_change.html`):

Before:
```jinja
{% block head_include %}
<link href="/assets/verenigingen/css/tailwind.css" rel="stylesheet">
{% from "templates/macros/brand_css.html" import brand_css %}
{{ brand_css() }}
<style>
```
After:
```jinja
{% block head_include %}
{{ super() }}
{% from "templates/macros/brand_css.html" import brand_css %}
{{ brand_css() }}
<style>
```

- [ ] **Step 2: Verify tailwind is linked exactly once on each page.**

Add a temporary probe or extend the harness: for each of the 4 routes, render and assert `html.count('/assets/verenigingen/css/tailwind.css') == 1` and `PORTAL_CSS_LINK in html`. Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache
bench --site veg11.veganisme.org execute verenigingen.tests.portal_css.verify_portal_base_css.run
```
Expected: the 4 pages still render (`ok=True`, `sheet=True`); tailwind link count is 1. If any page renders as `ERR` for Administrator, it requires a member context — it is already rendered as `member` in `PAGES` for `address_change`/`contact_request`/`my_teams`/`volunteer/dashboard`.

- [ ] **Step 3: Commit.**

```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/templates/pages
git commit -m "refactor(portal): restore super() + drop duplicate tailwind link on 4 base_portal children (TPL-4 Case A)"
```

---

### Task 6: Visual spot-check (Playwright) + final full harness run

**Goal:** Human confirmation of the pages that change visually (the 3 widened wrapper pages) plus representative pages, and a guest-page bleed screenshot.

**Files:**
- Create: `verenigingen/tests/portal_css/dump_html.py` (render → save standalone HTML for screenshotting).

- [ ] **Step 1: Render target pages to standalone HTML** via a `bench execute` helper. Create `verenigingen/tests/portal_css/dump_html.py`:
```python
import os
import re

import frappe
from frappe.utils import get_html_for_route

OUT = "/tmp/portal_css_shots"
BASE = "https://veg11.veganisme.org"
# (route, who) — widened pages, representative pages, a Case-A page, and guest bleed page
TARGETS = [
    ("board/document_upload", "admin"), ("board/document_browser", "admin"),
    ("ponto_api_debug", "admin"), ("mollie_bulk_payment_creation", "admin"),
    ("member_portal", "member"), ("chapter_dashboard", "admin"),
    ("volunteer/dashboard", "member"), ("address_change", "member"),
    ("login", "guest"),
]


def _user(who):
    if who == "member":
        r = frappe.get_all("Member", filters={"user": ["!=", ""]}, fields=["user"], limit=1)
        return r[0].user if r else "Administrator"
    return {"admin": "Administrator", "guest": "Guest"}[who]


def run():
    os.makedirs(OUT, exist_ok=True)
    for route, who in TARGETS:
        frappe.set_user(_user(who))
        try:
            html = get_html_for_route(route)
        finally:
            frappe.set_user("Administrator")
        # rewrite root-relative asset URLs to absolute so file:// can load them
        html = re.sub(r'(href|src)="(/[^"]*)"', rf'\1="{BASE}\2"', html)
        name = route.replace("/", "_") + ".html"
        open(os.path.join(OUT, name), "w", encoding="utf-8").write(html)
        print("wrote", name)
```
Run: `cd ~/frappe-bench && bench --site veg11.veganisme.org execute verenigingen.tests.portal_css.dump_html.run`

- [ ] **Step 2: Screenshot each** with local headless chromium:
```bash
cd ~/frappe-bench/apps/verenigingen
for f in /tmp/portal_css_shots/*.html; do
  npx playwright screenshot --full-page "file://$f" "${f%.html}.png"
done
```

- [ ] **Step 3: Review the PNGs together.** Confirm: the 3 widened pages look correct at 1600px; representative pages unchanged; `/login` shows no green-on-black or wide-wrapper artifacts (bleed check, visual).

- [ ] **Step 4: Final harness run + branch summary.**
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache
bench --site veg11.veganisme.org execute verenigingen.tests.portal_css.verify_portal_base_css.run
cd apps/verenigingen && git log --oneline refactor/portal-base-css ^develop
```
Expected: `VERIFY OK`; commits from Tasks 1-5 listed.

- [ ] **Step 5: commit the screenshot helper.**
```bash
cd ~/frappe-bench/apps/verenigingen
git add verenigingen/tests/portal_css/dump_html.py
git commit -m "test(portal): add dump_html helper for portal CSS screenshot review"
```
Do NOT commit the PNGs or the `/tmp/portal_css_shots` output.

---

## Notes for the implementer

- If the harness reports a page as `ERR` under Administrator, that page likely requires a Member link. Move it to `"member"` in `PAGES` (rendered as a real member user) rather than forcing Administrator.
- `bench execute <dotted.path>` runs the function with frappe bootstrapped and NO test-bootstrap — this is why it avoids the veg11 `before_tests` crash. Do not convert the harness into a `run-tests` TestCase on veg11.
- The three lifted rules only appear on 3 admin/debug pages; if the compiled-CSS overlap check in Task 1 Step 6 flags any of them, drop that rule and leave it inline — the wrapper consolidation is the essential deliverable.
