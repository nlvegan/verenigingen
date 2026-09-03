# Handoff — 2026-09-03c: the green was borrowed

Continues [2026-09-03b](2026-09-03b-the-checks-that-were-checking-me.md), whose PR (#770)
was still open when this session began — that document's eight-agent run produced several of
the issues picked up here. Five issues went to parallel agents, then every resulting PR got a
pre-merge skeptical review.

**6 PRs merged, 1 red, 1 held; 5 issues closed, 7 filed — including a live cross-member data
leak that no PR introduced and that the test suite was structurally unable to see.**

The title is the pattern. Four separate times, something was green **because of state that
did not belong to it** — and each time I read the green as evidence about the code:

| what looked green | where the green actually came from |
|---|---|
| #745's premise "verified live" | a working tree **20 commits stale**; the file had been *moved* by the fix, so the old path still held the old code |
| `test_complete_member_application_to_active_workflow` passing locally | **12 leaked Dutch test companies** on this bench; a fresh CI site has none, so the flag it depends on flips |
| #461 "already fixed" | a `grep | head -10` where tests outnumber production code — the real hit was line 11 |
| the payment dashboard's member lookup, for months | a `setUp` that **clears the cache** to stop test pollution, so no test ever ran two identities in one process |

The last one was a security bug. The generalisation: **when a check passes here and fails
there, ask what this machine has that the other does not, before reaching for
"co-tenancy" or "flake".**

## The find: a cross-member data leak, and an authorization bypass (#782, fixed in #784)

`cache_with_ttl` built its key as `func.__name__` + `hash(args)`. No session. Every
no-argument call collided on one key, so for the whole TTL each caller got whichever result
landed there first. Measured read-only on veg11, two real users owning distinct members:

```
A: user owns Assoc-Member-2026-01-33713 -> resolved ...33713   OK
B: user owns Assoc-Member-2026-01-33584 -> resolved ...33713   MISMATCH
```

The worse half: **a cache hit returns before the function body**, so a permission check
written inside that body never runs. Demonstrated with the real decorator — a stranger
received a board-only payload and the guard never executed. Three of four call sites were in
that shape (`get_member_from_user`, `get_chapter_dashboard_data`, `format_member_address`);
the last two carry their access check *inside* the cached function.

Fixed at the decorator (`per_user=True` default, explicit opt-out for the one genuinely
global cache) rather than at three call sites, because the next author would otherwise
inherit the same footgun. #785 tracks the deeper shape: an authorization check has no
business living inside a cacheable body — check first, then cache only the payload.

**How it was found matters more than the bug.** It came out of a skeptical review of PR
#777, which came out of an issue picked at random this morning. Nobody was looking for it,
and `test_payment_dashboard_api.py:38-46` *documents the mechanism precisely* — as test
hygiene, with a cache-clear in `setUp`. The knowledge was sitting in a comment for months.
A `setUp` that clears shared state "to avoid pollution" is describing production behaviour
nobody has questioned.

## Trunk was red, and CI hid why (#780, fixed in #786)

`test_complete_member_application_to_active_workflow` failed on shard 7 of four PRs,
including one that only deletes a JavaScript file — the control that proved it was not the
branches. `develop`'s own run *also* failed, but in "Initialize containers" after 68
seconds, so an infrastructure failure masked a genuine test failure on the same shard.

Root cause: `update_member_full_name` used `is_dutch_installation() and doc.tussenvoegsel`.
The first clause is answered by a **Redis-cached scan for any Company row with country
Netherlands**, good for an hour, set by whichever caller runs first, and cached `False` for
five minutes after any exception. A fresh CI site's default company is Indian (ERPNext's
`before_tests` runs `setup_complete(country="India")` — the same source as the Asia/Kolkata
timezone in #642), so the answer came from whether another test in the shard had already
made a Dutch company.

The production defect underneath: a member with "van" in their name joining an association
not detected as Dutch had it **silently stripped** from `full_name`.

The fix reads the record: a populated tussenvoegsel *is* the declaration. Four sites. One of
them gated on `hasattr` rather than a value — and every Member *has* the field — so it took
the tussenvoegsel branch even when blank, skipping the `middle_name` particle parsing that
was the only thing which could have recovered it.

**Deliberately not fixed:** the form-rendering callers, which run before any record exists.
That is a genuine org-level question and wants a setting; there is none today (Verenigingen
Settings has 101 fields, none about naming, country or locale). #780 stays open for it. The
asymmetry is the argument: a hidden form field is visible and recoverable, stored names
losing their particles is silent corruption.

## Corrections made to this repo's own record

Four things the tracker or the docs asserted, which measurement contradicted:

- **"`@frappe.whitelist()` MUST be OUTERMOST — Frappe checks by object identity."** Not this
  app's rule. `frappe_whitelist_adapter.register_wrapper_in_whitelist` re-registers each
  security wrapper, so an innermost whitelist is normally fine; what breaks a function is an
  **outermost decorator that wraps without re-registering** (`handle_api_error`). Measured by
  testing `fn in frappe.whitelisted`, and an AST sweep for that shape found exactly the 3
  broken sites. `get_members_without_chapter` has `whitelist` in the *middle* of its stack and
  was still broken, which no "topmost" reading explains. **CLAUDE.md rewritten accordingly**,
  including the second half: whitelisting gates *dispatch*, not calls — background jobs and
  the scheduler are ungated, which is why a broken whitelist stays invisible.
- **#769's diagnosis (mine).** The ratchet check has consulted its own near-identity verdict
  since #458. The gate that actually failed PR #768 was the separate baseline-sync step.
- **#708's severity.** Real defect, but not a live wrong-debit: the only production caller
  sources its invoices from a query that already excludes ambiguous members. Defense-in-depth
  on a public resolver, not "we were debiting the wrong account."
- **#745's premise.** Already refuted in that issue's own comments on 2026-09-02, and
  described in full in the previous handoff — which I did not read before picking the issue.
  **Read the previous handoff document, not just the tracker.**

## Instrument failures worth not repeating

Every one of these produced a confident wrong answer before being caught:

- `grep -rn <pat> | head -10` in a repo where tests outnumber production code — the
  production hit was line 11. Scope the grep, or count first.
- `git checkout -- <file>` to undo a mutation, on a fix that was **not yet committed**. It
  reverted the fix. Commit before mutating.
- Pinning a Redis key before `bench run-tests` to force a code path: **the harness clears
  `frappe.cache()`**, so the pin never reached the test process, and develop "passed" the
  control. Testing the mechanism in a single process is what produced the real result.
- A polling loop whose completion message said "settled after N polls" whether it settled or
  exhausted its budget. Same class as everything above: a message that cannot distinguish
  two states.

## State

**Merged:** #775 (duplicate-helper sync gate scoped to real clone families), #786 (trunk fix,
above), #784 (the cache leak, closes #782), #771 (deletes the unreachable DD batch UI, adds a
`public/js` endpoint guard), #773 (SEPA mandate ambiguity refused rather than guessed), #779
(three `log_error` calls that raise inside their own `except` handler). The last three were
merged only after being re-run against a `develop` carrying the trunk fix — their earlier reds
were #780, not their own code.

