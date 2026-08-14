# Handoff — 2026-08-14: the ratchet and the telescope

Session goal was "merge #330, then pick the next thing". #330 landed, and the next thing
turned out to be the other half of #328: the leak instrument built in #329 had nothing
consuming it, and the shard layout that decides which collisions surface was still
undrawn on purpose. Both now exist and both have already reported real findings.

## Landed

| PR | | merge |
|---|---|---|
| #330 | the drain cancels submitted docs and drains in dependency order | `be5a31aa` |
| #332 | the leak ratchet + coverage for the second test base | `72bd3541` |
| #333 | seeded chaos layout + nightly workflow | `2e0ea85e` |
| #334 | the chaos partition step must run from `sites/` | `7f87e1be` |

Both CLAUDE.md files were corrected too (they are outside git, so there is no commit):
the false claim that branch work can only be verified by CI, plus new sections on
marking shared fixtures and on reading a red shard.

## The leak ratchet is live

`scripts/testing/check_test_leaks.py` + `verenigingen/tests/known_test_leaks.txt` gate
every shard: per-**module** leak counts may only fall. Confirmed running and passing on
all 12 shards of a PR run *and* of the develop-push run for `72bd3541`.

**The census, from CI's fresh per-shard sites: 594 leaked records across 71 modules**,
all 12 shards complete. Against the pre-#330 floor of 2,097 from 681 modules — and that
run never finished. Heaviest: `test_membership_dues_schedule` 36,
`test_real_world_dues_amendment_scenarios` 33, `test_membership_endpoints` 33.

Coverage was the half nobody had noticed. `VereningingenTestCase` is **not** a subclass
of `EnhancedTestCase` — it is a sibling base carrying ~450 test classes — and it already
recorded which tracked documents it failed to delete, as a human-readable "CLEANUP
SUMMARY" block. A gate reading only the other base would have called the suite clean
while half of it leaked. Both bases now emit the same line via `leak_guard.report_leaks`.

**What the ratchet still cannot see**, stated in the baseline header rather than left
implied:

1. An orphan whose parent deleted cleanly. The drain reports what it FAILED to delete,
   so zero GL Entry leaks are listed — yet orphan GL Entries broke a test in the very
   run that seeded the baseline (`voucher_no` is not unique: the naming-series counter
   rolls back with the test transaction, committed GL rows do not, so a later invoice
   reuses the number and inherits them).
2. ~950 test classes on uninstrumented bases: 562 on plain `unittest.TestCase` (no
   rollback at all, so the likeliest leakers) and 388 on raw `FrappeTestCase`, plus
   three classes whose `tearDown` skips `super()`.
3. A module whose TestCase classes are imported by another module runs in two shards and
   each sees a partial count. Four such imports exist; none of those modules leaks yet.

## The chaos layout found something on its first working run

`show_test_shards.py --seed N` permutes both halves of order-dependence — shard
membership *and* execution order within a shard — where CI's own split is a pure
function of the weights and therefore identical on every PR. `chaos-shards.yml` runs it
nightly, report-only.

Seed **20260814** found **two** order-dependent modules in the eight shards checked
before handoff. Both fail in-suite and **pass solo**, which is the collision-victim
classification the detector exists to make:

| shard | finding | solo |
|---|---|---|
| 6 | `tests.backend.unit.services.test_payment_history_service.TestPaymentCoverageService.test_get_coverage_from_schedule_found` (1 failure) | 22 tests, 0 failures |
| 7 | `tests.backend.comprehensive.test_reconciliation_edge_cases` — 4 errors across `TestDuplicatePaymentDetection` and `TestPartialPaymentReconciliation` | 30 tests, 0 errors |

The other six checked shards were clean (2, 3, 4, 9, 10, 12 — 1597 to 2290 tests each).

**Replay is proven, not asserted.** CI's `chaos_modules_N.txt` was byte-identical to
lists generated locally from the same seed — same members *and* same order — for
**8 of 8** shards checked. Recipe:

```bash
cd ~/frappe-bench/sites
../env/bin/python ../apps/verenigingen/scripts/testing/show_test_shards.py \
    --seed 20260814 --modules-for 6            # the exact list CI ran
gh workflow run chaos-shards.yml -f seed=20260814   # or re-run the whole draw
```

## Findings worth keeping

**Never seed a leak baseline from a local test site.** Measured on the same suite and
commit: shard 4 leaked **3 records locally versus 54 in CI**, shard 1 two versus 15. A
warm site under-reports, because the rows a delete would trip over are often already
there or already gone. This is #308's "a green solo run on test_site_1 is not evidence",
quantified — and in the direction that would have baked a far-too-low ratchet.

**Importing `frappe.testing` requires cwd = `<bench>/sites`.** Its log handler path is
`os.path.join("..", "logs", ...)` — relative — and it is opened at import time, so
anything importing `parallel_test_runner` dies before running. This is what failed all 12
shards of the first chaos run.

