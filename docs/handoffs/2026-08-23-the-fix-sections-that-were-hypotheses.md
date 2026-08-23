# 2026-08-23 — the fix sections that were hypotheses

Eight issues worked by agents, seven skeptical reviews, two PRs merged, four opened, eight issues
filed. The changelog is at the bottom. The two things worth carrying forward are both about
*instruments*, not code.

---

## 1. An issue's evidence is authority. Its "Suggested fix" is a hypothesis.

This held **8 for 8** today. Every issue's measurement survived scrutiny; every issue's proposed
remedy, and every issue's estimate of its own scope, was wrong.

| issue | what it proposed / claimed | what was true |
|---|---|---|
| #516 | a `db.exists` guard inside `test_dues_invoice_workflow` | the raise is inside `super().setUpClass()` at `base.py:99` — a guard in the reporting module is **structurally incapable of firing**. Correct altitude was `ensure_netherlands_territory()`, fixing 15 consumers instead of 1 |
| #516 | 7 sites, line numbers given | **each off by one**; an 8th site missed; two files never mentioned |
| #514 | a `stream` setter that is `pass` | **reddens 8 tests, 7 pre-existing** — `Handler.setStream` then reports a stream it did not install |
| #514 | "`tests/setup/__init__.py:14` is the only module-level call" | `enhanced_test_factory.py:204` is a second, and is the one covering most modules |
| #515 | #511 unmasked the accumulation; two remedies offered | delta is **identical on develop**; option A is already the `name=None` behaviour and option B is dead code (zero `cleanup()` calls at the accumulating sites) |
| #466 | 2 nonexistent fields | **4** |
| #513 | "worth grepping for a third" | **5** instances |
| #531 (mine) | both count assertions blocked by a literal cross-reference | only one is; the other is a **one-line** fix |
| #530 (mine) | "no local site can exercise the branch" | a test **already exercises it** (`test_chapter_cost_center_seeding.py:84`), and the seeder runs **mid-suite from 46 call sites**, not just `before_tests` |

**How to brief this:** treat the evidence section as authority and the fix section as a hypothesis to
test. Re-verify every line number against the actual base branch. Locate the frame where the failure
is *raised* before choosing a fix altitude. And re-run the census — the scope is consistently too
small, because the author measured the symptom well and then reasoned about the remedy from reading.

## 2. Seven reviews changed seven verdicts. None found a bug in the code; all seven found bugs in the *prose*.

Not one review rejected an implementation. Every one found that the sentences justifying it were
wrong — and in this repo the comment explaining a fix is the next person's search query, so wrong
prose is the durable liability.

- **#525**: "0 of 708 rows dangle today" — measured **72 of 91 dangling on test_site_2**, 40 of 1284
  on test_site_4. The narrow claim (nothing dangling on *borrowable* chapters) survives; the sentence
  does not. Also: the handler catches `LinkValidationError` from the **whole Chapter**, and
  test_site_2 has 2 dangling `Chapter Board Member.volunteer` rows — so the new log line would report
  a board-link failure as "a stale roster row", which is worse than silence. And "the swallow is
  load-bearing" is unestablished: a bare-`raise` mutant passes both consuming modules, and the
  sibling `with_team_assignment` has no `except` at all.
- **#524**: the PR's own control column was **stale** — the installed checkout was 8 commits behind
  develop (29 vs 34 `def test_` in one file), so a "32/32 branch vs 27/27 control" delta was other
  people's merged work presented where a reader attributes it to this change. *The instrument, not
  the method, was wrong.*
- **#526**: the fix **loses** records emitted from `tearDownClass` — `stopTestRun` never drains
  `_module_or_class_*_capture`. Measured with a control. 9 harness-logger-backed class-teardown sites,
  including one of the 13 that #512 just converted. So it trades a hypothetical loss for a measured
  one, and is not a strict improvement.
- **smoke chapter**: the stated mechanism was wrong — the drain's `force=True` delete **never runs**
  (0 `Deleted Document` rows against a positive control of 63); `tearDown`'s `frappe.db.rollback()`
  does the work.
- **EUR sweep**: the raw-SQL decoy can **permanently corrupt a CI site**, because one call site
  commits inside the window and `tearDown`'s rollback then resurrects the uncommitted `DELETE`, which
  the drain commits. Third recurrence of #489/#407/#486.

**How to brief this:** ask the reviewer to attack the *justification*, not just the diff, and to say
which numbers it re-measured. Two reviews retracted their own first findings after checking — that is
the behaviour to reward.

---

## Traps worth remembering

- **`TestCase.run()` does not invoke `setUpClass`.** Verified. This is why #524's sweep missed a 9th
  site: `test_harness_leak_attribution.py:915` runs a nested case via `case.run()`, so no harness
  seeding happens. A sibling 400 lines later uses a suite and *is* covered.
- **A source guard matching a *string* is satisfied by a comment.** Demonstrated. #524's guard passes
  if `ensure_root_territory` appears anywhere in the file. An AST walk for a `Call` would have caught
  the 9th site above.
