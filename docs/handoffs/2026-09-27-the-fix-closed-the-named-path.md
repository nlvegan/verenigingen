# 2026-09-27: the fix closed the named path; review found the next one

This session picked up from the 2026-09-26b handoff (`docs/handoffs/2026-09-26b-the-guard-could-not-see-what-it-was-guarding.md`).
That handoff and the previous one (PR #1448) were still unmerged. The 26b file ships in the
same PR as this one, with its **Final state** section filled in.

- **Staffing.** Issue units went to sonnet authors. The maintainer lifted the pool cap from 2
  to 5 authors plus reviewers ("put agents on 5 more open issues").
- **Kit.** Everything went through `~/frappe-bench/dispatch/`. `README.md` gained rule 10,
  and `ledger.md` has the per-agent site column for this session.
- **Review.** Every author commit got an independent `skeptical-code-reviewer` before it was
  pushed, on its own test site. Every answering round got either a re-review or a coordinator
  delta check; a delta check was used only for message-only, comment-only and test-only deltas.
- **Merging.** Every merge went through `automerge.sh`: full green CI, the `premerge.sh`
  gates, and a pin to the head commit.

## Decisions made by the maintainer

"Where recorded" says whether the decision is on an issue, or was given in chat and exists
only here and in `~/frappe-bench/dispatch/ledger.md`.

| Subject | Decision | Where recorded |
|---|---|---|
| automerge | Do not restart automerge for #1495/#1508/#1509 until the follow-ups #1504, #1510 and #1511 are fixed. | chat (ledger) |
| #1504 | Fix it now, with **option (a)**: the Role Profiles grant their own literal role (earlier it was ruled "later"). | issue comment |
| #1511 | Not reproducible in 11 runs, so it counts as resolved for the automerge restart once #1509 carries a diagnostic precondition. The issue stays **open**. | issue comment |
| merge order | Merge #1514 and #1515 first, then update #1509 on top of them. | chat (ledger) |
| #1455 | **Option A**: a Direct Debit Batch with ANY invalid invoice is refused at save, naming each invoice; no silent exclusion. The coordinator's design call within it (reported to the maintainer): reject and annotate always succeed; approve and SEPA generation of a now-invalid batch are refused; removing the bad invoice and saving works. | issue comment |
| test sites | STANDING (saved to memory): when test-site pollution is not the bug under study, reset from the snapshot instead of hand-cleaning. | chat (memory file) |
| pool | Cap raised from 2 to 5 authors. | chat (ledger) |

## Test-site reset tooling

- **All 13 test sites were reset** from a snapshot rebuilt from develop, with
  `~/frappe-bench/reset_test_sites.sh --refresh`, run by the maintainer.
- **Fixes to `reset_test_sites.sh`** (bench root, not in the repo):
  - It **forced `developer_mode 1` on every site**, which would have destroyed the CI-parity
    sites 1-5. It now keeps each site's own value.
  - It now defaults to sites 1-13, refuses veg11, passes `--db-root-username root`, and has
    `--refresh`, which rebuilds the snapshot from a real `reinstall` of test_site_1.
- **Claude cannot run it.** The permission classifier blocks reading the MariaDB root
  password, so the maintainer runs it in their own terminal. Passing a password through `!`
  lands it in the transcript.
- **After a reset:** `System Settings.time_zone` is NULL until the first test run sets it to
  Asia/Kolkata. The six ad-hoc SEPA tables are absent, which matches CI. `--refresh` also
  rewrites the timestamp of `verenigingen/public/css/email_brand.css` in the **main** tree;
  discard it with `git checkout`.

## What shipped

**10 PRs merged** in this session; each merge commit is in **Final state**.

| PR | Closes | What | Notable review finding |
|---|---|---|---|
| #1509 (from 26b) | part of #1486 | report-role gate + 3 REPORTING leaks. This session: shard-12 fix, then the Auditor control through the real Role Profile, plus the #1511 precondition | the 3 SEPA-history refusal tests were **vacuous in CI**: the missing table made every call `success: False`. Measured: they passed with the guard deleted |
| #1514 | #1504 | Auditor/Treasurer Role Profiles grant their literal roles; new `Verenigingen Treasurer` Role | the commit message claimed escalation was newly unlocked; it was not (Staff already grants it). Only dues-invoice generate/approve is new. The sweep missed 2 more profiles, so #1512 was extended |
| #1515 | #1510 | six SEPA tables created at `after_install` + `after_migrate`; constructor DDL removed | the first "red" was a `ModuleNotFoundError`; a hook-wiring test added the behavioural red. Develop's `ensure_table_exists` **rolled back the caller's pending writes** (reproduced independently) |
| #1495, #1508 (from 26b) | #1461, #1325 | as described in 26b | merged after the follow-ups |
| #1519 | #1502 | membership_applications page: 3 crashes fixed **and** per-chapter scoping | making the page work re-opened #1486's listing leak unless scoped; the fix ships with scoping. The reviewer filed #1518 (the sibling filters `Active`, while real pending applications are `Pending`) |
| #1521 | #1477 | volunteer-expense Cost Center creator uses the root fallback; `get_fallback_cost_center` scoped by company | the first round still returned **another company's Cost Center** when root creation failed (reproduced). The second round also exposed a test that "passed" only through that bug |
| #1523 | #1467 | `EnhancedTestCase.setUp` registers both drains via `addCleanup`; 3 per-class copies removed | the test's 2 bare commits would have failed CI's "Baseline did not grow" (compared to the merge base); moved into COMMIT_EXEMPT fixture helpers (base=head=1075). Registration order is not pinned by a test (#1522) |
| #1525 | #1484 | chapter-permission check on `get_approval_progress` | the query-count oracle test was flaky 1/5 on the reviewer's site; made deterministic (55/55 on site 2, 10/10 on site 11); the extra query was never reproduced |
| #1526 | #1455 | refuse a mixed Direct Debit Batch (option A) | round 1 blocked **reject** of a batch whose invoice degraded after creation. Round 2 also found two defects already on develop: approve without notes skipped validation, and SEPA XML was generated from stale amounts before any check |

## The pattern: the fix closed the named path; review found the next one

Every author did red/green/mutants honestly, and still nearly every review found a second path
to the same harm:

| Where | The named path, fixed | The next path, found by review |
|---|---|---|
| #1477 | the literal-company-name parent | `ensure_root_cost_center` returning None fell through to the same unscoped fallback: wrong-company Cost Center again |
| #1455 | the mixed batch refused at save | the refusal ran on **every** save, so reject/annotate of a degraded batch threw; approve without notes and generate-before-validate were silent paths already on develop |
| #1502 | three crashes | the fixed page would have **re-opened** a listing leak nobody could confirm while it crashed |
| #1509 | `assertTrue(success)` red in CI | the refusal tests passed with the guard deleted, via the same missing table |
| #1467 | a leak on setUp failure | the fix's own test would have reddened CI through a gate that compares against the merge base, not the PR's file |
| #1510 | constructor DDL removed | the "red" was an import error; nothing tested the hook wiring that CI actually uses |

**Suggested brief line:** after fixing the named path, list every other way the same bad
outcome is reachable (other callers, other lifecycle steps, other failure branches) and put
one test on each, or say why it is unreachable.

## Unexplained and left open

- **#1511.** A Staff fixture user was refused at an `ADMIN_ROLES` guard twice on a just-reset
  test_site_1. It was not reproduced in 11 runs, including the exact refresh-source
  condition, where Redis had no `roles` key at all. A diagnostic precondition is in #1509.
- **#1484's extra query.** The flaky 8-vs-9 query count was never reproduced (55 + 10
  clean runs). The measurement now warms up with both ids.

