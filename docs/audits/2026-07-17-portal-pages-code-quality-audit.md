# Portal Pages — Code Quality Audit (2026-07-17)

Scope: `verenigingen/templates/pages/**`, `verenigingen/www/**`, `verenigingen/templates/includes/**`,
`verenigingen/templates/macros/**`.
Size: 68 real page controllers + 68 real templates (+1 symlinked pair, `me.py`/`me.html` →
`member_portal.*`). Raw measurements below of 17,504 LOC (controllers) and 40,571 LOC (templates)
follow symlinks and therefore **double-count ~1,432 LOC** — see DEAD-1.

**Status (2026-07-17):** items 2–9b are **FIXED** on branch `fix/portal-dead-wiring-and-audit-cleanup`.
Item 1 was **retracted** (see DEAD-1). Items 10–20 remain open.

LIVE-1 was resolved by owner decision: staff is granted all-chapter visibility on **both** pages
(`Roles.ADMIN_ROLES`), consolidated into
`services/chapter/chapter_permission_service.py::get_user_board_chapters()`.

**The blast radius of that decision is wider than this section originally stated, and the corrected
scope was accepted by the owner on 2026-07-17.** An external review found that
`verenigingen/api/chapter_dashboard_api.py` imports `get_user_board_chapters` from
`templates.pages.chapter_dashboard` at **nine** call sites, so the consolidation silently re-pointed
it at the staff-inclusive implementation. Eight are read endpoints for which it is the **only**
chapter check — `get_chapter_member_emails`, `get_active_members_count`,
`get_pending_applications_count`, `get_board_members_count`, `get_new_members_count`,
`get_filed_expense_claims_count`, `get_approved_expense_claims_count`,
`get_volunteer_expenses_count`; the ninth is `quick_approve_member`, which takes it as its *first*
gate. Add `chapter_dashboard.get_chapter_dashboard_data`, which exposes `financial_summary`,
`dues_payment_status` (per-member payment state), `member_overview`, `pending_actions` and
`board_documents` for the selected chapter. The security decorators do not constrain staff:
`utils/security/authorization_policy.py:83` grants `VERENIGINGEN_STAFF` the HIGH/MEDIUM/LOW levels,
so `@high_security_api(MEMBER_DATA)` passes and for those eight endpoints what this function returns
is the access decision.

