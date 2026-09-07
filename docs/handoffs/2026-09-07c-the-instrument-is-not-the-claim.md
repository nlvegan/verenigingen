# 2026-09-07c — the instrument is not the claim

**State at handoff:** `develop` at `c37e65738`. **4 PRs merged** (#1091, #1099, #1100,
#1102) plus the previous handoff #1087; **1 PR open** (#1103, reviewed, one review fix
applied); **12 issues filed** (#1088–#1098, #1101, plus #1104–#1106 from a review);
183 issues open. Git worktrees: **235 → 1**.

The session began by acting on the previous handoff's single top recommendation. That
recommendation was wrong, and finding out why set the theme for everything after it.

---

## The through-line

**A claim and the instrument that produced it are different things.** Every substantive
correction today came from re-deriving a claim with a *different* instrument — never from
looking harder with the same one. Most of the corrected claims were mine.

| the claim | the instrument that produced it | what a different instrument said |
|---|---|---|
| "#1074: 66 endpoints declare `allow_guest` and are refused at runtime" | a census counting the **presence** of the `allow_guest` keyword | counting its **value**: 79 declare `True`, **0** are refused |
| "14 bare-whitelisted `scripts/` endpoints write to the DB" (mine) | textual `.<method>(` match | an AST call-name walk: **11** — wrong in *both* directions |
| "the shrink gate fails open when it cannot resolve git" | `$?` **after a pipe** — i.e. `tail`'s status | running it unpiped: `return 1`, fails closed |
| "both token call sites are inside a `try`" (my own self-review) | reading the file I had just edited | reading all callers: there are **three**, and one is not |
| "three modules stay green under the verifier mutation" (mine) | a *narrow* mutation | the **full** mutation its own prose implied: one of the three reddens |
| "these branches are abandoned / these are superseded" | open/merged **PR state** | `git cherry` **patch-id**: disagreed in both directions |
| every grep I ran for the first half of the session | the local working tree | it was **50 commits stale**; the answers matched by luck |

The tell is always the same shape: the mechanism is real, so confirming the mechanism
*feels* like confirming the claim. #1074's adapter genuinely never syncs
`frappe.guest_methods`, and a synthetic endpoint built in the buggy shape genuinely gets
`PermissionError`. Both true. The population is still zero.

---

## #1074 — the previous handoff's top item, refuted

It was carried as *"the only open item where the naive fix turns a latent functional bug
into a live security incident"*, and I repeated that twice before checking it.

- Runtime, on `test_site_2`: all **79** endpoints declaring `allow_guest=True` are in
  `frappe.whitelisted` **and** all 79 are in `frappe.guest_methods`.
- Static, independently: of those 79, **zero** sit anywhere but the outermost decorator
  position, and zero are non-literal. Run against a `git archive` of the pushed tree, with
  a positive control (a synthetic `@public_api` / `@frappe.whitelist(allow_guest=True)`
  pair, which the sweep detects).

The convention here puts `@frappe.whitelist(allow_guest=True)` **outermost**, where
frappe's own `whitelist()` registers the dispatched wrapper into both registries. The
adapter is never in the loop.

**Where "66" came from:** the census counted the keyword, not its value. Counting any
explicit `allow_guest=` — `True` or `False` — gives **150**, close to the "140" the issue
also reported. The two endpoints named as the reason the fix was dangerous,
`apply_optimizations` and `sepa_security_health_check`, are both `allow_guest=False` and
have been since `2dbea04eb` (2025-11-20).

**Still worth doing:** nothing enforces "`whitelist(allow_guest=True)` must be outermost",
so the first endpoint written the other way silently 403s for guests. A **ratchet asserting
the invariant** is the right shape — not a runtime `guest_methods` sync, which would be
compensating machinery for a population of zero.

---

## What shipped

- **#1091** — 11 bare-`@frappe.whitelist()` endpoints under `scripts/` that mutate the
  database, dispatch-reachable by any authenticated user. Worse than the one #1084 named:
  role/permission `delete_doc`, and create/submit/delete of accounting **Period Closing
  Vouchers**. Fixed by *removing* the whitelists — these are `bench execute` tools, and
  `bench execute` never consults the whitelist.
- **#1099** — `update_mollie_subscription_amount` accepted any caller-supplied
  `subscription_id`. Reuses `73d8d0569`'s `_authorize_member_access` shape rather than
  hand-rolling a fourth variant.
- **#1100 / #1102** — `scripts/` as a real second scan root for the duplication and
  API-security gates, and four previously-unenforced ratchets wired into CI.
- **#1103** (open) — signed return tokens for three guest-reachable page disclosures
  (#1053, #1055, #1052), split out of recovered unreviewed work.

---

## Corrections to my own work — read these before trusting anything above

1. **My `scripts/` census was wrong in both directions.** Textual `.<method>(` matching
   missed three writers calling a bare-imported `rename_doc(...)` (no attribute access to
   match) and counted six read-only `SELECT`s as writes. The agent's AST sweep — 11 — is
   the right figure.
2. **I nearly filed a fail-open in a gate shared by ~11 baselines.** I read `exit=0` from
   `$?` after a pipe, which is `tail`'s status. `baseline_shrink_gate.py` returns 1 when it
   cannot resolve the repo. This is the *same* invocation error recorded on 2026-09-03,
   where I blamed the instrument three times for my own bad call.
3. **My self-review on #1103 was wrong about its own code.** "Both call sites are inside a
   `try`" — there are three, and `ponto_pay.py`'s is not one. A non-ASCII token raised
   instead of refusing. Fixed in the *helper*, not the callers: a module whose premise is
   "fixed once, safe everywhere" cannot depend on callers remembering to wrap it.
4. **My mutation evidence described a narrower mutation than my prose.** Under the full
   mutation the wording implied, `test_page_payment_success_coverage` reddens. The tests
   are *more* sensitive than I reported — but "which mutation" is exactly what makes
   mutation evidence mean anything.
5. **I worked from a 50-commit-stale tree** for the first half of the session, including
   the #1074 sweep. The answer happened to match when re-run against `origin/develop`. That
   is luck, not method.
6. **I over-trusted PR state when triaging abandoned branches.** `fix/745` carries a unique
   patch despite its PR merging; `test/357` carries none despite having no PR at all.

---

## The worktree audit — 235 → 1

`git worktree remove` deletes the checkout, not the branch, so commits survive removal.
Only *uncommitted* changes can be lost; those were archived as patches under
`.review-scratch/worktree-rescue-2026-09-07/` first.

- **52 removals initially refused as "locked"**, each naming pid 534326. That pid was *this
  session's own `claude` process* — locks held for agents that had already finished, not
  protection of live work. Check the pid before forcing.
- **Large dirty counts are not uncommitted work.** The biggest (311 files) diffs *against*
  code added on 2026-09-05, net −16,751 lines: a stale file snapshot under a moved HEAD.
- **`git cherry` is the right instrument**, not merge-ancestry or PR state. Nine branches
  hold genuinely unique patches; the rest are superseded.
- **The one that mattered:** `fix/1051-guest-context-disclosure-sweep`, local-only, never
  pushed, committed as *"checkpoint after quota interruption (not reviewed)"* — 17 files
  against four open issues. Its #1052/#1053/#1055 thirds became **#1103**.

**Its #1051 third was excluded because it is wrong**, and that is the reusable part:
`application_status.py` was made to refuse every Guest, but
`membership_application.js:4265` hands every freshly-submitted **anonymous** applicant a
"Check Application Status" button pointing at `/application-status?id=<id>`. The guard
would break that for every new applicant. #1051 stays open and needs the token wired
through the application submit path.

---

## Highest-value open issues

- **#1105** — a **measured** ~10× median timing gap (0.37ms vs 3.83ms over 300 calls)
  distinguishing existing from non-existing docnames in
  `validate_payment_document_access`, despite byte-identical response text; a non-existent
  docname short-circuits on `frappe.db.exists()`. Same class as #1028, and
  `refresh_payment_status` has no rate limit to bound sampling. **Look at this before the
  token pattern spreads further.**
- **#1084's siblings, still open** — #1088/#1089/#1090 include SEPA mandate *write*
  endpoints that could redirect a member's direct debit to an attacker's IBAN.
- **#1097** — 224 Critical Operation Rules name a function that **exists** but is never
  security-decorated, so the rule can never be consulted. This is the complement of #1033
  (closed), which measured name *resolution* and never measured *reachability*. 911 are
  genuinely reachable.
- **#1101** — six endpoints share `validate_member_ownership()` and disagree on whether an
  admin may act for a member: five refuse, one allows. Needs a product decision, not a code
  decision.
- **#1083 / #1076 residual** — `security-permission-check.yml`'s own trigger is still
  `paths: ['verenigingen/**/*.py']`, so a `scripts/`-only PR never runs the permission gate.
  Widening it would redden future PRs on the pre-existing debt in #1095, so it is a
  deliberate call, not a mechanical completion.

---

## Traps worth knowing

- **`$?` after a pipe is the last command's status.** It has now cost two sessions.
- **A locked worktree may be locked by you.** `kill -0 <pid>` before forcing.
- **`git cherry` beats PR state** for "did this work land".
- **Prettier in this repo only *checks*.** A failing pre-commit will not fix the file; run
  `npx prettier --write` yourself.
- **The clone gate blocks a 9th copy of a helper.** When a helper has one call site,
  inlining beats inventing a shared module — an abstraction for one caller buys nothing.
- **`hmac.compare_digest` raises on non-ASCII `str`.** Any guest-supplied token needs the
  `TypeError` caught at the helper.
- **`_board_member_user` is newly duplicated on develop** (2 definitions, baseline 0) from
  PR #1099 and the #966 fix — non-blocking, but unbaselined today.
- The main checkout **fast-forwards on its own**, but not promptly. Check
  `git rev-list --count HEAD..origin/develop` before trusting any grep.

---

## If you do one thing

Re-derive **#1097**'s 224 with a second instrument before acting on it. It is my number,
produced by the same class of census that made #1074 wrong — I stated the boundary in the
issue (it is an upper bound; aliased decorators are not detected; my no-`def` count of 925
disagrees with #1033's 851 and I did not reconcile it), but a boundary written into an issue
is a promise to re-check, not a substitute for it.

https://claude.ai/code/session_01TS8PzQDJZXjpgmtzhVJo7K
