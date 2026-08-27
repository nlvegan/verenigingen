# 2026-08-25 — the count that was wrong three times

Picked up the loose thread #564 left open: `_StderrHandler`'s docstring asserted **"nine
class-teardown call sites log through this logger"** and **"ERROR is the level all nine of
those teardown sites use"**, a review's count that had been propagated into merged code
without its own check. #564 §9 offered two exits — run the call-graph walk and keep the
number, or reword to the property.

I ran the walk. The number was wrong. Then my replacement was wrong. Then my *description*
of how I measured it was wrong. Three corrections to one paragraph, and the same sentence
explains all three:

> **A figure stated without the rule that produced it cannot be checked, and will be wrong
> in a way nobody notices.**

Merged as **#571** (`91ef497c7c`), 43/43 green. The docstring now carries the edge rule
beside the number.

---

## 1. The three wrong counts, and what produced each

| # | claim | wrong because | found by |
|---|---|---|---|
| 1 | "nine sites, all ERROR" | never measured; it counted *teardowns calling `restore()`*, not logging sites | me, this session |
| 2 | "ten sites, five calls, one ERROR" | my filter excluded a real edge class | skeptical review |
| 3 | "edges were resolved by name" | describes a simpler instrument than the one that produced the number | skeptical review, round 2 |

**Final, verified:** **eleven** `tearDownClass` bodies reach the harness logger, through
three routes, hitting **nineteen** logging calls at three levels — **16 WARNING + 1 DEBUG +
2 ERROR**.

| route | teardowns | logging calls |
|---|---|---|
| `SingletonBackup.restore()` → `_restore_singleton` | 9 | `:207` W, `:269` W, `:279` D, `:292` **E** |
| `TestWebhookUserSetup._sweep_webhook_users` | 1 | `test_webhook_user_setup.py:143` W |
| `cls._test_instance.tearDown()` → `EnhancedTestCase.tearDown` | 1 | 13 W + `error_log_guard.py:194` **E** |

The original "nine" was real but mislabelled — nine teardowns *call* `restore()`, and
`restore()` is their shared callee rather than "among them". The level claim was simply
false, and **the docstring already contradicted it six lines below**: *"The residual limit: a
`.warning()` or `.info()` from class teardown is still lost."* That paragraph was right all
along, and 17 of the 19 calls are exactly what it describes.

Claim 4 — that the `>= ERROR` mirror gate rests on the level of the specific records that
must not be lost, rather than on a property all sites share — survived every round and came
out stronger: 2-of-19 instead of 1-of-5.

---

## 2. The instrument failures, in order, because each is reusable

**A body-scan returns 0 when the logging is indirect.** #564 already had this: scanning
`tearDownClass` bodies for logging calls finds nothing, because teardown calls `restore()`
and `restore()` logs. Zero from the wrong instrument reads as "no sites".

**An over-approximation that comes back BELOW the claim is a real refutation.** I built the
walk name-based on purpose — every def of that name — so the untightened answer (34 calls, 6
ERROR) refuted "nine, all ERROR" before a single site was hand-checked, because 6 < 9. A
small *exact-looking* answer from a blind instrument would have settled nothing.

**But the filter you tighten it with is where the next error lives.** This is the part I got
wrong and would not have found alone. I then excluded lifecycle methods (`setUp`/`tearDown`/…)
as call TARGETS, reasoning that unittest invokes them rather than helpers calling them. True
everywhere in this repo **except one place**:

```
test_chapter_permission_service_integration.py:182
    tearDownClass  ->  cls._test_instance.tearDown()
```

`_test_instance = cls()` is stashed in `setUpClass` (`:64`); the class defines no `tearDown`,
so it binds to `EnhancedTestCase.tearDown` (`enhanced_test_factory.py:2507`) and drags the
whole drain onto a class-teardown path — including a **second ERROR** at
`error_log_guard.py:194`, in that set for the same #433 reason as `singleton_backup.py:292`.

**The untightened walk had it all along.** My filter threw it away. So: *an
over-approximation bounds a claim from above; it does not license the filter you use to
shrink it.* Justify every exclusion as a class before applying it — grepping non-`super()`
lifecycle calls inside class-teardown bodies repo-wide returns **exactly one** occurrence, so
the rule was right about the shape and wrong to be absolute.

**Then: describing a simpler instrument than the one you ran.** Round 2 caught that the
docstring said "edges were resolved by name", but 19 came from a receiver/MRO-resolved walk.
Measured both ways on this tree:

| rule | calls | levels |
|---|---|---|
| name-only, as the paragraph described | 34 | 26 W, 1 D, 1 I, **6 E** |
| receiver resolved through the MRO | 19 | 16 W, 1 D, **2 E** |

`tearDown` has **498 defs** in this repo (`cleanup` 7, `restore` 4), so resolving
`cls._test_instance.tearDown()` by name links to all 498. Receiver resolution is also the
only thing keeping the phantom `factories.py:260` out of the set. Both numbers are now in the
docstring so a reader can tell which walk the count depends on.

**The control that made any of it trustworthy:** assert the instrument finds
`singleton_backup.py:292` — the site the prose names by hand — before believing any total it
reports. My first script silently missed the entire file the docstring names, because it
handled `logger = get_harness_logger(...)` but not inline
`get_harness_logger(...).error(...)`. The control caught that in one run.

---

## 3. Two things I called broken that were working correctly

