# Handoff — 2026-08-28b: the highest-risk site was a docstring

**PR #620** (issue #605) merged as `8576ce9cf`, four rounds, after the first CI run it had
ever had went red on two shards. Three issues filed (#628, #630, #631), one investigation
closed out (#605), two agent branches finished and **not yet pushed** (#622, #628).

Read `2026-08-28-six-checks-are-not-forty-four.md` (PR #629) first for the stacked-PR
class. I hit the identical defect on #620 independently and about an hour later: base was
the already-merged `fix/597-purpose-filtered-mandate-resolution`, six green `build (3.x)`
ticks, zero shards, three review rounds "CI-verified" against pylint. **Two PRs in one day,
same cause, discovered twice.** That is the signal — it is not a one-off, and nothing in
the repo fails when it happens. The mechanics (retarget with `gh api -X PATCH`; a base
change fires `pull_request: edited`, which is not in the default types, so it queues
nothing; a push is what makes the suite run) are all in #629's note and I will not repeat
them.

What follows is only what that note does not cover.

---

## The lead: I called it highest-risk and it was prose

I filed #628 for the naive-`date.today()` class and led the table with:

> `payment_entry_creation_service.py:212,214` — `posting_date=` / `reference_date=` — a
> Payment Entry **posts to the GL on the wrong date**, and can land in the wrong accounting
> period at a month/year boundary.

An agent checked it with an AST walk instead of a grep:

```
real date.today() CALL nodes at lines: NONE
docstrings containing the text date.today(), starting at lines: [130]
```

Lines 212 and 214 are inside an `Examples:` block. **The highest-severity entry in an issue
I filed has no runtime effect at all**, and I repeated the claim in the PR body and to the
user before anyone checked it.

The mistake is not the grep. It is that severity and existence came from the same
observation. I ranked the sites by *consequence-if-real* and never separately asked
*is it real* — so the scariest-sounding line got the least scrutiny, exactly backwards.
`grep` finds text; only the parser knows what is code. For any claim of the form "this call
site does X", the census must be an AST walk, and it costs about six lines:

```python
[n.lineno for n in ast.walk(ast.parse(src))
 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
 and n.func.attr == "today"]
```

Corrected on #628. The real behavioural count is **13**, not the 15 the issue claims — and
the issue's own tables list 14 while its prose says 15, omitting
`invoice_generator.py:286`, which the agent found by re-running the census rather than
trusting the table.

## The clock I measured was not the clock I named

The bug #620 died on: `_lookup_mandate_sign_date` returned Python's `date.today()`
(process tz) as its "no sign date" sentinel while the fixture used `frappe.utils.today()`
(site tz, `Asia/Kolkata`). Real bug, real fix — `getdate()` — and the repo had already
named this class in a comment at `dues_payment_processor.py:350`: *"a real TZ-boundary
bug, not just a test flake."* That comment was the search query; the adapter was its
unfixed sibling.

Then I measured the window and wrote: *"measured on test_site_1 at 2026-08-27 23:30 UTC."*

It was 23:30 **CEST**. This box has no `TZ` set and `tzname == ('CET','CEST')`. I had read
a naive `datetime.now()` as UTC — **the same conflation of process-local and absolute time
that the bug itself is made of**, committed while documenting that bug.

There are two windows, because the two hosts sit at different offsets from the site:

| host | offset | its midnight | divergence window |
|---|---|---|---|
| CI runners | UTC | 24:00 UTC | **18:30 – 24:00 UTC** |
| this bench | UTC+2 | 22:00 UTC | **18:30 – 22:00 UTC** |

The cost was not cosmetic. I briefed an agent at 22:51 UTC with *"you are inside the
window, it closes at 00:00"* — locally it had closed 51 minutes earlier, so every plain run
it made would have been green on unfixed code and it would have concluded the sites were
not instances. Caught it from the review and corrected mid-flight.

**Do not wait for the window. Force it.** `TZ=UTC <cmd>` reproduces CI's condition at any
hour, verified on this box:

```bash
TZ=UTC PYTHONPATH=<worktree> bench --site test_site_1 run-tests --app verenigingen --module <m>
TZ=UTC ./env/bin/python -c "import datetime; print(datetime.date.today())"   # sanity first
```

The agent went further and built the durable version:
`verenigingen/tests/test_site_timezone_today.py` pins the *site* timezone to
`Pacific/Kiritimati` (+14) or `Pacific/Midway` (−11) — 25 hours apart, so one always
differs from the process date — via `frappe.local.system_settings`, and restores it.
Mutation control in both directions with production reverted: 7/15 red with the site ahead,
5/15 behind, 8 distinct tests. That is the right answer to "this class is only detectable
5.5 hours a day".

## What the review corrected, and where it was wrong

The skeptical review returned MERGE WITH CHANGES and reproduced every empirical claim in my
fix commit with its own controls — the 3/16 mirror on the assertion edits, CI's literal
`40.0 != 100.0` from four planted incidents, `setUp`/`tearDown` safety when `setUp` itself
raises. No code change was required. It corrected two things:

1. **My rename rationale was backwards.** I renamed a `_validate` helper "rather than
   growing the baseline". Control: with the rename reverted the validator prints
   `NEWLY DUPLICATED -- name collision only, NOT blocking` and **exits 0**. The step that
   failed was the separate baseline-in-sync check, and the clone-family gate's own comment
   says a name collision is *supposed* to be recorded — "the same dead end, by another
   door." Harmless outcome, inverted reason.
2. The timezone stamp, above.

And it was wrong once: it reported "149 `date.today()` sites" as matching no ref. Measured
per-ref — develop **149**, the PR branch **145**. 149 is develop's figure, which is what
#628 was filed against. It had only checked the branch and its parent.

**A review that is right twice is not right three times.** I verified all three before
acting, and should have done the same to my own numbers a round earlier.

## The security shard: I immunised the victim

Shard 3 failed `test_security_score_calculation` with `40.0 != 100.0` on a branch touching
neither file. `_calculate_security_score(0,0,0,0)` looks pure but subtracts 15 per active
CRITICAL and 10 per HIGH from `get_security_monitor().active_threats` — a process-wide
singleton. 100 − 60 = 40. I cleared and restored it in that class's `setUp`/`tearDown`.

The review found the polluter still standing: `test_api_security_framework.py:491` defines
a **second class of the same name** that takes the same singleton and drives it past
threshold (`for i in range(15)` auth failures), and auto-resolution is gated on
`ThreatLevel.LOW` (`security_monitoring.py:399`), so HIGH/CRITICAL persist for the life of
the process. The repo already had the right tool — `_make_isolated_monitor()` in
`test_security_monitoring_coverage.py:67` — and I used a weaker one. Filed as **#630**.

The general shape: **fixing the test that failed is not the same as fixing the thing that
made it fail.** Shard packing decides which class notices.

## #605: the enumeration holds, and the sweep over-counts

#605 lists 52 purpose-blind mandate resolutions "classified by reading rather than by
execution" and worries its 15-line window missed some. I reproduced the sweep mechanically
and tested that worry three ways:

- Like-for-like across refs, same heuristic: blind **79 → 57**, scoped **29 → 46**. #620
  moves ~22 sites.
- Widened the window 15 → 40 → 80. Four new files, **all artifacts** — a different doctype
  (`ING Checkout Mandate`, `Membership`, `Membership Dues Schedule`), an already-fetched
  `mandate_doc.status`, or docstrings in `permissions.py`.
- Checked the raw-SQL class separately (39 `tabSEPA Mandate` references, which a
  doctype-string sweep could plausibly miss). The batch ones — `dd_batch_api`,
  `sepa_batch_ui`, `sepa_batch_ui_secure` — are already scoped by #604.

**Nothing was missed.** The error runs the other way: the heuristic *over*-counts, because
a purpose applied through a variable (`resolve_purpose_flag(purpose)` then
`filters[purpose_flag] = 1`) has no `used_for_*` literal to match. Measured 6 of 57 on the
branch, 5 of 79 on develop, so truly blind is **≤ 51**. As more code routes through
`resolve_purpose_flag`, any re-run of that sweep will report inflated numbers. Whoever
re-runs it should count indirect filters before believing the total.

What genuinely remains of #605 after #620: **two sites, both dead code** —
`payment_mixin.py:225` and `utils/member_utils.py:643` (zero production callers; deleting
beats scoping). Everything else is in #605's own "correct as they are" classes. This is
static analysis, same evidence class as the issue's own — I did not execute these sites.

## Filed, not fixed

- **#628** — naive `date.today()` vs site-tz `getdate()`. Two corrections posted: the
  docstring finding above, and the two-window table.
- **#630** — the security-monitor polluter.
- **#631** — a mandate signature date the system does not know is sent to the bank as
  `DtOfSgntr`. The documented strict-mode net is declared `"default": "0"` and is `0` on
  veg11, so the fabricated date *is* the default path. #620's own comment describes that
  channel as though it were live; #631 carries the correction.

## Two agent branches, finished and unpushed

Both committed in their own worktrees, verified, nothing pushed:

- **#622** (`5f38cbfbd`) — scheduled payment retries never ran. Premise confirmed with a
  control, not by reading: the no-arg scheduler call returns `None`, and the *same call
  with an argument* raises `DoesNotExistError`, so the `None` is the guard branch and not a
  decorator swallowing. Fix sweeps `status = "Scheduled"` and `next_retry_date <= today`.
  It also relaxed the per-record guard from `!= today` to `> today`, on the argument that
  an *overdue* record selected by the sweep would otherwise be silently dropped — a
  deliberate widening past the issue's literal scope, and correct. 36 tests green, verified
  independently. It swept all **51** scheduler entries: this was the only instance.
  **Deploy note: `sync_jobs` only runs on `bench migrate`**, so the stale job row persists
  until then.
- **#628** (`65472555c`) — 13 real sites fixed, the docstring example corrected, and the
  timezone test module above. Five existing test modules retargeted in the same commit,
  because changing a production date reddens the tests that pinned the old behaviour — the
  trap #620 hit first.

## State

`develop` at `8576ce9cf`. veg11's working tree is a live deploy and was **never** written
to this session — it sits on `c46e4e9d1`, clean, **27 commits behind** `origin/develop`,
and I did not pull it. (MEMORY.md records that this tree has fast-forwarded on its own
before; it did not today, so do not assume either way — check.) Scratch worktrees removed;
the two agent worktrees remain, holding the unpushed commits above.

## For whoever picks this up

1. **Push the two agent branches and open PRs** — and retarget-check them the moment they
   exist. That is now twice in one day.
2. A required check that fails when `base ∉ {develop, main}` would have caught both. #629
   proposes reading `.base.ref` and counting checks; a gate beats a habit.
3. `chaos-shards.yml` runs at 03:17 UTC, which is **inside** the CI divergence window. It
   may already be hitting the date class and being read as flake.
4. The two dead-code sites are all that is left of #605; deleting `member_utils.py:643`
   closes the larger half of it.
