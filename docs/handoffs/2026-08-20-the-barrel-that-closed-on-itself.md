# Handoff — 2026-08-20: the barrel that closed on itself

Session started as a one-line question — "any idea why i got this error?" — attached to a
production `_frozen_importlib._DeadlockError` from a Member form load. It was not a flake and
not a Frappe bug. It was our own package layout meeting a CPython 3.13 importlib change, and
the same shape is still live in a package with far wider exposure than the one that fired.

## Landed

| PR | | merge |
|---|---|---|
| #397 | the billing barrel emptied; concurrent-import deadlock closed | `4baf27c2` |

| issue | |
|---|---|
| #396 | the other barrel packages + a shrink-only ratchet; `utils/security` is item 1 |
| #398 | `test_invoice_management` asserts its fixture is inside a nondeterministically capped sweep |

**Not deployed.** The live tree at `apps/verenigingen` is still on `4cc0c502`. See
*Needs a human decision*.

## What the bug actually was

`verenigingen/services/billing/__init__.py` re-exported 13 submodules, so **any** import below
`verenigingen.services.billing` ran all 13 first, holding the package lock for tens of ms.

CPython acquires the lock for the **full dotted name** first, and only then does
`_find_and_load_unlocked` re-enter the import of a parent whose spec is still `_initializing`.
So the submodule lock is taken *before* the package lock, and two request threads can close a
cycle:

| | thread A (the traceback) | thread B |
|---|---|---|
| holds | `services.billing` (running `__init__.py`) | `...billing.template_configuration_service` |
| wants | `template_configuration_service` (`__init__.py:76`) | `services.billing` (parent `_initializing`) |

Thread B is any of the eight production modules importing `template_configuration_service` at
module level. Thread A was the `permission_query_conditions` hook on Membership Dues Schedule
importing the controller.

Fix: empty the `__init__`, repoint the one production caller of a re-exported name
(`membership_dues_schedule.py:8`) at the defining submodule, and guard the shape with a test.

## Findings worth keeping

**This is 3.13+ behaviour, and that makes it dateable.** Python 3.12's
`_find_and_load_unlocked` re-imports a parent only when it is *absent* from `sys.modules`; 3.14
also re-imports it when `_initializing` is set. Read both interpreters on this bench to confirm.
Every barrel in the app became newly dangerous the moment we moved to 3.14 — none of this could
fire before. Pinning back Python is a real (unattractive) mitigation.

**Each occurrence emits two different 500s and only one is greppable.** The detecting thread
raises `_DeadlockError`; the other gets a bare `KeyError: 'verenigingen.services.billing'` from
`parent_module = sys.modules[parent]`, after the failed import removed the half-initialised
package. Anyone sizing incidence by grepping logs for `_DeadlockError` undercounts by ~half.
This showed up in my own repro output before I understood it.

**A barrel scan must match relative imports.** Mine matched only
`^from verenigingen.<pkg>.`, so every `from .submodule import X` barrel was invisible — which
hid the highest-exposure package in the app. `verenigingen/utils/security/__init__.py:28`
re-exports 13 submodules relatively; `api_security_framework` is imported at module level by
**394 files**; it deadlocks at 0–1 ms with the same two-thread harness. That is #396 item 1,
ahead of `services/chapter`.

**`find_orphaned_schedules` is `LIMIT` with no `ORDER BY`**
(`membership_dues_schedule.py:527-545`). The site-wide cleanup endpoints are therefore not
merely capped at 20/50 — they are *nondeterministically* capped, and three tests assert their
own fixture landed inside that set. `test_site_1` carries 10 orphans against a budget of 20.
Note two of those tests run `dry_run=False`, so the obvious "raise `max_cleanup`" fix used
elsewhere in the file would enlarge a **destructive site-wide** operation. #398.

**CI's `apt-get update` has no retry, no timeout, and can burn a 60-minute runner slot.**
On run `32293882131` attempt 1, **7 of 12 shards** died identically: the Azure apt mirror
returned `Ign:` for every line, apt fell back to `https://archive.ubuntu.com`, and hung on
`noble-security InRelease` until `timeout-minutes: 60` killed the job inside *Setup
Environment* — `Run Tests` skipped, so nothing of ours ever executed. The green shards fetched
from `azure.archive.ubuntu.com` in **1 second**. Attempt 2 was clean, 12/12. Not filed as an
issue yet; offered.