**Shard weight tracks the test COUNT for files absent from `test_timings.json`.**
Measured: adding one test class took `test_harness_leak_attribution` from 19.0 to 20.0,
which moved it shard 9 → 4 and re-packed everything downstream, dropping
`test_sepa_performance_optimizations` from shard 1 into shard 2 ahead of its victim. You
can predict this before pushing, with no CI round-trip, by diffing
`show_test_shards.py --find <mod>` against the same command under
`PYTHONPATH=<worktree>`.

**A base change does not retrigger CI, and `gh pr close && gh pr reopen` is the cheapest
fix** (`reopened` is a default `pull_request` type) — no dummy commit needed. Also
`gh pr edit --base` still fails here with the Projects-classic GraphQL error; use
`gh api -X PATCH .../pulls/N -f base=develop`.

**A green PR based on develop can still have skipped the whole suite.**
`server-tests.yml` has a `paths` filter, so a PR touching only `scripts/**` shows 25/25
green with no `Tests (N/12)` at all. Read the check *names*, not the count. Tools under
`scripts/testing/tests/` are covered instead by `code-validation.yml`, which discovers
them by pattern — a new test file there needs no wiring.

## What went wrong in how I worked

**My end-to-end smoke test ran the right pipeline from the wrong directory, and the
environment hid it.** From `~/frappe-bench`, frappe's `../logs` resolves to
`/home/frappeuser/logs`, which exists on this box for unrelated reasons, so the partition
step silently worked; on a runner it does not exist and the identical command died at
import. I only found it because I ran the workflow instead of trusting it. Reproducing it
locally needed a cwd whose parent has no `logs/`.

**Three of my own tests could not fail, and my mutation battery missed all three** — a
skeptical review found them. The dangerous one: dedupe keyed on `(test_id, record)` could
be narrowed to `test_id` alone with every test still green, and that mutant silently drops
every record after the first that one test leaks — the normal shape. Lesson: **mutate in
the direction that would be invisible.** An over-count fails loudly next run; an
under-count is a gate quietly reporting less than it should.

**A test that fabricates a leak and prints it poisons the gate.**
`LeakCheckReportingTest` handed `_finalize_leak_check` an invented row and let it print,
so `Territory::zz-x boom` reached the shard log indistinguishable from a real leak. The
baseline was one merge away from carrying a fictional entry. Anything exercising a
reporting path must capture stdout.

**My first positive control reported nothing, and I nearly believed it.** It created both
parent and child Territory under capture, so the drain deleted them in dependency order —
no leak to observe. Had I trusted it, I would have launched a 3-hour census against an
instrument I had just "confirmed" was silent.

**One review finding was wrong and I checked before implementing it.** The proposal to
delete four cross-module TestCase imports would have broken the files that reference them
(`test_comprehensive_suite_demo.py:179,240`, `test_helpers.py:102`). The underlying
double-run risk is real and is documented instead.

## Next

1. **The two findings above.** Both are reproducible today: replay seed 20260814 for
   shard 6 or 7 and bisect the prefix with `order_dependence_detector.py` to name the
   polluter. Neither has been triaged beyond "passes solo, fails in-suite".
2. **The remaining shards of run 31782223549** were still finishing at handoff — 8 of 12
   collected. Artifacts carry `chaos_modules_N.txt` / `chaos_result_N.json` per shard,
   for 14 days.
3. **#328 mechanism 2** (isolation diff: run each module alone *and* in-suite; the two
   directions are different bugs) is the last unbuilt mechanism.
4. **#308's remaining borrow sites** — 35 `get_all`/`get_list("Company", limit=1)` in the
   test tree.
5. **`check_new_test_failures.py`'s docstring still cites a "~2,336 failing" baseline.**
   `known_test_failures.txt` now has **zero** live entries, and
   `known_test_failures_v16.txt` (2359 lines) is wired nowhere.

## Needs a human decision

The live working tree has three uncommitted files nobody in this session touched:
`verenigingen/public/css/email_brand.css`,
`verenigingen/verenigingen/doctype/membership_termination_request/membership_termination_request.json`,
and `verenigingen/verenigingen/module_onboarding/verenigingen/verenigingen.json` — Frappe
writing metadata back to disk from Desk edits. They blocked `git pull` on the live tree,
and since that tree *is* the deployment, a future `git checkout` there would silently
overwrite them. They should be committed or reverted deliberately.

## Raw evidence

`/home/frappeuser/test-leak-census/` (outside `/tmp`, 1.6 MB gzipped) holds the 12 CI
shard logs the baseline was seeded from, the partial warm-site census, and
`tooling/seed_baseline.sh <run_id>` to re-seed. Its `README.md` carries the provenance
table and the two traps that will otherwise mislead a replay. GitHub expires the run's
own logs after ~90 days.
