# Handoff: `in_import` harness removal — CI fallout triage

Date: 2026-07-31
Status: **change is implemented and pushed, NOT mergeable — 169 CI test failures need triage**
Branch: `test/harness-production-fidelity` (no PR open yet)
Design doc: `docs/superpowers/specs/2026-07-30-in-import-harness-phase1-design.md` (revision 2)

---

## 1. Current state

### Landed / in review

| | Branch | PR | State |
|---|---|---|---|
| Security-wrapper retirement | `refactor/retire-security-wrappers` | **#193** | Open, independent, 65 tests green. Not blocked by anything below. |
| Harness `in_import` removal | `test/harness-production-fidelity` | none | 2 commits on `develop`. **Blocked: 169 CI failures.** |

`test/coverage-sweep-agent-suites` is a **dead branch** — its PR #192 already merged. It holds
the same commits plus history noise. Do not open a PR from it.

### What the harness branch contains

- `97503208` — `test(harness): stop EnhancedTestCase suppressing production document behavior`
- `7aac10c8` — `fix(tests): honor explicit posting_date on factory invoices`

The change itself, in `EnhancedTestCase.setUp` (`enhanced_test_factory.py`):

```python
# was: frappe.flags.in_import = True
self._original_throttle_limit = frappe.local.conf.get("throttle_user_limit")
self.addCleanup(self._restore_throttle_user_limit)
frappe.local.conf["throttle_user_limit"] = 1000000
```

`in_import` was set for exactly one reason — to make `throttle_user_creation()` return early.
It also disabled `_set_defaults()`, `_validate_selects()`, `_validate_constants()`, autoname
regeneration, and subscriber dispatch. Full list in the design doc.

---

## 2. The blocking problem

CI run **30579228391** (`gh run view 30579228391`), 12 shards, manually dispatched:
**11 of 12 shards failed, 169 failing tests.**

**Almost none of these are harness bugs.** They are the harness no longer accepting data that
production rejects. Each needs a judgment call: *is the test wrong, or is production writing
an invalid value?* The second kind are real bugs and the reason this change is worth
finishing.

### Failure taxonomy

| Root cause | ~count | Diagnosis | Status |
|---|---|---|---|
| `ValidationError: Due Date cannot be before Posting Date` | 9 | ERPNext overwrote `posting_date` | **FIXED** in `7aac10c8` |
| `<Field> cannot be "<value>"` — Event Type, Contribution Mode, Severity, Status, Proficiency Level, Permissions Level | ~50+ | `_validate_selects()` restored; tests/production writing invalid Select values | **TODO — the main work** |
| `Invalid coverage period: start date <today> must be before end date` | ~26 | date fields landing on today instead of the intended date | **TODO — likely same class as the fixed one** |
| `Please select a country code for field phone` | few | validation now running | TODO |
| `Insufficient permissions`, `Failed to add/remove board member`, `Could not find For User` | ~15 | unclear; needs triage | TODO |

### Root cause #1 (fixed) — worth understanding before triaging the rest

`erpnext/utilities/transaction_base.py`:

```python
def validate_posting_time(self):
    if (frappe.flags.in_import or self.flags.from_restore) and self.posting_date:
        self.set_posting_time = 1

    if not getattr(self, "set_posting_time", None):
        now = now_datetime()
        self.posting_date = now.strftime("%Y-%m-%d")   # overwrites explicit posting_date
```

Under `in_import` an explicit `posting_date` was honored. Without it, ERPNext **silently
replaces it with now()**. Fixed by adding `"set_posting_time": 1` to the two factory builders
(`create_test_sales_invoice`, the Payment Entry builder) — already the established pattern in
`tests/fixtures/sepa_test_factory.py` and `tests/scalability/payment_history_test_factory.py`.

**This is the template for the remaining triage**: the failure surfaced only because the CI
run crossed midnight. On any run that doesn't, the date is silently wrong and nothing
complains. Expect more silent-corruption cases of this shape, and assert the *value* directly
rather than relying on a downstream validation to notice.

---

## 3. Next steps, in order

1. **Land #193 first.** It is independent and green. Nothing below blocks it.
2. **Triage the Select-validation failures** (~50+, the bulk). For each: read the DocType JSON
   `options` list, then decide — invalid value written by the *test* (fix the test) or by
   *production code* (real bug, likely worth its own commit and possibly its own PR).
   Start with `Contribution Mode` (~27 across shards) and `Event Type` (~16); they dominate.
3. **Triage `Invalid coverage period`** (~26). Check whether a date field is now receiving a
   `Today` default it previously never got, the same shape as root cause #1.
4. **Triage the permission/board-member failures** (~15). Least understood; do last.
5. **Re-run the 12 shards** (`gh workflow run server-tests.yml --ref <branch>`, or just open
   the PR — a PR targeting `develop` triggers them automatically).
6. **Open the harness PR** once shards are green.

---

