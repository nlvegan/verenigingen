# 2026-10-29/30: the yearly slot could bill monthly

This session ("aanmeldformulier") started as a question and ended as a feature branch. The
maintainer's instructions, in order:

1. Can a Frappe Web Form (copyable in the UI) replace the `/apply_for_membership` template?
2. "sketch the form variant doctype approach"; then, after asking the stakeholder: skip optional
   data, start with "why are you here", follow the Procurios flow at `wordlid.veganisme.org`.
3. "build a separate page and leave this one alone"; brainstorm → design → plan.
4. "feel free to clean up test data" (veg11 Membership Types).
5. "proceed" (commit design + plan, PR); "subagent-driven. proceed".
6. "ask a skeptical review agent to check the work once it's complete, then generate a handoff".

## Decisions made by the maintainer

| Subject | Decision |
|---|---|
| Web Form vs template | Neither as-is: a Web Form saves exactly one doc; the old page creates Address + Member + Volunteer + chapter rows. Build a new page instead; leave `/apply_for_membership` alone. |
| Doors | Three, all in v1: **Regulier, Student, Huisgenoot**. Gift membership dropped. Krappe beurs stays an email process. |
| Doors vs Membership Types | A curated door list (records), not "show every Membership Type". |
| Student | Its own Membership Type (it must be re-approved periodically; amount differs). Same questions as Regulier for now. |
| Questions | Same as the Procurios forms for now, extra-info block included; moving it to a follow-up email is phase 2. |
| Approval | **Every applicant is approved manually**, through the existing flow. |
| Email confirmation | **Keep it** (Procurios-style double opt-in). |
| Gift (when it returns) | Fixed fee, paid once up front, no ongoing giver relationship. |

## What exists now

**PR #1727** (`docs/short-application-page-design`, open, not merged). It contains the design
(`docs/superpowers/specs/2026-10-30-short-application-page-design.md`), the plan
(`docs/superpowers/plans/2026-10-30-short-application-page.md`) and 21 commits implementing it:

- `Membership Application Door` (+ amount and hidden-question child tables). Validates the template
  type and **slot frequency**, and that each tier is at least its template's minimum. Renaming is disabled.
- `Membership Application Submission`: the staging record. Nothing is created until the applicant confirms.
- `api/short_application.py`: `submit_short_application` (guest, rate-limited, honeypot, same
  response for known and unknown emails) and `confirm_short_application` (guest, POST only, HMAC token,
  row lock, savepoint, snapshot check, refusals that all look the same).
- `services/member/application/`: `short_application_validation.py`,
  `short_application_confirm.py` (also the daily `expire_and_purge_submissions`: expire at 7 days,
  purge at 30).
- `www/word-lid.html` and `word_lid.py`, `www/word-lid-bevestig.html`, `public/js/short_application.js`.
  Route rules live in `hooks/portal.py`.
- New Member fields and two admin-editable answer lists (`Membership Join Reason`,
  `Membership Referral Source`), seeded by `patches/v2_2/seed_application_answer_masters.py`.

Verified on test_site_2 (worktree on PYTHONPATH): 7 new modules / 81 tests plus the old application
modules (11 + 35), all green; jest 8/8; pre-commit and pre-push green over `origin/develop..HEAD`;
the clone-family baseline matches the tree.

**veg11:** the 191 leftover test Membership Types were deleted, along with 8 draft test DD batches,
46 test memberships and 228 dues schedules. A backup was taken first:
`20261029_231820-veg11_veganisme_org-database.sql.gz`. Written up in **#1726**, with what was left alone.

## Owed before go-live (in order)

