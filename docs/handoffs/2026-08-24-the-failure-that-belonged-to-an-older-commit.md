# 2026-08-24 — the failure that belonged to an older commit

Task was "read the 23b handoff, merge all green PRs." That is a triage session, not a
building one, and almost all of its content is about **how "green" was decided**. Twelve PRs
merged, `develop` `f7633f89` → `a18d48d9`, 37/37 and 12/12 shards on the merged tree, live
tree synced and restarted.

The 23d handoff was titled *my own instruments were broken*. Every defect below is one of
mine, in a session that opened by reading two handoffs that warn about exactly this.

---

## 1. `statusCheckRollup` served a stale FAILURE three times, and a stale red is worse than a stale green

`gh pr list/view --json statusCheckRollup` reported `👯 Duplicate Helper Guard (ratchet)` as
`FAILURE` on **#553**. I wrote that in a report, in a table, as the reason not to merge it.
Opening the job showed **every step of every job `success`** — 43/43 at its real head. The
roster belonged to an older commit.

Then again on **#557**, listed `UNSTABLE`, actually 43/43 green at `b8d218f7`. Someone merged
it 13 seconds before my own merge of #526, which is how I noticed at all — the two racing
merges produced `GraphQL: Merge already in progress`.

The 23f handoff already says *"a green PR check roster can belong to the previous head."* I
had read it that morning. **The direction it does not spell out is the one that costs
something:**

| stale direction | what happens |
|---|---|
| stale **green** | you merge, CI on develop contradicts you within the hour |
| stale **red** | you skip a mergeable PR, write the reason down, and *nothing ever argues back* |

There is no feedback loop on a false negative. #553 was the fix for #544 that the 23f handoff
itself listed under "for whoever picks this up," and I had it one sentence from being left
open for another day.

**The rule:** `statusCheckRollup` is fine for *rendering* state and is not authoritative for
*deciding* it. Decide from the commit:

```bash
SHA=$(gh pr view <n> --json headRefOid --jq .headRefOid)   # never hand-type it
gh api "repos/nlvegan/verenigingen/commits/$SHA/check-runs?per_page=100" \
  --jq '.check_runs[] | select(.status != "completed"
        or (.conclusion | IN("success","skipped","neutral") | not))'
```

Empty output is green, and the `sha` in the path makes the answer provably about the head you
named. Recorded in the memory note that already covers the `conclusion=""` half.

## 2. Three ways a CI watcher lies by staying quiet

All three were in monitors I wrote **this session**, after writing the rule above.

- **I fabricated a commit SHA's tail.** Wrote `5b2dd619b3ff17f5…` for the real
  `5b2dd61920d23e…`. `gh api` returns nothing for a nonexistent commit, so the roster read
  `0`, `0 >= floor` was false, and the monitor would have polled a commit that does not exist
  **silently, forever**. Caught by `git rev-parse`, which is exactly how 23f says it gets
  caught — that handoff logs the identical mistake. Fix: never type a sha, and make an empty
  roster emit `[WARN] … NOT a pass` rather than nothing.
- **A fixed "expected roster size" floor is the wrong termination condition.** I set 37 from a
  past develop run. This one registered 34 and climbed to 37 as workflows queued; the PRs ran
  to 42 and 43. Above the real roster it hangs; below it, it concludes early. Gate on **no
  workflow at that sha still running** (`gh run list --commit <sha>`) plus no pending
  check-run, and the floor is unnecessary.
- **Silence is indistinguishable from health.** When one monitor printed progress for
  `develop` but nothing for two PRs, I checked directly rather than assume — the numbers
  agreed (off by one, a check completing between calls). Worth doing: two of the three
  defects above present as *no output*.

## 3. A reviewer's recommended fix can be unimplementable, and the measurement is what says so

#526's review was right that the lazy-stderr fix removed an accidental guarantee, and offered
two ways out: document the loss, or add a `sys.__stderr__` fallback that "would fix this and
Finding 5 together." Asked which, Foppe said **both**. I had sketched a `_is_dead_capture()`
detector to make that work. It cannot be built:

- `_module_or_class_stderr_capture` exists only inside `frappe/testing/result.py` — no global,
  no `frappe.local` binding, so the undrained buffer cannot be identified by identity.