- **#527's ratchet misses the shape all five of its callers use** — it matches direct `Name` calls, so
  `try: cls._setup_sepa_configuration()` sails through. The PR's mutation tested the *direct* call
  site: confirming evidence about the shape it catches, not discriminating evidence about the shape it
  misses.
- **`buffer=not debug`** — `frappe/commands/testing.py:147`. Under `bench run-tests --debug` the
  streams are never swapped, so #514 cannot occur at all.
- **`frappe/testing/environment.py:164` runs `pkgutil.walk_packages` over every installed app**, so
  `verenigingen.tests.setup` is imported before `startTestRun` unconditionally — `--skip-before-tests`
  included. #514's latency is a *framework guarantee*, not import-order luck.
- **CI gives each shard its own `mariadb:10.6` container** (`_base-server-tests.yml:64-66`), so
  cross-shard fixture collision is impossible. `enhanced_test_factory.py:1395` still claims "8 shards
  as parallel processes on ONE shared DB" — **stale, and load-bearing for other fixture decisions.**
- **`frappe.get_app_path` already is both anchors** (27 users; `test_harness_logger.py:222` does
  exactly `Path(get_app_path(...)).parent`). The new `tests/utils/paths.py` hand-rolls `parents[3]`,
  so the depth-fragility it exists to remove now lives inside it.
- **Upstream frappe, two bugs, neither filed:** `result.py:109-110` pops the stdout/stderr stacks
  **crosswise** (alternates by parity of `stopTest` count, hence "intermittent" mislabeling); and
  `stopTestRun` never drains the class-level capture. Filing is a third-party repo, so it needs a
  human call.

---

## Where things stand

`develop` @ `09a6f57c`. **Merged:** #511, #512.

| PR | branch | review verdict | blocking work |
|---|---|---|---|
| #524 | `fix/516-territory-root-fixture` | merge **with changes** — CI **43/43 CLEAN** | guard the 9th site (`leak_attribution:915`); add `tests/utils/base.py` to `UNGUARDED_CALLS` and assert named calls are *found* (deleting `base.py:99` leaves the suite green — the ~289-file half of the fix is unpinned); fix 2 body claims. Its review's third blocker — "the shards have not run" — is now **answered**: 43/43 at shard scale, which matters because this edits `tests/setup/__init__.py`, on every test's setup path |
| #525 | `fix/515-builder-must-not-mutate-borrowed` | merge **with changes** — CI **43/43 green** | 4 prose corrections (posted on the PR); consider register-then-re-raise |
| #526 | `fix/514-harness-logger-lazy-stream` | merge **with changes** — CI **41/43**, co-tenancy | document or mitigate the class-teardown loss; correct the mutation table (3 red, not 2) |
| #527 | `fix/513-466-sepa-setup-never-applied` | merge **with changes** — CI 1 red shard, co-tenancy | per-test re-assertion in `test_sepa_xml_compliance` + `test_api_regression` (one line each, copying DDB `setUp:91`); broaden the ratchet |

**#526 has one red shard (5/12), and it is CO-TENANCY, not the diff.** Root cause is
`test_tussenvoegsel_name_handling_integration` (`full_name 'Jan Bergen63758233217'` should start with
`'Jan van Bergen'` — the tussenvoegsel is dropped entirely, and the numeric suffix is the factory's
own uniquifier on `last_name`). The `writeln` `AttributeError` is downstream: a failing `subTest`
calls `self.stream.writeln()` and frappe's `TestResult.stream` is a raw `TextIOWrapper` on
**Python 3.14.7** — which is also why the shard reports `Failing: 0, Errors: 1`.

Evidence, now complete:

| run | tests | failing | errors | that test |
|---|---|---|---|---|
| #525 shard 3/12 | 1853 | 0 | 0 | **ran and passed** (confirmed by log, not by absence) |
| #526 shard 5/12 | 1939 | 0 | 1 | failed |
| local, develop, standalone | 7 | — | — | passed |
| local, #526 branch, standalone | 7 | — | — | **passed** |

Same base, different packing. It passes standalone against #526's own code, so **the diff does not
cause it in isolation** — but the baseline header's warning applies: a green local run is not
evidence. **The baseline has 0 active entries**, so any failure fails the gate and this blocks #526.

**Next step is a bisect over co-tenants, not more local runs.** 25 modules precede the failing one in
#526's shard 5 and are absent from #525's shard 3. Full list saved at
`scripts/testing/notes/526-shard5-unique-predecessors.txt` (below). The most suspicious is
`verenigingen.tests.test_harness_leak_attribution` — it deliberately plants and force-deletes
fixtures, and it is a file #526 edits. Note `run-tests --module A --module B` silently runs only B,
so reproducing co-tenancy needs `run-parallel-tests` or a driver script.

## develop carries latent order-dependent failures, and the baseline has 0 entries

Two of the four PRs went red on modules they never touch, and the third was fully green. This is the
single most useful operational fact from the session, because it means **a red shard on these PRs is
not evidence about the PR**.