**The armed gate.** Shard 5 went red on `test_get_data_real_sql_execution`, and the gate said
`matched baseline (allowed): 0 / NEW: 1`. The baseline file it reads,
`known_test_failures.txt`, has **zero** non-comment entries. I concluded the gate was
misconfigured and was about to file that as an issue.

It is **intentionally** empty. Its own header says so in caps — *"THIS BASELINE IS
INTENTIONALLY EMPTY (2026-07-26) … the gate is therefore fully armed: ANY failing test now
fails the gate"* — after being taken 32 → 0 by *fixing* rather than baselining (`4269c917d`).

> **RULE: an empty config file is not evidence of a broken gate. Read its header.** "Zero
> entries" is equally consistent with "never populated" and "deliberately emptied because
> everything was fixed", and only the header discriminates. I reached for the first reading
> because it explained my red shard conveniently.

What *is* broken is **`known_test_failures_v16.txt`** — 2349 lines, read by **nothing**
(zero hits outside `docs/handoffs/`), whose first line calls it a *"no-new-failures gate
baseline"* and whose header still claims `known_test_failures.txt` is "v15-generated", false
since 2026-07-26. It is consulted precisely when someone is deciding whether a red test is
pre-existing — the one question it answers wrongly. Three for three now: the 2026-08-14
handoff, **#357 filed on a wrong premise** (2026-08-16b), and me today. Filed as **#573**.

**The "order-dependent" failure.** I twice called the shard-5 failure a co-tenancy-order
problem surfaced by the re-pack. It is not. Same commit-to-commit comparison:

| | `6715038d` | `b74fadd4` |
|---|---|---|
| shard | 5 | 5 |
| modules | 86 | 86, **zero difference** |
| class order | — | **identical, all 241** |
| `test_get_data_real_sql_execution` | ✖ | ✔ |

Identical co-tenancy, identical order, fresh per-shard DB, opposite outcome → **the failure
is non-deterministic**. Ordering is excluded, not implicated.

> The re-pack story is *always available* — editing a test file does re-pack every bin — and
> it always fits. That is exactly why it needs discriminating evidence rather than a
> mechanism that merely fits.

The corollary worth adding to the "reading a red CI shard" playbook: the existing note says a
re-run reproduces co-tenancy and order, so a deterministic order-dependent failure repeats
identically. **The converse is the useful half — if you obtain the same co-tenancy and order
and it does NOT repeat, you have a flake.** "Same shard number" is not that claim; shards
re-pack while numbers stay put. Diff the module set *and* the order:

```
gh api repos/<r>/actions/jobs/<id>/logs | sed 's/\x1b\[[0-9;]*m//g' \
  | grep -oE "verenigingen\.tests\.[a-zA-Z0-9_.]+\.[A-Z][a-zA-Z0-9_]*" | awk '!seen[$0]++'
```

The flake itself: `CannotChangeConstantError` from `validate_set_only_once` on a `Payment
Schedule` child row, during `SalesInvoice.submit()` inside the test's own
`create_test_sales_invoice`. Passes standalone on branch and develop, 17/17 both ways. **Not
filed** — one fail, one pass, no reproduction; the argument for a ticket is that the gate is
armed, so a flake here randomly reddens unrelated PRs.

---

## 4. Traps hit this session

- **`gh pr view` is broken here** (Projects-classic GraphQL), and so is `gh pr edit`. Use
  `gh api` for everything: `pulls/<n>`, `-X PATCH` for the body, `-X PUT .../merge`.
- **A monitor's own terminal line can lie.** My CI watcher's final tally printed
  `🔴 #571 COMPLETE: of not green` — both counts empty, and with `bad` empty
  `[ "$bad" -eq 0 ]` errors and falls through to the red branch. The red was an artifact of
  my own script. Query the real state before relaying a watcher's verdict; the per-shard
  events were trustworthy, the summary was not.
- **Cancelled shards are not failures.** Pushing a new commit supersedes the run; nine
  "cancelled" events were my own push.
- **The live tree fast-forwards on its own.** It moved to `11565e4b9` (a merge of #569)
  mid-session with nobody here running it. Known, but it still surprises.
- **A skeptical reviewer's line numbers were clean this round; its paths were not.** It
  reported `@backup_singleton` as "zero usages" from a grep that excluded the only file
  containing them (four hits, all docstring examples — conclusion held, count didn't), and
  put the single `tearDownModule` in `e_boekhouden/` when it is `donor/`.

---

## 5. For whoever picks this up

1. **#573** — delete or rename `known_test_failures_v16.txt`. It has now misled three
   separate investigations, one of which produced a wrong issue.
2. **The flake** needs a decision: file it with the fingerprint and both logs, or wait for a
   recurrence. It is armed-gate-visible, so it will randomly redden PRs until fixed.
3. **The AST scripts are not committed** — deliberately, to keep the diff surgical. The
   docstring cites a measurement a reader cannot re-run. If that trade looks wrong now,
   `scripts/validation/` is where they would go; the three of them are the site census
   (both binding shapes), the name-only walk, and the MRO-restricted walk.
4. **`docs/handoffs/2026-08-23*.md` still carry the old "nine"** in two places. Left as
   written — dated records of what was believed then. #564 §3/§9 *were* updated, since that
   is the live document that flagged this.
5. **The residual limit is still real**: 17 of 19 class-teardown records are below ERROR and
   are lost. Fixing it properly means draining `_module_or_class_stderr_capture` in
   `stopTestRun`, which is `frappe/`'s to do.