- The per-test buffer is **not truncated** after `stopTest` reads it, so "still holds our
  text" does not separate drained from undrained either.

So I measured the strategies through the real `TestResult` with `buffer=True` — one class, a
warning in the test, an error in `tearDownClass`:

| emit strategy | in-test record | tearDownClass record |
|---|---|---|
| lazy resolve only (the branch as it stood) | report ×1 | **LOST** |
| mirror everything (the naive fallback) | report ×1 + **real-stderr ×1** | real-stderr ×1 |
| **mirror ≥ ERROR** (shipped) | report ×1 | real-stderr ×1 |

The middle row is the point: the recommended fallback *does* fix the loss and double-prints
every in-test record — undoing the attribution the lazy read exists to gain. An explicitly
installed stream is never mirrored, which is what keeps `captured_stream` — every level test
in that file runs through it — off the real stderr.

**On "nine sites", which is the review's count and not mine.** I verified the one that
matters: `SingletonBackup`'s `"Failed to restore %s: %s"` is `.error()` through
`get_harness_logger` (`singleton_backup.py:288`), and it is reached from `tearDownClass`
(`test_singleton_backup_restoration.py:126`). I could **not** verify the total. My AST scan
for logging calls inside `tearDownClass`/`tearDownModule` bodies returned **0 files** — the
wrong instrument, because the logging is *indirect*: teardown calls `restore()`, and
`restore()` logs. Counting "sites reachable from class teardown" needs a call-graph walk,
which I did not do. Treat the number as unverified; the ERROR gate stands on the one site I
did check plus the mechanism, not on the count.

**Finding 5 was verified before being fixed, and held.** `StreamHandler.emit` does route write
errors to `handleError`, so "a closed stderr raises into the caller" needed checking. It does:
`Handler.handleError` writes its own diagnostic to the **same** closed object and catches only
`OSError`, so the `ValueError` escapes `.error()` itself — into call sites that are all
`except` blocks.

The residual limit is in the docstring rather than mourned in a comment: a `.warning()` from
class teardown is **still lost**, and draining that buffer is `frappe/`'s to fix.

23f's rule was *verify a reviewer's recommended FIX, not just its finding.* This is the same
rule one step on: the fix was verified, found wanting, and the measurement produced a third
option neither of us had proposed.

## 4. "Retry a red PR" is not a re-run

#526 and #437 were red on shards they never touched. `gh run rerun --failed` replays the
recorded merge ref — same base, same shard packing — which is precisely what CLAUDE.md means
by "re-running a shard does not test for flakiness." The meaningful retry is a **new merge
ref**: merge `origin/develop` into the branch and push, so CI tests it against the develop
that now carries the five fixture PRs.

Both went green. **#526's shard 5 passed**, which settles the 23b handoff's "bisect the
co-tenant" item empirically — one of the merged fixture PRs fixed
`test_dutch_business_rules_phase3`, and no bisect was needed. That is a better answer than the
25-module bisect list in `scripts/testing/notes/526-shard5-unique-predecessors.txt`, which can
now be deleted or marked closed.

## 5. Green CI is not the merge criterion

Two PRs were fully green and correctly **not** merged:

| PR | checks | why not |
|---|---|---|
| #378 | 42/42 | its own body: *"a skeptical review returned REQUEST CHANGES with two blocking findings. Do not merge as-is."* |
| #526 | 43/43 | review verdict "merge **with changes**", and the change was unaddressed |

#526 is the instructive one. Its docstring presented "every later harness record goes
somewhere nothing reads" as the bug being *fixed* — so a reader would conclude records are now
always visible, while class-teardown records were in fact being lost. Grepping the branch head
for `teardownClass|stopTestRun|drain|__stderr__|last class` returned **zero hits**. The tests
passed; the file lied. **Read the PR body and the review thread before trusting the check
marks** — `--comments`, every time, which is CLAUDE.md rule 5 and paid for itself twice today.

## 6. The ratchet failed on my own push, exactly where the 23b handoff said it would

`👯 Duplicate Helper Guard` went red on my #526 commit. Step 5 "Ratchet check (whole tree)"
**passed**; step 6 "Baseline is in sync with the tree" **failed**, on one line:
`_restore::4` → `_restore::5`. No `# clone family` annotation, so the growth gate — the part
that exists to stop clone laundering — was never in play. This was the census recording a
**name collision**, which is that job's legitimate half.