## 4. Traps that cost time in this session — read before starting

### Local runs cannot verify this change

A full local run showed **0 failures across 11,293 tests** while CI found 169. Two reasons:

- `sites/test_site_1..4/site_config.json` already set `throttle_user_limit: 100000`, so the
  throttle path can never fail locally. CI's `.github/helper/db/mariadb.json` sets nothing →
  default 60. **CI is the only environment where the throttle substitute is load-bearing.**
- `test_site_1` is long-lived and carries committed state that masks the data-validity
  failures.

Use the 12-shard CI run as the source of truth. A green local run means nothing here.

### The local full-suite run dies reproducibly

`bench --site test_site_1 run-tests --app verenigingen` (single serial process) dies without a
summary at `verenigingen.tests.e_boekhouden.test_rest_migration_helpers.TestReportingHelpers`,
reproducibly, on two separate runs, at ~11.3k–11.7k tests. That module passes standalone (42
tests, OK, exit 0). Cause not determined — accumulation/OOM was hypothesised but no OOM
evidence was found in `journalctl -k` or `kern.log`. **Not worth chasing**; CI shards each run
a fresh process and don't hit it.

### `pgrep -f` / `pkill -f` match their own shell

In this harness the Bash tool wraps commands in `bash -c '...'` whose argv contains the
pattern verbatim. So:

- `pkill -f "<pattern>"` SIGTERMs its own shell → **exit code 144**.
- `until ! pgrep -f "<pattern>"` as a completion watcher **never exits** — it always finds
  itself. Silence is indistinguishable from "still running".

Use `ps -eo pid,etime,cmd | grep "[b]ench_helper"` (bracket trick) and
`while kill -0 "$PID"` on a PID captured at launch. Launch with
`setsid nohup ... < /dev/null &`.

### Worktrees break two pre-push hooks

If you use a git worktree outside the bench directory:

- `make-test-quick` runs `bench --site ...` → `WARN: Command not being executed in bench
  directory`, exit 2. Skip with `SKIP=make-test-quick` **only** if the identical tree already
  passed it from the main tree.
- Performance benchmarking needs `jest`, but `node_modules` is gitignored and absent in a
  worktree. Symlink it: `ln -s /home/frappeuser/frappe-bench/apps/verenigingen/node_modules <worktree>/node_modules`.

Both look like real failures if you only read the last line of `git push` output. Also
`SKIP=whitelist-type-safety` as usual (pre-existing failures).

### `in_bulk_import` is NOT a substitute for `in_import`

Tried and reverted. The event **emitters** (`events/team_events.py:36`,
`member_events.py:34`, `chapter_events.py:37`) gate on `bulk_*_operations or in_bulk_import`
and never check `in_import`, so under `in_import` they emit normally. Setting `in_bulk_import`
short-circuits them *before* `event_emitter.emit_event()` — it suppresses strictly more. It
broke 3 tests in `tests/events/test_team_events_coverage.py`
(`AssertionError: None != 'bulk_team_operations'`).

Only the **subscriber** side (`events/subscribers/subscriber_utils.py:45`,
`chapter_subscribers.py:132`) consults `in_import`. **Consequence: there is no clean
Phase 1 / Phase 2 split.** No existing flag suppresses dispatch without also killing
emission, so event dispatch now runs in tests. Holding that boundary would require adding a
new test-only flag to production code — judged not worth it, since the four modules directly
exercising the subscriber path all pass with dispatch restored (29, 8, 38, 28 tests).

### `test-quality-enforcer` blocks permission bypasses in test bodies

`frappe.set_user("Administrator")` inside a test method fails the hook (setup / teardown /
factory methods only). `EnhancedTestCase.setUp` already grants System Manager, which can
create Users — no bypass needed. The hook only fires on the **staged set** at commit time.

### Reading CI logs

`gh run view --log` returns empty. Use
`gh api "repos/nlvegan/verenigingen/actions/jobs/<job_id>/logs"`. Failure lines carry ANSI
escapes between the status and the test name, so match `(ERROR|FAIL).*test_` — not
`(ERROR|FAIL) +test_`, which silently returns 0 and looks like "no failures".

---

## 5. What is already verified

Green on `test_site_2` with the harness change applied:

- `test_harness_production_fidelity` — 5/5 (the new pinning tests)
- `test_team_events_coverage` — 28/28
- Subscriber path: `test_member_events_coverage` 29, `test_subscriber_utils_coverage` 8,
  `test_chapter_subscribers` 38
- `test_rest_migration_helpers` — 42 standalone

The five fidelity tests were each confirmed RED before the fix — defaults absent,
`ValidationError not raised`, `user.enabled` was `None`, throttle `100000 not >= 1000000`,
and `'2026-07-31' != '2026-07-21'` for posting_date. Two were additionally proven to bite by
temporarily reverting the fix. Keep that standard for anything added during triage: on
`test_site_1` a great many assertions pass for the wrong reason.