## Process and coordinator notes

- **Queue race.** A read-modify-write of `approved_prs.txt` while `automerge.sh` ran silently
  dropped #1509 and #1519. This is now kit README rule 10: write the full list in one `echo`.
- **Banned `git stash`, once (#1455 author).** It was disclosed. The coordinator verified the
  shared stack still holds exactly its 2 foreign entries, in order.
- **Agents backgrounding test runs.** Authors and reviewers repeatedly ended turns waiting on
  their own background runs, despite the brief. The harness woke them each time, so nothing
  was lost, but the brief line alone does not prevent it.
- **Coordinator slips, caught before harm:**
  - `gh` run from the non-git `dispatch/` directory broke the first automerge start.
  - `--test` takes method names, not class names, so that run tested nothing.
  - A ledger row said a reviewer was dispatched before it was.
- **A reviewer's site can differ from the author's in a way that matters.** #1484's flake
  appeared only on test_site_11 (`developer_mode=1`), so the confirmation run had to happen
  there.

## Not done

- **Filed this session, open:**
  - Roles and permissions: #1511 (not reproducible), #1512 (3 more Role Profiles; creating a
    `Verenigingen System Administrator` role would switch on bypass-validation gates, so it
    **needs a ruling**), #1517, #1518, #1524.
  - Test tooling: #1513 (the order-dependence scanner is blind to `sql_ddl` commits), #1522.
  - Accounting: #1520.
  - Other: #1516.
- **Still open from 26b:** #1483 (wire and publish the agreement web form), #1507, #1501, the
  #1486 remainder, and the smaller items listed there.
- **Handoffs:** PR #1448 (the 2026-09-26 handoff) is still open.
- **veg11:** see Final state.

## Final state

- **Merged (PR → merge commit):**
  - #1514 → `c56915142`, #1515 → `dd62e7271`
  - #1495 → `91588e1a1`, #1508 → `4e68ce060`
  - #1519 → `ab2926caf`, #1509 → `d5fdcfef9`
  - #1521 → `fc9461ae2`, #1523 → `c9e979aa7`
  - #1525 → `9efec9580`, #1526 → `d4d8f827f`
- **Closed:** #1461, #1325, #1504, #1510, #1502, #1477, #1467, #1484, #1455. #1486 stays open
  for its remainder, and #1511 stays open as not-reproduced.
- **veg11:** migrated at develop `d4d8f827f`. Checked afterwards: the Auditor and Treasurer
  Role Profiles grant their literal roles, the `Verenigingen Treasurer` Role exists, and all
  six SEPA tables are present. Web and workers were restarted via `supervisorctl`, because
  gunicorn preloads the code and a pull is inert until restart.
- **Main tree:** `apps/verenigingen` is at develop `d4d8f827f` and clean.
- **Automerge:** finished with "ALL APPROVED PRs MERGED"; `approved_prs.txt` is empty.
- **Agent worktrees:** the ones under `/home/frappeuser/agent-worktrees/` for merged PRs are
  safe to remove. They were not removed.