Six `_restore` definitions already existed. Rather than grow that and churn the baseline, the
helper now says what it restores (`_restore_logger_and_real_stderr`) and the baseline needs
**no change at all** — verified by running `--update-baseline` locally and confirming
`git diff` on the baseline is empty.

---

## Traps worth remembering

- **A crude grep makes a false finding as easily as a true one.** Verifying the restart, my
  own check reported that #437's invented `"Website"` default was still present. It was the
  explanatory comment #437 *added*; both real defaults were gone. I looked before reporting.
  A string check needs to be discriminating too.
- **Check the new code present AND the old code absent.** Confirming only the new string is
  consistent with a half-applied file. Used both directions on
  `bank_transaction_reconciliation.py` after the restart.
- **`sites/assets/verenigingen` is a symlink into `verenigingen/public`** — same inode,
  verified. So `public/js/*.js` served by direct URL is live on the next fetch with **no
  `bench build`**. #437 changed `membership_application.js`, and for a while the form's
  browser half was live while its server half was not.
- **`clear-cache` is not what reloads Python.** I paired it with `restart` out of habit;
  frappe's cache holds metadata. For a `.py`-only delta the restart alone is the step.
- **The veg11 working tree fast-forwards on its own.** Asked to update it from 17 commits
  behind, it was already current — it had moved between two of my own checks. Nobody ran it.
  Already in memory; walked into it anyway.
- **Two merges can race.** `GraphQL: Merge already in progress` was my #526 landing 13 seconds
  after someone else's #557. `develop` had moved twice more by the time I re-read it. Re-read
  `origin/develop` after every merge, not once at the start.

## Where things stand

`develop` @ **`a18d48d9`** — 37 check-runs (36 success, 1 skipped `fast-validation`, PR-only),
**12/12 shards**, 7/7 workflows. First run to exercise all twelve merges together; five of
them touch the same test-fixture layer and none had been tested against a base containing the
others.

**Merged:** #524, #541, #542, #543, #550, #553, #555, #556, #437, #526 (this session) and
#557, #558 (in parallel).

Live tree at `a18d48d9`, restarted, verified loading current code for both production modules
that had gone stale (`bank_transaction_reconciliation.py`, `application_helpers.py`).

| still open | state |
|---|---|
| **#378** customer failure destroys Member (#254) | green, blocked by its own two review findings |
| **#379** mollie reversals (#370) | `DIRTY`, WIP |

## For whoever picks this up

1. **#378 is the only green thing left**, and it is green in the way that does not count — two
   blocking review findings, both reproduced in its own body. Read those before touching it.
2. **The two upstream frappe bugs from #526's review are still unfiled**: `stopTestRun` not
   draining `_module_or_class_std{out,err}_capture`, and the crosswise pop at
   `result.py:109-110` (`stopTest` pops `_old_stderr` into `sys.stdout` and `_old_stdout` into
   `sys.stderr`, which is why the mislabeling reads as intermittent — it alternates by
   parity). The first is what makes §3's residual limit permanent from this side.
3. **`526-shard5-unique-predecessors.txt` is now spent** — §4 settled it empirically.
4. **#540 first, still.** Unchanged from 23f: veg11's Mollie Settings points at
   `TEST-Payment-Integration-Company`, so anything that path books goes into a test company's
   ledger. #553 and #558 both merged today and both live on the tree now.
5. **Two counts of mine in merged text are not trustworthy, and both are recorded here rather
   than rewritten.**
   - `9810f744`'s commit message says "Seven `_restore` definitions already exist" when six
     did, and the validator counted four (it dedupes within a file and skips closures).
   - Worse, because it is in code and will be read as fact: **I propagated the review's
     unverified "nine class-teardown call sites" into `_StderrHandler`'s docstring**
     (`harness_logger.py:150`) and into `test_harness_logger.py:269`. See §3 — I verified the
     mechanism and one site, never the total. Either verify it with a call-graph walk and
     keep it, or reword both to the property ("class-teardown records are lost, and the
     restore-failure site is one") which is what the gate actually rests on.

   This is the repo's own "the census is always bigger" rule biting from the other side: a
   number that arrives inside a correct finding still needs its own check before it goes into
   a docstring.