1. **Review and merge #1727.** Nothing on this branch has been through CI yet.
2. **Browser smoke test.** The JS has only jest coverage; this session's Playwright server failed to connect.
3. **veg11 configuration** (after merge: pull the live tree, migrate, restart):
   - a `Huisgenootlid` type with an Annual €0 template;
   - a real Student type with Monthly/Annual templates. The amounts are the association's call; veg11's
     `Student` / `Student Member` are demo data;
   - the three doors (each template must be in the slot matching its frequency, or save fails);
   - check that `creation_user` and the "SEPA Direct Debit" Mode of Payment exist (#1729 M9);
   - by hand: submit, confirm and approve one Regulier. Note whether Huisgenoot approval creates a
     €0 invoice (the spec accepts it for v1).

## Rulings I made (the maintainer has not seen these individually)

Each is recorded in the PR or spec as well. "Cost" is what it costs if the ruling is wrong.

- **New short-form members are opted out of optional email** (no newsletter question on the form;
  opt-in by default is weak GDPR consent). Cost: fewer newsletter recipients, reversible per member.
- **A submission snapshots its membership type.** Confirm refuses if its template no longer fits
  (the door was edited in the 7-day window). Cost: that applicant has to reapply.
- **Reapplying via `/word-lid` keeps** birth date, pronouns, middle name, the opt-out and the
  volunteering choice (the shared helper would otherwise blank them), and **refreshes** the dues
  template and fee.
- **The chapter steps in confirm run as the system user** (`secure_user_context`), mirroring
  `_save_suggested_chapter`. As Guest they fail silently, which is what the old flow does (#1731).
- **A Member who became blocked meanwhile** (e.g. Active) gets the generic "invalid or expired" at
  confirm; the submission is set to Expired.
- **At most 5 join reasons**, and unknown answers are refused (stricter than Procurios).
- Rate limit via `frappe.rate_limiter.rate_limit` (10/h per request IP), not the app's
  `check_rate_limit`, which is dead and keyed on `REMOTE_ADDR` (#1732).
- **Country list** = Verenigingen Settings `available_countries` entries that exist as Country
  docs; "Other" is dropped.
- **Card/intro text** are Text Editor fields, rendered through `sanitize_html` (the spec said Text
  Editor; the first build had Small Text).
- **A hidden magazine/starter-guide question** counts as "not postal" for the postal minimum.
- Smaller placement calls: pages in `www/`, the patch in `v2_2`, hidden questions as a plain child
  table, confirm with no commit of its own.
- **Parked, not fixed** (all in #1729): the savepoint-gone path still commits partial rows; a
  template's frequency edited between submit and confirm; nested links in card text; editing a slug
  breaks its URL; answer-list rows deleted mid-window; `allow_custom_amount` not enforced
  server-side; house number not required server-side; seed missing on fresh installs; the payload
  keeps PII after confirm.

## Issues filed this session

- #1726: veg11 test Membership Types (cleaned up; leftovers listed)
- #1729: `/word-lid` residual review items
- #1730: **old flow:** a reapplication keeps the OLD dues template and fee
- #1731: **old flow:** the chapter steps run as Guest, so no Pending Chapter Member and an error
  message on a successful application (#1595 cross-linked)
- #1732: dead `check_rate_limit` (`REMOTE_ADDR`, fails open)
- #1733 student re-approval · #1734 welcome + follow-up email · #1735 postcode autofill

## What went right, and what nearly didn't

- **The whole-branch skeptical review found what seven task reviews could not.** Each task was
  approved on its own terms, but the door accepted any template in either slot. An applicant who
  ticked "yearly" for €60 would have been approved on a **Monthly** schedule at €60, 12× the
  agreed amount, collected by SEPA. No per-task diff contained both halves of that. The same review
  found that a reapplication via the short form re-subscribed opted-out members and blanked their
  date of birth (the old form re-asks those fields; the new one doesn't), and that the
  end-to-end approval test could not fail on the template. The reviewer proved that last one by mutation.
- **Copying a call "exactly as the old flow does" copied its bugs.** The Task 5 brief said to reuse
  the chapter helpers the way `submit_application` does. They fail as Guest there too, so the copy
  inherited a silent failure (#1731) until a reviewer asked the system (`has_permission`,
  `can_request_system_escalation`) rather than the source.
- **One discovery was dropped.** Six old `submit_application` tests "failed on the untouched tree" in
  one run, then passed 11/11 in a later run on the same site. Treated as site state, not filed.
- **A tooling note for worktrees:** the doctype-name pre-commit hook resolves apps from the live
  tree. When a commit adds DocTypes, commit from the worktree with `BENCH_APPS` pointing at a
  symlink dir whose `verenigingen` is the worktree. That makes the hook stricter, not weaker; never use `--no-verify`.