Accepted position: **staff act as read-only administrators over all chapters** — member email
addresses via `get_chapter_member_emails`, and the full dashboard payload above. Mutations stay
closed because they take a second gate — `quick_approve_member` requires
`get_user_board_role().permissions.can_approve_members`, and `get_user_board_role()` has no staff
branch, so it returns `None`. That denial is a load-bearing safety property and is now pinned by
`tests/services/test_chapter_board_chapters.py` (verified by mutation: adding staff to
`get_user_board_role`'s short-circuit fails the test).

### SEC-1 — `get_chapter_member_emails` leaks across chapters via a shared cache — **CONFIRMED, PRE-EXISTING, UNFIXED**

Found by external review while checking the above; **not introduced by this branch**, and it means the
staff grant is not the only way to read a chapter's member emails.

`chapter_dashboard_api.py:32` applies `@cached(ttl=300)` as the **innermost** decorator, so a cache hit
returns before the body's chapter check (`:84-86`) ever runs. The key
(`utils/performance_utils.py:229`) is `f"{func.__module__}.{func.__name__}:{hash(str(args)+str(kwargs))}"`
— **no user component** — and `CacheManager._cache` is a process-wide class attribute. The
`@high_security_api` tier check still runs, but it gates on tier, not chapter.

Consequence: once any authorized caller warms a chapter, **every user who clears the HIGH tier reads
that chapter's member emails for 5 minutes**, including `Verenigingen Chapter Board Member`, who holds
HIGH per `authorization_policy.py:88-91` — i.e. a board member of chapter Y reads chapter X's members.

Demonstrated on production data with a board member who does not govern the target chapter:

| cache state | result |
|---|---|
| cold | `dict` (OperationResult denial — correctly refused) |
| warmed by Administrator | `list` of **110 member email addresses** |

Scope is bounded: an AST sweep found this is the **only** whitelisted `@cached` endpoint with an
in-body permission check and no `key_func`.

Fix options: give the cache a user-scoped `key_func` (`lambda chapter_name:
f"{frappe.session.user}:{chapter_name}"`), or drop `@cached` (the body is a single indexed query).
Note `hash()` is `PYTHONHASHSEED`-randomised per process, so the cache is already incoherent across
workers — an independent reason to question its value. **Owner decision required; left unfixed here
because it is outside this branch's scope.**

Two further tensions remain by design: `ChapterPermissionService.get_permission_query_conditions()`
still restricts staff to published chapters in list views, and `chapter_dashboard.html:76` falls back
to the literal label "Board Member" when `user_board_role` is `None`, so staff are labelled
"Board Member" on every chapter — misleading, not a crash.

**Correction to DEAD-3's count:** 10 whitelisted endpoints were deleted on this branch, not 6. The
audit listed the six in the portal pages; the branch also removed four from
`utils/portal_customization.py` (`setup_member_portal_menu`, `reset_portal_menu_to_member_only`,
`analyze_current_portal_usage`, `get_clean_member_portal_menu`) as part of the inert portal-menu hook
removal. All four were independently verified to have zero callers.

**Known follow-up:** `verenigingen/fixtures/critical_operation_rule.json` still carries Critical
Operation Rule records for all 10 deleted endpoints. They are inert (rules keyed by operation name
that can no longer be invoked) but will be re-created on every migrate; removing the fixture rows does
not delete already-imported records, so a patch is needed. Also `docs/remediation/
HOOKS_SIMPLIFICATION_PLAN.md:193` still references the deleted `volunteer_portal.css`.

## Confidence markers

- **CONFIRMED** — independently verified during this audit (command output / framework source read).
- **REPORTED** — surfaced by analysis but not independently verified. Verify before acting.

Two corrections were made to draft findings during verification; both are recorded below under
"Corrections", because the reasoning that produced them will recur.

---

## 0. Negative results (things that are NOT wrong)

Recorded deliberately — an audit that only lists problems invites over-correction.

- **CONFIRMED** All 69 portal routes resolve (`PathResolver.is_valid_path()`). There are no dead
  pages at the route level, unlike the orphaned reports found on 2026-07-16.
- **CONFIRMED** No SQL injection. All 21 raw `frappe.db.sql` calls in the scope were reviewed,
  including the three f-string cases (`mollie_payment_processing.py:185,196`, `volunteer/skills.py:150`).
  Each interpolates only placeholder counts or hardcoded condition strings; values are bound.
  This is a layering violation, not a vulnerability.
- **CONFIRMED** `mollie_payments_debug.py` (1,210 LOC) is not a god file and is not publicly exposed.
  It is ~35 thin wrappers over `MollieDebugService`, gated by `require_login()` + role check +
  `@high_security_api(FINANCIAL)` with `allow_guest=False`. The problem is boilerplate, not architecture.
- **REPORTED** The "template reads a variable the controller never sets" category is **not** systemic.
  An automated pass flagged ~100 vars across 44 files; manual review found ~98% false positives
  (context is set indirectly via `context.update(service...)`, `populate_*_context()`,
  `setup_portal_context()`). Only one real case survived (see LIVE-2). Distrust any tool reporting
  otherwise without a manual pass.

## Corrections made during this audit

1. **A draft finding claimed a member-access bug** from `has_website_permission` diverging across six
   pages (four using `{"email": user}`, one `{"user": user}`, one the canonical helper). The
   duplication is real; the bug is not. Frappe never calls these functions (see DEAD-2). Severity
   dropped from "latent access bug" to "dead code". Lesson: verify the framework's dispatch path
   before believing a divergence report.
2. **The single largest finding — 847 LOC of `me.py`/`member_portal.py` duplication — was wrong.**
   They are committed symlinks. `md5sum`/`diff`/`wc -l` follow symlinks, so identical hashes were
   mistaken for duplication by two independent analyses *and* by the verification pass that marked it
   CONFIRMED. Use `ls -la` / `git ls-files -s` when a duplication claim rests on file equality. See
   DEAD-1. This also means "verified by command output" is only as good as the command chosen.

3. **An initial dead-code pass reported zero dead code** — a false negative. `coverage_html_report/`,
   the auto-generated `fixtures/critical_operation_rule*.json` (which registers *every* whitelisted
   endpoint by name), and `scripts/permission_analysis_details.json` mention every function name and
   manufacture 3+ fake "callers" each. Any dead-code grep in this repo must exclude those three paths.

---

## Live bugs (small, high value)

### LIVE-1 — `get_user_board_chapters()` privilege divergence — **CONFIRMED**

`templates/pages/volunteer/skills.py:66` is a copy of `templates/pages/chapter_dashboard.py:110`
(its docstring says so: *"copied from chapter_dashboard.py"*). Both are live, called from
`get_context` (`skills.py:17`, `chapter_dashboard.py:44` and `:252`). The admin role sets diverged:

| File | Roles short-circuiting to "all chapters" |
|---|---|
| `chapter_dashboard.py:115` | `SYSTEM_MANAGER`, `VERENIGINGEN_ADMIN` |
| `volunteer/skills.py:73` | `SYSTEM_MANAGER`, `VERENIGINGEN_ADMIN`, **`VERENIGINGEN_STAFF`** |

A Verenigingen Staff user who is not a board member sees **every chapter** on `/volunteer/skills`
and **none** on `/chapter_dashboard`. One of the two is wrong; product decision required.

Fix: one `get_user_board_chapters(include_staff: bool = False)` in the existing
`utils/chapter_board_permissions.py`. `member_portal.py:579 is_user_board_member()` is a third
variant of the same walk and becomes `bool(get_user_board_chapters())`. (~70 LOC)

### LIVE-2 — `/volunteer/skills` logo never renders — **CONFIRMED**

`templates/pages/volunteer/skills.html:17` reads `{% if brand_logo %}`. Nothing sets `brand_logo`:
`skills.py` sets only `no_cache`, `show_sidebar`, `title`, `user_chapters`, `chapter_member_ids`,
`no_access`, `skills_by_category`, `skills_stats`, `search_results`, `search_params`. The only
`brand_logo` in the app is `services/communication/email_service.py:823` (unrelated email context).
Every other page uses `organization_logo` (e.g. `volunteer/apply.py:31` via
`brand_settings.get_organization_logo()`). Jinja renders undefined as falsy, so this failed silently.

Fix: `brand_logo` → `organization_logo` + set it in `skills.py`. (1 line + 2)

---

## Dead code

### DEAD-1 — ~~`me.py` and `member_portal.py` are byte-identical duplicates~~ — **RETRACTED, NOT A FINDING**

**This finding was wrong. There is no duplication.** `me.py` and `me.html` are **committed symlinks**:

```
$ ls -la verenigingen/templates/pages/me.*
me.html -> member_portal.html
me.py   -> member_portal.py

$ git ls-files -s verenigingen/templates/pages/me.py     # 120000 = symlink mode
120000 d30216a8… 0  verenigingen/templates/pages/me.py
```

The aliasing this audit was about to recommend **is already implemented**, and via a better mechanism
than the proposed redirect: a symlink preserves the `/me` URL instead of bouncing to `/member_portal`.

**How the error was made — worth internalising:** `md5sum`, `diff`, and `wc -l` all silently follow
symlinks. Identical MD5s across two paths were treated as proof of duplication and the finding was
marked CONFIRMED. The correct check is `ls -la` or `git ls-files -s`. Two independent analyses and one
verification pass all missed it; it surfaced only when a write to `me.py` was refused as a symlink write.

**Consequences for the rest of this document:**
- The scope figures at the top are inflated by ~1,432 LOC (847 `.py` + 585 `.html` counted twice).
  Real counts: **57** real page controllers + **56** real templates (+1 symlink each).
- Any finding citing "`me.py`/`member_portal.py`" as two sites is **one** site: DEAD-2's
  `has_website_permission` count is **10 modules (~84 LOC)**, not 11/92; KISS-5's `me.py:177` /
  `member_portal.py:177` N+1 is one loop, not two.

**Genuinely worth noting (unrelated to duplication):** `/me` shadows Frappe's own account page
(`frappe/www/me.html`) because verenigingen is last in `apps.txt` and its `templates/pages/me.html`
overwrites the route. `web_sidebar.html:62` links `/me` labelled **"My Account"** with a cog icon —
which is what Frappe's `/me` *is*. So the sidebar's intent may be Frappe's account page while the
route serves the member portal. That is a product question, not a defect, and is left open.

**Also incidental:** `verenigingen/templates/pages/addresses.py` is dead — verified `addresses` is not
a registered route (`get_pages()` has no entry). Frappe's router only registers html/xml/js/css/md
(`website/router.py::get_pages_from_path`), so a `.py`-only page never gets a route. It also uses the
RPC-style `frappe.local.response["type"] = "redirect"`, which would not redirect a page render even if
it were routed. The working pattern is `frappe.local.flags.redirect_location` + `raise frappe.Redirect`
(`payment_plans.py:21`, `volunteer/index.py:7`). ~11 LOC; `volunteer/index.py` is registered via its
sibling `index.html` and is fine.

### DEAD-2 — `has_website_permission()` is never called — **CONFIRMED** — ~97 LOC, 10 modules

Frappe resolves this hook **only** for doctype web views:
- `frappe/__init__.py:652` calls it as a **Document method**;
- `frappe/__init__.py:655` reads `get_hooks("has_website_permission")`, a **doctype-keyed dict**;
- callers are `website/page_renderers/document_page.py:29`, `www/printview.py:397`,
  `website/doctype/web_form/web_form.py:568`.
- `TemplatePage` (which renders these pages) performs **no** permission check — it calls only
  `get_context` (`template_page.py:163`).
- The merged hook across all installed apps contains only frappe/erpnext doctypes — **zero**
  Verenigingen entries; `verenigingen/hooks/` registers none.

Sites: `brand_management.py:43`, `sepa_reconciliation_dashboard.py:27`, `team_members.py:205`,
`my_teams.py:121`, `chapter_join.py:122`, `personal_details.py:89`, `verenigingen/join_chapter.py:138`,
`manage_donations.py:54`, `contact_request.py:66`, `member_portal.py:127`.
(`me.py:127` is the same definition reached through the symlink — see DEAD-1.)

**Not a security hole** — each `get_context` independently gates access. The dead functions merely
duplicate the real gate.

**Blocker:** some tests assert a false premise, e.g. `test_page_sepa_reconciliation_dashboard.py:6`
describes it as "gating the route to banking/accounting roles". It gates nothing. Those tests must be
deleted or rewritten alongside the functions — they are currently proof that the misunderstanding is
load-bearing in the test suite, not in production.

### DEAD-3 — Six `@frappe.whitelist()` endpoints with zero callers — **CONFIRMED** — 88 LOC

Live HTTP surface; ranks high regardless of LOC. Verified by repo-wide grep excluding the three
noise paths named under "Corrections".

| LOC | Location | Decorator |
|---|---|---|
| 34 | `templates/pages/volunteer/expenses.py:48` `create_volunteer_for_member` | `high_security_api(ADMIN)` |
| 14 | `templates/pages/volunteer/skills.py:278` `search_skills` | `standard_api(MEMBER_DATA)` |
| 13 | `templates/pages/membership_application.py:145` `calculate_suggested_contribution` | **`public_api` — guest-reachable** |
| 9 | `www/monitoring_dashboard.py:426` `get_detailed_analytics_report` | `standard_api(REPORTING)` |
| 9 | `www/monitoring_dashboard.py:439` `get_performance_optimization_report` | `high_security_api(ADMIN)` |
| 9 | `www/monitoring_dashboard.py:452` `get_compliance_audit_report` | `high_security_api(ADMIN)` |

Precedent: PR #142 deleted two orphaned whitelisted endpoints for the same reason.

### DEAD-4 — Three unreferenced template includes — **CONFIRMED** — 464 LOC

| File | LOC |
|---|---|
| `templates/includes/skills_dashboard_widget.html` | 319 |
| `templates/includes/portal_sidebar.html` | 113 |
| `templates/includes/address_list.html` | 32 |

Zero references anywhere in the app. Verified they shadow no core template: frappe/erpnext have no
`templates/includes/skills_dashboard_widget.html` or `portal_sidebar.html`; core's `address_list.html`
lives at `frappe/public/js/frappe/form/templates/` (a JS form template, different path, not shadowed).
Contrast `web_sidebar.html`, which **does** shadow `frappe/templates/includes/web_sidebar.html` and is
therefore live.

The only mentions are in `docs/plans/2026-02-17-member-portal-ux-review.md`, which flagged them and was
never actioned. `portal_sidebar.html` is a third nav implementation.

### DEAD-5 — Unreachable branch in `admin_tools.py:751` — **CONFIRMED** — ~50 LOC

```python
715:  if method not in ALLOWED_ADMIN_METHODS:
          frappe.throw(...)                                    # always raises
749:  method_explicitly_allowed = method in ALLOWED_ADMIN_METHODS   # therefore always True
751:  if not is_whitelisted and not method_explicitly_allowed:      # therefore always False
```

`method` is not reassigned between 715 and 749 (verified). The ~50-LOC `debug_info` introspection
branch walking `__wrapped__` can never execute. Same defect class as the merged Audit-D fix (PR #144).

The dynamic `import_module`/`getattr` dispatch is correctly gated by the allow-list — not RCE.

### DEAD-6 — `donate.html:517–543` `{% if false %}` — **CONFIRMED** — 27 LOC

`{# Disabling tax deduction benefits section for now #}` — unreachable ANBI tax-benefits markup.

### DEAD-7 — Unused imports/locals — **REPORTED** — 24 (22 ruff-autofixable)

`volunteer/expenses.py:20,21,24,26`, `manage_donations.py:8,17`, `my_dues_schedule.py:1,5,9`,
`mollie_bulk_payment_creation.py:12`, `dues_coverage_manager.py:11`, `board/document_upload.py:14`.

### DEAD-8 — `payment_plans.py` computes context the template discards — **REPORTED** — ~15 LOC

`payment_plans.html` is fully JS-driven and uses no Jinja vars, but `payment_plans.py:27,35,44,45` set
`no_member`, `member_name`, `has_dues_schedules`, `dues_schedules` — the last from a live
`frappe.get_all("Membership Dues Schedule", …)` whose result is never rendered.

---

## DRY violations

The shared helpers **already exist and are already used by some callers**. What remains is
un-migrated leftovers — low-risk mechanical work against a proven target, not new abstraction design.

Canonical helpers: `utils/member_utils.py:57 get_member_name_for_user()`, `:93
get_current_user_member_name()`, `:17 require_login()`, `utils/member_portal_utils.py:226
setup_portal_context()`, `utils/constants.py:41 Roles.ADMIN_PAIR`.

### DRY-1 — `setup_portal_context()` migration left two pages behind — **REPORTED** — ~50 LOC

`member_portal.py:22-60` and `contact_request.py:14-37` hand-roll the identical ~25-line block that
`setup_portal_context()` exists to remove (5 other pages already migrated).

**Diverged:** the hand-rolled copies fall back to `email_utils.get_support_contact_email()` on
exception; `setup_portal_context:249` logs and sets `support_email = None`. So on the 5 *migrated*
pages the "Member Record Not Found" banner shows no contact address when the setting is missing.
The migration silently lost a fallback for the majority of pages — port it into the shared helper.

Also: `me.html:64` includes `portal_no_member_error.html` but no `me.py` sets `no_member_record` —
that banner is dead on that page.

### DRY-2 — Four competing member-from-user resolvers — **REPORTED** — ~40 LOC

| Resolver | Lookup order | On failure |
|---|---|---|
| `utils/member_utils.py:57 get_member_name_for_user` | user → email | `None` |
| `utils/error_handling.py:849 validate_member_for_user` | **email → user** | throws |
| `api/payment_dashboard.py:664 get_member_from_user` | member-id → email → user → User.email | `None`, TTL-cached 300s |
| `utils/security/self_service_access_controller.py:100 get_user_member` | delegates to canonical | `None` |

The first two resolve in **opposite order**. Where `Member.user` and `Member.email` point at different
Member records, `my_teams.py:20` and `contact_request.py:21` resolve to different members for the same
session. `payment_dashboard`'s 5-minute cache also means a member/user relink lags there while every
other page updates instantly. `error_handling.py:851` calls itself a *"development helper"* yet
`my_teams.py:20` uses it in production.

Note `self_service_access_controller.py:100-121` documents the underlying defect:
*"Resolving email-only here wrongly locked out members linked via Member.user whose Member.email
differs from their login."* That fix reached the access controller and `manage_donations.py` but not
the page-level copies — which is only harmless because those copies are dead (DEAD-2).

### DRY-3 — Inline `admin_roles` lists despite `Roles.ADMIN_PAIR` — **REPORTED** — ~15 LOC

`member_portal.py:586`, `chapter_dashboard.py:115`, `chapter_dashboard.py:166`, `volunteer/skills.py:73`
re-inline the list; `brand_management.py:18,50` and `membership_adjustment.py:901` use the constant.
Adding a role to `ADMIN_PAIR` updates 3 sites and misses 4. This is the mechanism that let LIVE-1 drift.

### DRY-4 — Guest guards / duplicated error strings — **REPORTED** — ~60 LOC

`require_login()` exists but the guard is re-implemented ~12× in three styles: redirect to `/login`
(`payment_plan_pay.py:16`, `payment_plans.py:20`), throw `PermissionError` (7 sites), return `False`
(the dead `has_website_permission` family). Guests hitting `/payment_plans` get a login redirect;
guests hitting `/dues_invoice_manager` get a 403 page. Inconsistent UX, not a security hole.
`address_change.py` alone throws 10 hand-written "Access denied…" variants; lines 173-211 and 335-373
are a near-identical validate-member-then-validate-address block (~35 LOC).

---

## KISS / separation of concerns

Rubric (CLAUDE.md): *"Break functions exceeding 10 lines"*, *"Extract to service if >150 LOC"*,
*"Business logic is server-side [and belongs in services, not presentation]"*.

**REPORTED** measurements across 334 portal functions:
- **294 (88%) exceed 10 LOC**
- **106 (32%) exceed 50 LOC**, holding **10,416 LOC — 59% of the scope**
- 43 nest ≥4 levels; 10 take ≥5 args

### KISS-1 — `admin_tools.py:24 get_context()` is 585 LOC — **REPORTED**

66% of its file, in one function. ~470 LOC is data-as-code: four literal tool-definition lists
(`:59` invoice ~58, `:117` data-integrity ~167, `:284` system ~138, `:422` member-cleanup ~110).
Move the catalog to a constant/fixture/DocType; `get_context` collapses to ~20 LOC.

### KISS-2 — `donate.py` (1,019 LOC) reimplements `services/donation/` — **REPORTED** — ~250 LOC

`donate.py` imports nothing from `services/donation/` (1,574 LOC, already used by
`donation_dashboard.py`, `web_form/donation_form`, and the `Donation` DocType).
`get_or_create_donor():342` (81) ≈ `DonationDonorService.ensure_donor_exists()`;
`process_bank_transfer():715` (49), `process_sepa_direct_debit():764` (30),
`create_donation_record():487` (81) ≈ `DonationFinancialService`.
`get_context():48` is 162 LOC at **nesting depth 8** — the deepest function in the scope.

### KISS-3 — Mollie page family duplication — **REPORTED** — ~340 LOC

`mollie_payments_debug.py` (1,210) and `mollie_payment_processing.py` (888) share **340 identical
lines**, including `bulk_process_member_payments` (`:867` / `:491`, ~140 LOC, differing in 37 cosmetic
lines) and `process_payment_batch_job` (25 LOC, differing by a comment). `sanitize_csv_field()` is
copy-pasted verbatim into `mollie_bulk_payment_creation.py:60` and `mollie_subscription_recreation.py:154`.

Forked bulk **payment-processing** code is a real hazard: a batching/dedup fix in one copy leaves the
other charging members on stale logic. Consolidate into `mollie_admin_base.py`.

### KISS-4 — Business logic stranded in pages — **REPORTED** — ~1,800 LOC relocatable

All exceed the ">150 LOC → extract to service" rule and none is testable without a web-request context.
`chapter_dashboard.py` (1,116 LOC) imports **zero** of the 20 modules in `services/chapter/`.

| Function | LOC / nest | Belongs in |
|---|---|---|
| `mollie_payment_processing.py:56 _retrieve_global_payments_with_orphans` | 257 / 6 | `MollieDebugService` (already imported) |
| `mollie_bulk_payment_creation.py:85 validate_csv_members` | 257 / 7 | `services/csv_import/` |
| `mollie_subscription_recreation.py:247 parse_and_validate_csv` | 218 / 6 | `services/csv_import/` |
| `mollie_subscription_recreation.py:469 recreate_subscriptions` | 209 / 6 | `MollieDebugService` |
| `membership_adjustment.py:319 submit_fee_adjustment_request` | 214 / 4 | `contribution_amendment_approval_service.py` |
| `mollie_bulk_payment_creation.py:346 create_bulk_payments` | 182 / 6 | `MollieDebugService` |
| `address_change.py:134 update_member_address` | 185 | `services/member/` |
| `chapter_dashboard.py:786 get_dues_payment_status` | 161 / 8 | `services/chapter/chapter_query_service.py` |
| `chapter_dashboard.py:582 get_financial_summary` | 146 | `chapter_finance_service.py` |

### KISS-5 — N+1 queries — **REPORTED** — 8 loops

1. **`mollie_bulk_payment_creation.py:193`** → per-CSV-row `get_value("Member", {"mollie_customer_id": …})`
   at `:247`. N = upload size (hundreds+). The one genuine perf bug; fix with an `["in", ids]` prefetch.
2. `team_members.py:183` → per-chapter `get_all("Team")`.
3. `volunteer/profile.py:115` and `:129` → per-chapter/per-team `get_value` fetching only `name`, a
   column the loop already has as `cm.parent`/`tm.parent`. **Pure waste — free to delete.**
4. `me.py:177` / `member_portal.py:177` (the DEAD-1 duplicate), `membership_adjustment.py:718`,
   `workflow_demo.py:73`.

---

## Template layer

**REPORTED** 40,571 LOC across 78 files, of which **6,383 is inline CSS and 15,637 is inline JS** —
54% of the template layer is not markup.

### TPL-1 — No shared website stylesheet — ~1,500–2,000 LOC

There is **no `web_include_css` hook**, so website pages receive no app CSS and every page hand-rolls
its own. 53 of 78 templates carry `<style>`; 179 selectors are defined in ≥2 templates, 77 in ≥3;
31 rules are *exact-identical* across ≥3 templates (81 redundant copies).

Worst: `admin_tools.html` (508 CSS LOC), `mollie_payments_debug.html` (453), `personal_details.html` (309).
Most-duplicated: `.wide-layout-wrapper` ×13, `.btn` ×11, `.status-badge` ×10, `.btn-primary` ×10.

**CONFIRMED drift:** `.wide-layout-wrapper` is defined in 13 templates in mutually incompatible
variants (`width: 90vw; max-width: 1600px` vs `width: 95vw` vs `max-width: 1400px/1200px`). The same
class name yields a different layout width depending on which page you are on.

Fix: add `web_include_css` + a portal stylesheet; lift the ~80 shared rules; resolve
`.wide-layout-wrapper` to one definition.

### TPL-2 — Two parallel navigation systems; 26 pages have no nav — **REPORTED**

- `base_portal.html:13` includes `portal_nav.html` and **overrides `page_container`** — the very block
  Frappe's `web.html` renders the sidebar in. So the **19** templates extending `base_portal.html`
  get `portal_nav.html` and never render `web_sidebar.html`.
- `web_sidebar.html` is live only because it shadows frappe core's copy (verenigingen is last in
  `apps.txt`), included by `frappe/templates/web.html:51` under `{% if show_sidebar %}`. The **46**
  templates extending `templates/web.html` get it — but only the **11** whose `.py` sets
  `show_sidebar = True`. **26 set it False and get no navigation at all.**

Two role-based nav lists (118 + 140 LOC) maintained separately. `web_sidebar.html:2`'s docstring
("rendered on every page via base_portal.html") is **factually inverted** — base_portal is the one path
where it never renders. `hooks/portal.py:5` repeats the claim. Fix the docstrings regardless.

### TPL-3 — Four admin tools bypass the brand_css macro — **REPORTED** — 4 lines

`admin_tools.html:6`, `mollie_payments_debug.html:7`, `mollie_payment_processing.html:7`,
`ponto_api_debug.html:7` hand-copy the `<link>` instead of importing
`templates/macros/brand_css.html`. Since the served `brand_colors.css` is **globally unscoped**
(it restyles bare `.card`/`.bg-red-600` with `!important`), these internal admin tools are silently
recolored — and a fix to the macro will never reach them.

Conversely `financial_dashboard.html` and `my_addresses.html` are portal pages that *omit* it —
inconsistent theming on 2 of 19.

### TPL-4 — Six templates discard the base stylesheet — **REPORTED** — ~22 LOC

`address_change.html`, `my_dues_schedule.html`, `contact_request.html`, `my_teams.html`,
`membership_adjustment.html`, `volunteer/expenses.html`, `volunteer/dashboard.html` override
`{% block head_include %}` **without `{{ super() }}`**, discarding `base_portal.html:3-6`'s tailwind
link, then re-link tailwind to compensate. 16 of 19 base_portal children link tailwind twice.

**Caveat:** the redundant links are compensation for the missing `super()` — they cannot be blanket-deleted.

### TPL-5 — Duplicate expense-claim pages — **REPORTED** — ~500 LOC

`volunteer/expense_claim_new.{py,html}` (61 + 527) vs `volunteer-portal/expense_claim_new.{py,html}`
(64 + 476) — normalized diff 73 lines. `volunteer-portal/` is the refactored one (uses shared includes,
delegates to `volunteer_expense_portal_utils`); both service modules name it as their consumer. The
`volunteer/` copy inlines both blocks, uses a bare `except:`, hardcodes empty stats
("keeping it simple for now"), and its own docstring calls it "Alternative expense portal".
Neither is UI-linked, so confirm intent before retiring `volunteer/`.

### TPL-6 — 15,637 LOC inline JS with hand-rolled HTTP — **REPORTED** — ~300–500 LOC

61 of 77 templates carry inline `<script>`; `mollie_payments_debug.html` alone has a **2,465-line**
block. Two competing idioms: `frappe.call(` (130 uses / 42 files) vs raw `fetch('/api/method`
(38 / 10 files) hand-managing `X-Frappe-CSRF-Token` (40 uses / 11 files) that `frappe.call` handles free.
Duplicated definitions: `escapeHtml()` ×6, `showMessage()` ×4, `showError()` ×4, `switchTab()` ×3.
Six independent `escapeHtml` implementations is an XSS surface worth noting on its own.

### TPL-7 — 1,144 hardcoded hex colors vs 469 brand-var uses — **REPORTED**

Only 29% of colour references go through `var(--brand-*)`. The brand primary `#cf3131` is hardcoded
**48 times across 13 files** despite `--brand-primary` existing (and `apply_for_membership.py:36`
demonstrating the intended fallback pattern). Rebranding currently means touching 13+ templates.

### TPL-8 — Translation coverage 79% — **REPORTED** — 540 unwrapped strings

The gap is bimodal (whole files, not scattered misses): `chapter_dashboard.html` 51 raw / **0** wrapped,
`board/document_upload.html` 39/0, `www/mollie_subscription_audit.html` 36/0,
`www/monitoring_dashboard.html` 30/0. Contrast `mollie_payments_debug.html` at 239 wrapped / 9 raw.

**`chapter_dashboard.html` is the priority** — 51 untranslated strings including `"Access Denied"`
on a member-facing page. The rest are mostly internal admin tools.

### TPL-9 — `www/mollie_dashboard.html` has no controller — **REPORTED**

301 LOC, JS-driven with YAML front-matter, so it renders — but unlike every sibling in `www/` it has
no `.py` and therefore **no server-side permission gate**. Worth a security look, out of scope here.

---

## Ranked remediation

Mechanical, near-zero-risk first.

| # | Action | LOC | Risk | Confidence |
|---|---|---|---|---|
| ~~1~~ | ~~`me.py` → alias~~ — **RETRACTED**, already a symlink (DEAD-1) | — | — | **WRONG** |
| 2 | Fix `skills.html` `brand_logo` → `organization_logo` (LIVE-2) | 3 | none | CONFIRMED |
| 3 | Resolve `get_user_board_chapters` staff divergence (LIVE-1) | ~70 | low — needs product call | CONFIRMED |
| 4 | Delete 3 unreferenced includes (DEAD-4) | −464 | none | CONFIRMED |
| 5 | Delete 6 uncalled whitelisted endpoints (DEAD-3) | −88 | low — removes HTTP surface | CONFIRMED |
| 6 | Delete dead branch `admin_tools.py:751` (DEAD-5) | −50 | very low | CONFIRMED |
| 7 | Delete `has_website_permission` ×10 + fix false-premise tests (DEAD-2) | −84 | low — tests must change | CONFIRMED |
| 8 | Delete `donate.html` `{% if false %}` (DEAD-6) | −27 | none | CONFIRMED |
| 9 | ruff `--fix` unused imports (DEAD-7) | −24 | none | REPORTED |
| 9b | Delete unregistered `addresses.py` (see DEAD-1 note) | −11 | none | CONFIRMED |
| 10 | Fix `mollie_bulk_payment_creation` N+1 + `profile.py` waste queries (KISS-5) | — | low | REPORTED |
| 11 | `mollie_admin_base.py` — dedup family (KISS-3) | −340 | low | REPORTED |
| 12 | `admin_tools` tool catalog → data (KISS-1) | −470 | low | REPORTED |
| 13 | `web_include_css` + portal stylesheet; unify `.wide-layout-wrapper` (TPL-1) | −1,500/2,000 | medium | REPORTED |
| 14 | Retire `volunteer/expense_claim_new` (TPL-5) | −500 | low | REPORTED |
| 15 | `donate.py` → `services/donation/` (KISS-2) | −250 | medium | REPORTED |
| 16 | Resolve nav split; fix inverted docstrings; nav for 26 pages (TPL-2) | ~−150 | medium | REPORTED |
| 17 | Push 9 god-functions into existing services (KISS-4) | ~1,800 moved | medium/high | REPORTED |
| 18 | `portal_utils.bundle.js`; migrate raw-fetch → `frappe.call` (TPL-6) | −300/500 | medium | REPORTED |
| 19 | Brand vars for 170 hex sites (TPL-7) | ~170 sites | low | REPORTED |
| 20 | Wrap 540 strings in `_()`, `chapter_dashboard.html` first (TPL-8) | 540 sites | low | REPORTED |

**Items 2–9b remove ~750 LOC at essentially no behavioural risk** (down from the ~1,590 claimed before
DEAD-1 was retracted). Items 11–17 total ~3,400 LOC and reconnect to a service layer that **already
exists and is already used elsewhere** — reconnection, not new architecture.

## Recurring theme

Five of the eight dead-code findings are the same shape: **code that looks live, is plausibly
structured, and is never invoked by the framework.** `has_website_permission` (never dispatched for
template pages), the three unreferenced includes, the always-True guard, the `{% if false %}` block —
plus, from the same week, `website_context` method paths, `standard_portal_menu_items` with empty
`reference_doctype`, and a Desk-bundled portal stylesheet.

The common failure mode is assuming a declaration takes effect. The reliable check is to ask the
framework at runtime (`frappe.get_hooks(...)`, `PathResolver`, render the page) rather than to read
the declaration and infer.

`docs/plans/2026-02-17-member-portal-ux-review.md` already identified several of these items in
February and was never actioned; two of them (`portal_sidebar.html`, `skills_dashboard_widget.html`)
appear again here. Findings without a landed fix decay into rediscovery cost.