| PR | red shard | failing module | is it in the PR's diff? | same module on green #525 |
|---|---|---|---|---|
| #526 | 5/12 | `tests.integration.test_dutch_business_rules_phase3` | no | **ran and passed** (shard 3/12) |
| #527 | 1/12 | `tests.www.test_dues_www_pages_coverage` (3 tests) | no | **ran and passed** (shard 12/12) |
| #525 | — | — | — | 43/43 green |

Both were checked the way CLAUDE.md prescribes and both came back clean:

- **#527**: zero hits in its shard log for *every* string it introduces
  (`SEPAConfigurationNotApplied`, `sepa_test_configuration`, `apply_sepa_test_configuration`,
  `verify_sepa_configuration`, `webhook_user`). And the mechanism its review flagged as PLAUSIBLE —
  five modules now committing `Verenigingen Settings.company` site-wide with no restore — **cannot
  apply**: none of its six modified modules runs before the failure in that shard (position 84 of 99).
- **#526**: passes standalone against its own code and against develop; 25 predecessor modules differ
  between the two shards (list committed under `scripts/testing/notes/`).

`verenigingen/tests/known_test_failures.txt` has **0 active entries**, so any of these fails the gate.
The practical consequence: **re-running does not help** (it reproduces the same packing
deterministically), and a green local module run is explicitly not evidence — the baseline file's own
header records five failures that passed locally and failed in every shard. The work is a co-tenant
bisect, per red shard.

## One real bug the logs surfaced: #537

`Failed to restore Ponto Settings: Sandbox Client ID is required when Sandbox Mode is enabled` —
**4× in #527's shard, 4× in #526's, 17× `Failed to restore` in #525's.** `SingletonBackup.restore()`
captures a state it cannot write back, so the Single stays contaminated for every later class.

This is #513's class, and it is audible **only** because #512's logger conversion merged today — the
message is in `HARNESS_FILES` precisely because a wrongly-restored Single "said so nowhere (#433)".
Which closes a loop: **PR #526 would re-silence it**, since `restore()` is called from
`tearDownClass` in 8 of the 9 affected modules and #526 loses class-teardown records. Filed as #537
with the unmeasured half named (nobody has checked what the surviving value breaks, and the 17-count
on #525 was not partitioned by doctype).

**Three unpushed branches**, all reviewed:

| branch | verdict |
|---|---|
| `fix/borrowed-eur-company-scans` | open PR **after C1 + C2**: the decoy can permanently corrupt a site; the `setup/__init__.py:700` allowlist reason was disproved (see #530) |
| `fix/smoke-chapter-self-accumulation` | open PR **with changes**: correct the mechanism, fix a stale test name in the message |
| `refactor/app-root-and-territory-clones` | **split into two PRs after a rebase** — it does not merge onto its own base (`paths.py` conflict with `d772f3ad`) |

**Issues filed:** #537 (SingletonBackup cannot restore Ponto Settings), #528 (setUp reverts any per-class Single config — the biggest; census of what else it
breaks has never been run), #529 (`_create_sepa_xml_structure` exists nowhere), #530 (harness currency
scan, *corrected — higher priority than filed*), #531 (newsletter counts, *corrected*), #532 (109
no-filter Company scans, sort the opposite way), #533 (four chapter names with two owners each), #535
(five production settings pinned to hardcoded defaults — **#466's class in production code**).
**Closed:** #519 as duplicate, folded into #490.

**#490 is answered**, and the answer overturned the prediction: those swallows hide **no** broken SEPA
XML. As shipped, 0 pass / 0 fail / **32 of 32 never execute**, behind three independent gates. Lift
all three and 4 of 8 tests fail — every failure a defect in the *test* (e.g. `root.get("xmlns")` is
`None` because ElementTree folds namespaces into tag names, so that assertion can never pass on any
XML). Sequencing consequence: **#528 and #529 want fixing before the swallows come out**, or
unswallowing just converts silent passes into errors naming the wrong cause.

## Process failures worth not repeating

1. **Four PRs were opened without a skeptical review**, and Foppe had to ask for the third time.
   Reviews then changed all four verdicts to "with changes". Run the review *before* opening.
2. **I shipped a `paths.py` docstring that was wrong** in exactly the way the module exists to prevent
   — it listed `parents[3]` as an app-root depth when from `tests/backend/portal/` that is the
   *package*. Acting on my own follow-up would have retargeted two files one directory up.
3. **I briefed an agent that #445 was open.** It had been closed two days earlier by `275a906a`, an
   ancestor of develop — my own "the merged tree is the authority" rule, unapplied to a premise.

## Housekeeping

- A **stale worktree from a previous session** still holds #511's merged branch
  (`/tmp/claude-1000/.../86003363-.../scratchpad/wt-498`), which is why that remote branch survived
  the merge. Needs `git worktree remove` before the branch can be deleted.
- `verenigingen/public/css/email_brand.css` carries an uncommitted one-line change predating this
  session.
- `/home/frappeuser/frappe-bench/CLAUDE.md:173-174` still advises hand-rolling an AST walk for
  "same-named **module-level** functions" — inverted since `275a906a`. Not in any git repo.
