# Portal base stylesheet + `web_include_css` — Design (2026-07-18)

Addresses portal-pages audit item TPL-1 (infrastructure slice), TPL-3, and TPL-4
(`docs/audits/2026-07-17-portal-pages-code-quality-audit.md`). Branch `refactor/portal-base-css`.

## Problem

There is **no `web_include_css` hook** in verenigingen, so every website/portal page hand-rolls its
own CSS inside a `<style>` block. 56 templates carry inline styles; many rules are duplicated across
≥3 templates, and `.wide-layout-wrapper` is defined 10 times in **mutually incompatible** widths
(`max-width` = `1600px` ×7, `1400px` ×2, `1200px` ×1) — the same class yields a different layout
width depending on which page you are on. Two admin-tool families also hand-copy the brand-css
`<link>` instead of the shared macro (TPL-3), and 7 `base_portal.html` children override
`head_include` without `super()`, discarding the base tailwind link and then re-linking it (TPL-4).

## Decisions (owner-approved)

1. **Scope = infrastructure slice + related CSS fixes**, not the full ~1,500–2,000 LOC TPL-1 lift.
   Establish the hook + a shared sheet, resolve the confirmed `.wide-layout-wrapper` conflict, lift
   only the safe shared rules, and fold in TPL-3 and TPL-4.
2. **`.wide-layout-wrapper` resolves to a single `max-width:1600px`.** All 10 inline copies are
   deleted, including the 3 narrower outliers. `board/document_upload` (1200→1600),
   `board/document_browser` and `ponto_api_debug` (1400→1600) become wider — an accepted, intended
   visual change.

## Load-bearing constraint — bleed safety

`web_include_css` injects on **every** website page (rendered by `frappe/templates/includes/head.html`),
not just verenigingen portal pages. It is already a live merged list — `frappe.get_hooks("web_include_css")`
returns `['erpnext-web.bundle.css']` — so appending is safe mechanically. The risk is *semantic*: a
globally-injected rule on a framework/Bootstrap class name would restyle frappe's own pages (login,
signup, web forms, blog). Frappe's website SCSS already styles `.btn`, `.card`, etc., and the
most-duplicated portal selectors include framework names (`.form-group` ×29, `.btn-primary` ×18,
`.btn` ×13, `.form-control`, `.alert`, `.btn-secondary`). This is the same trap as the globally
unscoped `brand_colors.css`.

Therefore `portal_base.css` contains **only**:
- (a) verenigingen-portal-**unique** class selectors — never Bootstrap/frappe names, never bare
  element selectors, never `!important` element overrides; **and**
- (b) rules whose body is **byte-identical** across every current occurrence.

Framework-colliding names (`.btn`, `.btn-primary`, `.form-group`, `.form-control`, `.alert`, …) are
**left inline** and deferred to a future namespacing slice. The safe lift set is therefore smaller
than the audit's optimistic ~80 rules; that is intentional and correct.

## Changes

### C1 — hook + new stylesheet
- New file `verenigingen/public/css/portal_base.css`.
- `hooks/assets.py`: add `web_include_css = ["/assets/verenigingen/css/portal_base.css"]`; export it
  from `hooks/__init__.py` alongside the existing `web_include_js`.

### C2 — `.wide-layout-wrapper`
- Canonical definition (base rule + its media-query variant) in `portal_base.css`, `max-width:1600px`.
- Delete all 10 inline definitions (incl. the media-query-only variants in `volunteer/dashboard.html`
  and `volunteer/expense_claim_new.html`).

### C3 — lift safe shared rules
- Candidate portal-unique selectors duplicated ≥3×: `.status-badge`, `.timeline-item`, `.btn-brutal`
  (+ `--primary` etc.), `.tab-button`/`.tab-content`, `.result-area`/`.result-content`,
  `.brutal-section-dark`, `.validation-table`, `.debug-card`, `.file-upload-area`, `.calendar-day`,
  `.stat-value`, `.page-header`, `.form-header`, `.form-input`, `.debug-input`, `.checkbox-label`,
  `.status-pending`.
