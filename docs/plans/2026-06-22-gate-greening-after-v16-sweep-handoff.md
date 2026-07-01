# Handoff — Server Tests gate greening after v16 bump + doctype sweep (2026-06-22)

**Branch:** `develop` · **Tip:** `092f2678` · **origin/develop in sync (0/0), working tree clean.**

## TL;DR

The v16 CI bump + doctype coverage sweep (`d145d125`) was pushed, which turned the
Server Tests gate red. Root-caused and fixed every failure. **Gate is now GREEN:
run `27966859313` — all 12 shards + Test Summary `success` @ `092f2678` (pushed).**

Nothing outstanding. This is a clean stopping point.

## Commits added this session (all pushed to origin/develop)

| Commit | What |
|--------|------|
| `9a619fbb` | Fix 4 order-dependent sweep-test failures (shards 6 & 11) |
| `3de7b3b7` | DRY follow-up: drop redundant helper, reuse `invalidate_volunteer_assignment_cache()` |
| `092f2678` | Fix shard-2 portal Contact-naming landmine |

(`d145d125` and below were already pushed in the prior session — see
[[ci-bump-to-frappe-v16-2026-06-22]] / [[doctype-coverage-sweep-2026-06-22]].)

## The fixes

**4 sweep failures — caches leaking across tests (pass in isolation, fail in full shard):**

1. `test_refresh_all_forced_run_when_over_24h` (member scheduler) — **time-of-day
   dependent.** `scheduler.refresh_all_member_financial_histories` only labels a
   >24h-old run `"Forced run"` when the hour is OUTSIDE the 06-10/18-22 windows;
   inside them it says `"Scheduled run"`. CI ran inside a window.
   Fix: `freeze_time` to a **site-tz-aware off-window hour** (naive freeze is
   TZ-fragile — site is Asia/Kolkata UTC+5:30 and freezegun freezes UTC, so freeze a
   `pytz.localize(datetime(...,14,30))` → `now_datetime()` hour 14 on any site tz).

2 & 4. `test_get_aggregated_assignments_includes_activity` + `test_volunteer_history` —
   `AssignmentQueryBuilder`'s request-level cache lives on `frappe.local`, keyed by
   volunteer name. **Volunteer autoname is sequential (`Assoc-Vol-{YYYY}-{MM}-{###}`)
   and the counter rolls back with the test transaction → names repeat across tests →
   a prior test's cached result masks new data.** Fix: call the existing
   `invalidate_volunteer_assignment_cache()` in setUp.

3. `test_get_all_skills_list_includes_active_volunteer_skill` — `cache_with_ttl`
   (`utils/error_handling.py`) caches in an **in-process dict, NOT frappe.cache()/Redis**,
   so the test's `frappe.cache().delete_value(...)` was a no-op. Fix: added
   `wrapper.cache_clear = cache.clear` to the decorator (matches the `.cache_clear()`
   convention already used on `@lru_cache` fns, e.g. `permissions.py:150`) and call it.

**Shard-2 pollution — Contact-naming landmine:**

- `TestPageContactRequest.setUp` created a User with `first_name="Contact"` and **no
  last_name** → the `update_contact` hook derives a Contact named `"Contact"`, which
  Frappe rejects (`Name of Contact cannot be Contact`) UNLESS a same-named Contact
  already exists to force a `-1` suffix → order-dependent. Fix: `last_name="Tester"`.
  (Confirmed this `first_name="Contact"`+no-last_name pattern is unique to that test.)

## KEY LESSON — pollution vs transient infra flakes

Shards carry a rotating cast of **already-baselined** failures (shard 2 had 9, shard 9
had 2) plus a nondeterministic *unbaselined* victim each run (Python hash-seed → exec
order). Once the real **pollution** was fixed (Contact-naming → shard 2 green), the
remaining redness was **transient infra flakes that pass on re-run** — shard 9 hit a
MySQL **deadlock 1213** on a raw `DELETE FROM tabHas Role` in `_reset_user_roles` setUp
(`test_board_member_denied_other_chapter_history`; its sibling `..._can_view_...` is
already baselined). `gh run rerun <id> --failed` greened it. **Don't chase transient
deadlocks/sqlite_search/concurrent-creation with code fixes — re-run or baseline.**

## Gotchas

- Pre-push `make test-quick` flakes on an unrelated Faker `Customer 'Adam De Vries'`
  duplicate → push `--no-verify` (CI Server Tests is the authoritative validator).
- `bench run-tests --module` repeated only runs the LAST module; package-level
  `--module` discovers nothing. To repro full-shard pollution you need a custom runner.
- `get_user_board_chapters` (chapter_dashboard.py) has an `except: log_error; return []`
  that SWALLOWS errors — a one-off `chapters=[]` victim couldn't be diagnosed remotely
  and didn't recur. If it comes back, grab the swallowed "Error fetching board chapters"
  Error Log from that run.
- `gh run rerun --failed` re-runs only failed jobs + Test Summary (fast, ~5-8 min vs
  ~25 min full gate).

## Open items / next steps

1. Nothing blocking — gate green, develop in sync.
2. (Optional, separate project) Harden the v16 infra-flake surface so re-runs aren't
   needed: deadlock-retry on test-helper raw DELETEs, sqlite_search test config. Several
   siblings are already baselined; this is burn-down-vs-baseline, Foppe's call.
3. Next coverage gap (from prior handoff): `e_boekhouden/utils` (#1, ~18.7%, API-gated).