## What went wrong in how I worked

**I published a measurement table built with an instrument I had not tested.** The barrel scan
in #396 missed every relative-import package, including the worst one. The skeptical reviewer
found it. A scan is code; it needs a control like anything else — one known-positive it must
find. *(This is the "a finding is a class, not an instance" rule, failed at the search step
rather than the fix step.)*

**I ran a control on state the experiment had already destroyed.** `test_invoice_management`
failed in a branch sweep, so I ran develop alone and got green and nearly called it. But the
branch run's own `dry_run=False` cleanup had *deleted the site-wide orphans as it failed* — the
develop run started from a much cleaner site. Only replaying the identical 16-module prefix on
each side made the comparison mean anything. Same trap as the shard-11 bisect: **the victim
cleans up as it fails, so re-running proves nothing unless you re-dirty first.**

**A 25-module test sweep "passed" while executing nothing.** I used `./env/bin/bench`, which
does not exist here (`bench` is at `~/.local/bin/bench`). Every module reported an empty
summary, and my grep for `^OK|^FAILED` matched nothing — so the results file was 25 blank
lines. I caught it only because I opened one log. **An empty result is not a passing result;
make the summariser print `NO-SUMMARY` rather than nothing.** I did, after.

**I asserted a process fact I had not checked, twice.** Said the background rerun task "expired
without firing" — it was still polling and fired later, harmlessly. And I flagged that CI could
not reproduce this because it builds on 3.10–3.12; `server-tests` actually runs **3.14**. Both
were one command away.

**A `git checkout --` inside a control silently reverted an unrelated edit.** Restoring
`__init__.py` after a mutation test also discarded the docstring rewrite I had made minutes
earlier. Caught it on the next `git diff --stat`. Snapshot before mutating, restore from the
snapshot, and diff after.

## Next

- **#396 item 1 is `utils/security`, not `chapter`.** Same fix shape; the acceptance test is
  the two-thread harness reddening before and going green after.
- The repo-wide ratchet in #396 is the part that compounds — it stops the next barrel being
  born while the backlog burns down. `verenigingen/hooks/__init__.py` belongs on its permanent
  allow-list: Frappe reads `doc_events`/`scheduler_events` as attributes off that module.
- #398: prefer scoping the tests to their own fixture over widening a destructive sweep.

## Needs a human decision

- **Deploying.** The live tree is still `4cc0c502`; `git pull` there *is* a live deploy. The
  fix is import-time, so it does nothing until workers restart.
- **Which host actually failed.** The traceback came from `frappe 16.30 / python 3.14` at
  `/usr/local/lib/python3.14` — not this bench. If that deployment does not track `develop`,
  the merge has not reached the thing that broke.
- **Whether to file the apt-retry CI issue.** Evidence is ready (7 job IDs, the 1-second vs
  60-minute contrast).

## Raw evidence

```bash
# the repro (both ends of the sweep must be ok, or the harness is what you measured)
PYTHONPATH=<tree> ./env/bin/python repro2.py <delay-seconds>
#   develop: ok at 0ms, DEADLOCK at 2/4/8/16/32ms, ok at 64ms
#   fixed:   ok at all nine delays

# same harness against the next target, on develop
PYTHONPATH=apps/verenigingen ./env/bin/python repro3.py \
    verenigingen.utils.security api_security_framework 0.001
#   DEAD _ModuleLock('verenigingen.utils.security.api_security_framework')

# the interpreter difference, read rather than assumed
sed -n '/^def _find_and_load_unlocked/,/^    spec = _find_spec/p' \
    $(python3 -c "import sysconfig;print(sysconfig.get_paths()['stdlib'])")/importlib/_bootstrap.py

# barrel census - BOTH import forms
for f in $(find verenigingen -name __init__.py); do pkg=$(dirname $f | tr / .); \
  echo "$(( $(grep -cE "^from $pkg\.|^import $pkg\." $f) + $(grep -cE '^from \.[a-zA-Z_]' $f) )) $f"; \
done | sort -rn | head
```

Run `32293882131`: attempt 1 = 5/12 shards ran (all green), 7 cancelled on the apt stall;
attempt 2 = 12/12 green, verified at the `Run Tests` **step** level, not the job level —
7 of them had "passed" attempt 1 only by never executing.