- For each: (1) confirm the selector is portal-unique (absent from frappe's compiled website CSS and
  from the Bootstrap/frappe denylist); (2) confirm the rule body is byte-identical across all
  occurrences; (3) only then move the canonical body into `portal_base.css` and delete the inline
  copies. Any selector that is framework-named **or** varies between occurrences is skipped and left
  inline.

### C4 — TPL-3: brand-css macro
- `admin_tools.html`, `mollie_payments_debug.html`, `mollie_payment_processing.html`,
  `ponto_api_debug.html` each have `<link href="/css/brand_colors.css?v={{ frappe.utils.now() }}">`,
  byte-identical to what `templates/macros/brand_css.html::brand_css()` emits. Replace with the macro
  import + `{{ brand.brand_css() }}`. Output identical; future macro edits reach them.

### C5 — TPL-4: restore `super()`

Investigation during planning showed the 7 candidates split into two cases (the audit's "they all
re-link tailwind to compensate" was only half right):

- **Case A — re-link tailwind, missing `super()`** (`address_change.html`, `contact_request.html`,
  `my_teams.html`, `volunteer/dashboard.html`): these already have tailwind via their own `<link>`.
  Fix = add `{{ super() }}` (which resolves to `{{ head_include or "" }}` + base_portal's tailwind
  link — visually a no-op) and delete the child's own tailwind link so it loads once. **In scope.**
- **Case B — override `head_include` with NO tailwind** (`my_dues_schedule.html` links only mobile CSS;
  `membership_adjustment.html` has an empty block; `volunteer/expenses.html` loads external jQuery):
  these currently render **without** tailwind. Adding `super()` restores tailwind they lack — a real
  visual change on production pages. **Deferred** to a separate reviewed follow-up (needs per-page
  before/after screenshots); NOT done in this slice.

`super()` must be added **before** removing a link so tailwind is never dropped.

## Verification

Server-side rendering via `frappe.utils.get_html_for_route(route)` renders a full page (with `<head>`
and all CSS links) as a set user — no HTTP auth, no browser. Confirmed working on `member_portal`.

- **A. Render-assertion harness (deterministic, re-runnable).** Render every edited page + one per
  template family (~15–20 pages) as Administrator. Assert: `portal_base.css` `<link>` present in
  `<head>`; no inline `.wide-layout-wrapper` remains and the canonical width resolves; no inline copy
  of any lifted selector remains; page renders with no traceback. Capture the inline-`<style>` rule
  set before/after so the diff shows **only** intended deletions.
- **B. Bleed disjointness proof (deterministic).** Parse `portal_base.css` → selector set; assert it
  is disjoint from a Bootstrap/frappe denylist **and** from the selectors in frappe's compiled
  `website.bundle.css`; render 2 guest/non-portal pages (`/login`, home) and assert none of the
  sheet's selectors match anything there. Disjoint ⇒ zero bleed by construction.
- **C. Rule-equivalence check (deterministic).** For every lifted selector, grep all prior inline
  occurrences and assert byte-identical bodies (except `.wide-layout-wrapper`, whose 3 intended
  widenings are enumerated). Guarantees computed styles unchanged for lifted rules.
- **D. Visual spot-check (joint review).** Render → Playwright (local headless chromium) screenshot of
  the 3 widened pages + 3 representative pages for eyeball review.

A+B+C are deterministic and land as a committed test; D is human confirmation.

## Out of scope (future slices)

Namespacing the framework-colliding rules and the full ~80-rule lift; nav unification (TPL-2);
inline-JS extraction (TPL-6); hex→brand-var migration (TPL-7); translation (TPL-8).

## Risks

- **Bleed onto non-portal pages** — mitigated structurally (portal-unique selectors only) and proven
  by verification B.
- **Visual regression on portal pages** — mitigated by byte-identical lifting (verification C); the
  only intended changes are the 3 wrapper widenings.
- **Dropping tailwind mid-edit in C5** — mitigated by adding `super()` before removing any link and
  by render assertion A (tailwind link still present).