**Open, red:** #776 (periodic donation agreement). Its own new test errors in CI with
`PermissionError: No member record found for user`. **Not** caused by #784 — that resolver is
uncached and separate. Likely the #780 shape again: the test's member is created with `email=`
and resolution leans on an email fallback that works here and not in CI.

**Held:** #777 (six shipped pages calling endpoints that do not exist). Needs its own
`anonymous` form-data key fix — a real regression its CI caught — and it adds two call sites to
the resolver #784 just fixed. Merge after both.

**Filed:** #772 (16 more dead `public/js` endpoints, each one's real home already resolved),
#774 (the optimized SEPA batch silently collects fewer invoices than asked; the shortfall is
computed and then handed to `frappe.logger()`, which drops it on level), #778 (payment
dashboard notification toggles saved but honoured by nothing), #780 (the org-level half),
#781 (`create_periodic_agreement` still mints an inert SEPA agreement), #783 (two "partial
failure" tests that cannot fail — one calls the function with two kwargs it does not have),
#785 (authorization inside cached bodies).

**Closed on evidence:** #427, #463, #642, #745, #782. **#461 was wrongly reported fixed by
me and is still live** at `bank_transaction_reconciliation.py:2362`.

## For next session

1. **#776's fixture** — the email-fallback question above. Same shape as #780; worth
   checking whether `create_test_member(email=...)` persists what it is handed.
2. **#777** — fix the `anonymous` writer, then merge behind #784.
3. **#780's remaining half** — the setting for form rendering, and a decision on whether
   `is_dutch_installation()`'s cached scan should exist at all afterwards.
4. **#774** is the highest-value filed issue: a monthly dues batch that collects 337 of 340
   invoices and reports success is the same shape as the bugs that took longest to find today.
5. The **12 leaked Dutch test companies** on this bench are why #780 was invisible locally.
   They are worth removing, and they are a live example of the leak class #332 tracks.
