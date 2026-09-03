# Handoff — 2026-09-03d: 1 of 225

Continues [2026-09-03c](2026-09-03c-the-green-was-borrowed.md), which was still an open
PR (#787) when this session began and was merged during it.

**7 PRs merged, nothing left open; 6 issues closed, 6 filed. Every fix went through a
pre-PR skeptical review, and in every single case the review found more than the fix
did.**

The title is the session's hardest measurement. `block_inappropriate_mocks.py` was wired
live in `.pre-commit-config.yaml` with `fail_fast: true`, and across 1352 in-scope test
files it detected **1 of 225** mocks naming a prohibited target. It had never once
rejected the thing it existed to reject — while being cited, in a review earlier the same
day, as evidence that a change was acceptable.

That turned out to be the shape of nearly everything found:

| what it reported | what was true |
|---|---|
| `block_inappropriate_mocks`: pass | detected **1 of 225** prohibited-target mocks |
| the savepoint ratchet: **0 offenders** | both bugged sites were sitting in front of it |
| #701's own new test: pass | deleting the branch its docstring guards left it green |
| #783's two tests: pass | the call under test raised `TypeError: unexpected keyword argument 'chapter_name'` |
| #461's `skipTest` guard: never skipped | its condition can never be true on any site |
| #774: batch collected 337 of 340, "success" | the shortfall went to `frappe.logger()`, dropped on level |
| `_is_test_file`: file checked | 9 real test modules invisible to **every** check (#798) |
| `get_data`: filtered by member | never reads `filters.get("member")`; 5 of 7 callers pass on other members' rows (#792) |
| **my own** dedup in the #793 fix | a second prohibited target on the same line was silently dropped |

**A dead gate is worse than no gate, because it launders approval.** That is the sentence
to carry forward. Three separate times this session, something was accepted partly
because a gate had not objected, and in each case the gate could not have objected.

## What merged

- **#790** closes the remainder of #780. The public form, the desk form and
  `setup_dutch_name_fields()` no longer decide Dutch name handling from a Redis-cached
  scan for any Netherlands company. One declared setting,
  `Verenigingen Settings.enable_dutch_name_fields`, read by one function body.
  A new field rather than `System Settings.country` (which *is* `'Netherlands'` on veg11)
  because **tussenvoegsels are Flemish too** — country would silently exclude a Belgian
  association. The seeding patch is load-bearing, not cosmetic: an unseeded `Check` on a
  Single doctype reads as **`0`, not `None`** (`cast_fieldtype("Check", None) -> 0`,
  identical on the CI frappe tip), so the JSON default never reaches an installed site
  and without the patch veg11 would have silently stopped offering the field on deploy.
- **#791** closes #461. The `account_type = "Expense"` fee-account fallback is deleted
  rather than widened — widening a fallback from "matches nothing" to "matches something
  arbitrary" converts a loud failure into a silent misposting on a money path.
- **#794** closes #783. Two `send_overdue_payment_reminders` "partial failure" tests could
  not fail; a third instance was found by sweeping for the pattern.
- **#795** closes #701. Three hand-written savepoint rollbacks converged onto the
  canonical helpers, and the ratchet widened so it can see the shape it was built for.
- **#799** closes #793. One owner for mock policy, one detector.
- **#787**, the previous session's handoff, which had been sitting open.

- **#797** closes #774. A short SEPA batch stops reporting plain success: the shortfall
  is recorded on `batch_log` and in the Error Log, the per-invoice logging is capped at 10
  per reason (300 nonexistent invoices previously wrote **exactly 300 permanent MyISAM
  rows** in ~1.09s), and the batch takes a distinct `"Partially Collected"` status.
  **This one needs `bench migrate` or `bench reload-doctype "Direct Debit Batch"` before
  the next collection run** — see "a fix that was briefly more dangerous" below.

All merged with 12/12 shards green, verified at `per_page=100` rather than from a
truncated check listing. #799 legitimately runs no shards: the Tests workflow is
path-filtered to `verenigingen/**/*.py|js`, and it touches only `scripts/` and `docs/` —
the check that does cover it (`🚨 Test Quality Guard`, which unit-tests the enforcer,
runs the whole-tree ratchet, and regenerates the baseline) is green.

## Two claims of mine that were false, and how

Both were **confirming** evidence read as **discriminating**, which is the failure mode
this repo's own rules name first.

1. **"No pre-existing baseline key's count rose."** One did:
   `test_agreement_type_determination::DATABASE MOCK`, 1 → 2. I had compared the baselines
   line-by-line; diffing them **key-by-key** is what showed it. Worse, I had put the claim
   into a permanent test docstring, where it would have been read as measured fact for
   years.
2. **"`test_payment_entry_factory.py` is a live f-string blind spot."** That file is not
   scanned at all — `_is_test_file()` excludes any filename containing `_factory`, so it is
   invisible to every check the tool runs, before and after my change. I read its mock
   calls and judged them live **without running the tool against the file**. The verified
   citation is `test_ponto_webhook_handler.py`. Chasing the error produced **#798**.

The generalisation, and it is not new: reading source tells you what code says, not what
the system does. Both times the 60-second empirical check existed and I skipped it because
the source looked conclusive.

## Instrument failures — three, all mine

- **A CI waiter reported "30 success, settled".** GitHub's default `per_page` is **30**, so
  it was counting pending checks on a **truncated first page**. The PRs actually carry 46.
  It could have declared settled with a dozen checks unread. Same class as the
  `grep | head -10` in 03c.
- **A single-line regex proxy** of the enforcer's own rules reported "167 visible" where
  the real validator reported **1**. I used the tool's answer for the decision, but the
  proxy's number reached a commit message before being caught.
- **Verifying #701's widened ratchet took three attempts, two of which measured nothing.**
  First I ran the two arms with different `-k` filters (not comparable). Then I ran pytest
  directly in a detached worktree, where the test's `frappe.init("test_site")` fails —
  producing an identical `11 errors` in *all three* arms, which would have supported
  whichever conclusion I wanted. Only `bench --site test_site_4 run-tests` with
  `PYTHONPATH` discriminated.

**The pattern in all three: an instrument that cannot distinguish two states, reporting
confidently.** Before trusting a check, confirm a failing case looks different.

## GitHub closed a live issue because of a sentence

**#792 was auto-closed by prose.** The #783 commit says, under a heading reading "Filed
for follow-up, **not fixed here**":

> ...worth having on record here for whoever **fixes #792** or #793 next.

GitHub parses `fixes #<n>` anywhere, including mid-sentence in text that says the
opposite. Reopened, with the mechanism recorded on the issue.

**Refer to an issue you are not closing without a keyword in front of it** — "see #792",
"tracked in #792". `whoever fixes #792` and `closes #792` are the same string to GitHub.

## Filed

- **#788** — `stock_account_handler.py:190` sets `account_type = "Asset"` (not a valid
  option) then `insert()`, so the fallback **always raises**, and an
  `except Exception as e2:` swallows it. eBoekhouden opening-balance import. **Highest
  severity of the set**: unlike #461's instance, which failed loudly, this one falls
  through silently on a money path.
- **#789** — `create_period_closing_vouchers.py` scans
  `account_type IN ('Income','Expense','Cost of Goods Sold')`; only COGS is valid, so the
  P&L imbalance scan misses every income and expense account. Low severity, likely
  already run.
- **#792** — `get_data()` silently ignores a `member` filter. 7 callers pass it; **5 pass
  only because other members have overdue invoices**. On a fresh site all seven would go
  green for the wrong reason.
- **#793** — closed by #799.
- **#796** — `generate_sepa_xml_for_batch` unconditionally `db_set`s `status = "Generated"`
  without reading the prior value, so **every** submitted batch loses any pre-submission
  status. Makes #797's structured signal inert on auto-submit sites.
- **#798** — the `_factory` filename exclusion, above.

Also added an instance to **#490**'s census: `test_payment_report_integration.py:464`
wraps its own assertions in `except Exception as e: self.assertIsInstance(e, Exception)`.
It is the cheapest remaining site to convert — it already injects a real failure, so only
the swallow disarms it.

## Corrections to the record

- **The persona test's Phase 5 does not "report success without running".** I said it did;
  both enclosing methods carry `@unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)` — the
  `Volunteer Expense` doctype was archived and its table dropped. I had read the function
  bodies and missed the decorator one line above.
- **"A ratchet baseline must fail on shrinkage" is not this repo's convention.** I briefed
  two agents with it. `bf379a4fe fix(ci): stop ratchet baselines reddening on pure
  shrinkage` made them fire **upward only**, deliberately; `regressions()` returns only
  keys whose count rose. #701's own gate is a hard zero-tolerance
  `assertEqual(offenders, [])`.
- **`gh issue view` and `gh pr view --comments` are broken on this box** (GraphQL
  Projects-classic deprecation). Use `gh api repos/<o>/<r>/issues/<n>` and
  `.../issues/<n>/comments`. This cost the first two attempts at reading any issue.

## A fix that was briefly more dangerous than the bug

Worth reading before adding a Select option anywhere. #774's fix sets
`status = "Partially Collected"` so a short batch stops reporting success. Two things
nearly went wrong:

1. **Reclassifying the status hid the batch from monitoring.** Five queries filter
   `status == "Draft"` as "needs attention" — a stuck-batch alert, a **live Zabbix
   trigger**, an approval queue, and two conflict detectors. A shortfall batch became
   invisible to all of them at exactly the moment it most needed a human. My instruction
   caused that: I asked for the status change and told the agent to grep readers, and its
   grep was scoped to the submission pipeline. Grepping the *pattern* found all five.
2. **Frappe validates a Select against the DocField's CACHED options.** On a site whose
   doctype has not been reloaded, `_validate_selects` **throws**:
   `ValidationError  Status cannot be "Partially Collected"`. So in the window where code
   is live but the cache is stale, an unguarded write would take down the entire monthly
   collection run rather than merely under-collecting. The write is now guarded on the
   option existing in meta — the same shape as #780's `has_field` guard, for the same
   window.

## For next session

1. **#798** is the cheapest high-value item: 9 test modules currently exempt from every
   check. Expect the baseline to grow; that is the point, and the ratchet fires upward
   only so recording them blocks new ones without demanding the debt be paid first.
2. **#792** is the most likely to bite a user — a report filter that silently does
   nothing. When it is fixed, five `count > 0` tests will start failing. **That is the fix
   working.** Tighten them to the member under test; do not loosen them.
3. **#796** wants a decision, not a patch: `status` is carrying both a lifecycle stage and
   an outcome, with three similar `Partially *` strings whose meaning depends on when you
   look. `sepa_file_generated` already carries "XML written".
4. **#788** is the highest-severity filed item — an always-raising fallback on the
   eBoekhouden money path, swallowed.
5. **#785** remains the maintainer's call (check-then-cache at the two sites where an
   authorization check still lives inside a cacheable body).

**And the habit that produced all six issues:** not one came from reading the tracker.
#788 and #789 came out of reviewing #461's class sweep, #792 and #793 out of reviewing
#783's fix, #796 out of reviewing #774's, #798 out of reviewing my **own** #793 fix after
review had already corrected it once. Three of them were invisible to any grep for the
original issue's keywords. **Review the round that answers the review** — twice this
session the second review found a defect the first had created.
