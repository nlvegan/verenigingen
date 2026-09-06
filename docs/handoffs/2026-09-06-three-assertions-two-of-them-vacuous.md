# Handoff — 2026-09-06: three assertions, two of them vacuous

The session's through-line is not the eight fixes or the nineteen issues. It is that
**a green test is not evidence of coverage**, demonstrated three separate times, twice
against tests I wrote myself. The mutation step — delete the fix, confirm the test
reddens — caught every one. Without it, three tests would have shipped looking like
protection and providing none.

That is now a standing rule rather than a habit: `CLAUDE.md` gained a top-level
**"TDD is unconditional"** section, and Working Principle V was rewritten to point at it
instead of reading as advice.

## The three

**1. My #919 deadlock test passed with the fix mutated away.**
The SEPA savepoint fix (PR #919) shipped with no behavioural test — the AST ratchet
proved the *shape* was gone and nothing proved what the caller receives. Asked to write
one, I injected a `QueryDeadlockError` and asserted the error survives. Green. Then
green again with `except NON_RESUMABLE_DB_ERRORS: raise` deleted.

Injecting a Python-level deadlock leaves the savepoint intact, so the hand-rolled
rollback succeeds and both versions behave identically. The test needed a *second* stub
making `frappe.db.rollback` raise 1305, reproducing what a real 1213 does to the
savepoint stack. Only then:

```
fix present                    OK
fix removed, stub present      FAIL: 'deadlock found when trying to get lock' not found in
                                     'Error generating SEPA file: SAVEPOINT ... does not exist'
fix removed, stub absent       OK     <- the version I nearly shipped
```

**2. An agent's #452 assertion passed vacuously, and hid a live gap.**
It asserted `assertFalse(str(modified).endswith(".000000"))` to show #609's normaliser
had fired. Measured: under the frozen whole-second clock `now()` returns
`'...51.000000'` but the stored value reads back as `'...51'` — no fraction at all.
Which satisfies the assertion *while being the bug shape*.

**3. My replacement for it demanded the wrong mechanism.**
`assertNotEqual(get_datetime(modified).microsecond, 0)` — and it **failed**. #609's
normaliser does not fire on the `Membership` insert path at all. The path survives for a
different reason: both in-memory and stored forms are fractionless and therefore compare
equal, so `check_if_latest` cannot mismatch. The third assertion is the real invariant
(`str(membership.modified) == str(db_modified)`), and all three forms are recorded in the
test body so the next reader does not repeat the first two.

The consequence is a narrowed claim: **"#609 fixed #452" is not established.** #609
explains the signature in #452's traceback, its mitigations are on develop, and the
normaliser measurably does not fire here. #452 stays open. PR #980 pins the shape and
says so.

## One symptom, two causes — and the first fix revealed the second

Worth reading alongside the assertion failures, because the shape is the same: a green
result that would have licensed the wrong conclusion.

#919's Order-Dependence red was diagnosed by review as a staleness artifact — its single
delta was `test_volunteer_sync_service.py`, a file the branch never touches — and
predicted to clear on rebase. I rebased it. It stayed red, with a *different* delta:

```
COMMIT_EXEMPT tests/services/payment/test_sepa_upload_integration.py::5 -> ::6
```

That one is the branch's own. Its first commit adds `TestSEPABatchStatusRollbackOnFailure`,
whose `_cleanup_upload_logs` calls `frappe.db.commit()` — the recognised `_cleanup_*`
exempt pattern. develop's copy of the file carries 6 commits; the branch carries 7. So
the staleness diagnosis was correct *and* incomplete: fixing it uncovered a legitimate
entry that had been masked by the first.

The gated total is unchanged (1005 = 1005) because `COMMIT_EXEMPT` carries its own
marker that the no-growth grep deliberately does not match, so the entry just needed
recording — a one-line diff.

The transferable part: "it cleared on rebase" was never safe to assert from a prediction,
and a re-run that turned green would have been read as confirming the original
diagnosis. My report at the time said rebasing "should confirm or refute that — I have
not asserted it", which is the hedge that made the second cause findable rather than
surprising.

## Every fix that got reviewed had something wrong in it — five for five

| PR | found by review |
|---|---|
| #952 | a sibling endpoint reaching the same rows with neither guard |
| #954 | a shipped **regression** rejecting every legitimate custom amount |
| #919 | a money path fixed with no behavioural test |
| #776 | my own rebase splice: both parents kept verbatim, and verbatim was wrong |
| #922 | blocked by a gate defect, not by its own code |

#954 is the one to read. Widening the outer gate made validation *run*; the inner branch
still picked its rule from the same client flag, so `validate_membership_amount_selection`
took the "must equal the standard amount exactly" branch and refused every typed amount.
A bypass became a refusal. The diff had a below-minimum test and **no positive
counterpart** — that absence is the entire reason it survived to review.

## What I got wrong

* **#957's severity, published.** I wrote "any authenticated user", having read only the
  `SecurityProfile` dataclass and seen no role field. The gate is real and lives in the
  auth engine (`api_security_framework.py:393`). Corrected on the issue: it is a
  horizontal-privilege defect among board/staff-level users, which is lower severity and
  still a defect.
* **A phantom flake I nearly filed.** An agent reported a Mollie chargeback test flipping
  across identical runs. Four runs on an unshared site: 9/9 OK each time. I had put two
  agents on one test site, and a second writer breaks the premise that identical order +
  different outcome means flaky.
* **Five test sites, when thirteen exist.** The sharing above was never necessary.
  `test_site_1` .. `test_site_13` all exist and run tests. CLAUDE.md said five in four
  places; corrected in both copies, with a parity caveat: **6-13 have
  `developer_mode=1`** and CI has `0`, so prefer 1-5 for anything compared against CI.
* **An agent stalled twice** waiting on background notifications, burning 307k tokens for
  one uncommitted file. Stopped it and finished #452 directly.

## Issue premises: three of eight wrong or stale again

* **#369** — the line number pointed at a method already cleaned up, and its "dead code"
  item is a **live behaviour bug**: a whitelisted accounting summary that always returns
  empty `gl_entries` because it joins on the donation name instead of the JE name.
* **#428** — the stated €5.00 minimum was wrong; the fixture's `amount=10.0` kwarg is a
  silent no-op ("Membership Type" has no `amount` field) and the real floor is €7.50.
* **#362** — the rationale claimed no student mechanism exists; a live "Predefined Tiers"
  subsystem with a `Student` tier does. The deletion is still right.

Also: **#349 was already fixed and never closed** — caught by the pre-dispatch
workability check, which saved a wasted agent.

## Cross-codebase investigations

Three, each grounded in a defect confirmed this session rather than a hunch, each scoped
census-and-file with a fix-at-most-one cap and a mandatory control.

* **Endpoint ownership** (#965) — 1406 whitelisted functions scanned, 295 taking an
  identifier, 146 unscoped in money-adjacent files. Filed #966, #968, #969. The important
  correction came from its control: HIGH/CRITICAL endpoints *are* role-profile gated, so
  "any authenticated user" was wrong for most findings.
* **Validator scope drift** (#975) — 18 validators and 8 invariant suites. Filed #970,
  #971, #972, #973. Every finding required a constructed gap shape *and* a control
  proving the invocation was not simply broken.
* **Client-flag policy branches** (#977) — filed #976: any caller with plain
  `Membership: create` can POST `allow_multiple_memberships: 1` and bypass the
  duplicate-membership guard via `/api/v2/document/Membership`. Its own control turned a
  false negative into that finding.

**The most severe thing found all day is #969** — `donate.py::retry_payment` is
guest-reachable with no auth at all, and depends on no role profile. It has no PR.

## Merged

* **#943** — 23 reviewed PRs in one CI run, 45/45 green, 12/12 shards. Open PRs 29 → 6.
* **#951** — regenerated the two stale baselines; develop's Code Validation went green.

`--fail-on-shrink` is passed **only on push events**, so a ratchet red on develop does
not redden open PRs. I predicted the opposite and was corrected by measurement before CI
confirmed it.

## Open decisions — not mine to make

* **#949's metric.** `clone_share` is near-pairs / all-pairs, so it moves the wrong way in
  *both* directions: adding a dissimilar copy drops a family out of the gate, removing one
  pulls it back in. #922 is currently blocked by the second — a consolidation PR failing
  the duplication gate, with the message "recorded into the baseline instead of
  consolidated", which is the reverse of what happened. An absolute near-pair count is
  monotone, but re-arms 57 families with immediate fallout.
* **#958** — 115 sites flatten exceptions into domain errors. Most are legitimate
  external-API wrapping. The defect is the narrower intersection with DB-touching paths,
  and classifying those is the actual work; the census is not a to-do list.
* **#969** needs an owner.

## Verified state

13 PRs open, 19 issues filed. #959's install log read end to end: CI branches per app
(three yarn, verenigingen npm), and a control proved npm applies `overrides` — removing
the `qs` override drops the resolved version 6.16.0 → 6.14.2. Deleting `resolutions`
costs CI no pin and raises four.

Nothing else merged. #952's change request is addressed; #922 remains gate-blocked.
