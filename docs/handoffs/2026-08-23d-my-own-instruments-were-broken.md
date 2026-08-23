# Handoff — 2026-08-23d: my own instruments were broken, in the way they were built to detect

Picked up from `2026-08-23b-the-round-nobody-reviews.md` (PR #503) and worked its
"for whoever picks this up" list to the end. Four PRs open, all reviewed before opening,
all revised afterwards.

The 22f/23b sessions were about a right answer resting on a dead reason. This one is
narrower and more embarrassing: **twice, the guard I wrote against an instrument failure
had that exact failure.** I added two positive checks so that a dead recorder could not
pass a selftest — and wrote them with `grep -o`, which exits 1 on no match, so under
`set -o pipefail` the script *died* instead of reporting FAIL. Then I bounded some new
output with a cap, in a commit whose message invokes *no silent caps*, and the cap
silently truncated the selftest's own controls out of the report.

Both were caught by running the mutation rather than reading the green. Neither would
have been caught by anything else.

## Landed

| | | |
|---|---|---|
| #512 | #485: swallowed-failure logs to a sink CI reads; ratchet 3 → **14** | open, CI green |
| #511 | #498: the builder registers only what it created (**blocks #489**) | open, CI green |
| #510 | the delete-resurrection auditor, report-only | open, CI green |
| #518 | #482: the drain no longer strands ledger rows | open, CI running |
| #513 #514 #515 #517 | filed from the reviews and the measurements | open |
| #462 #466 #482 | new measured evidence posted | open |

Three skeptical reviews ran in parallel, one per PR, each on its own test site. Every one
found something real, **including in claims I had already published.**

## What the reviews overturned

> **The rule that keeps earning its place: an agent's report is not evidence until you
> have checked the one number you are about to repeat.** It cut both ways this time. The
> reviews were right on every point below — and one of their own headline numbers was
> wrong, and my re-measurement is what found it.

**A published falsehood on #466.** I had commented that the raise blocks `company_iban`,
`company_bic` and `company`. Re-measured with controls: **4 of the 5 fields do not exist**
on `Verenigingen Settings`; the IBAN/BIC pair lives on `Verenigingen Payments Settings`,
a different doctype. Only `company` is real, and it is the one that raises. The conclusion
("the helper applies nothing") held; two thirds of the reasoning did not. Corrected in a
follow-up comment rather than quietly edited.

**#511's central claim was wrong in my favour.** I wrote that the borrowed-chapter delete
is always undone by "the base teardown's rollback". That rollback is **conditional** —
`_rollback_once_before_draining` returns early unless a tracked document still exists —
and Frappe has **no per-test rollback at all**, only `addClassCleanup(_rollback_db)`.
Measured, same committed chapter, both trees:

| shape | develop | fixed |
|---|---|---|
| `cleanup()` in `tearDown` + one tracked doc | survives | survives |
| `cleanup()` **mid-test**, then any commit | **gone, committed** | survives |

So it is a live mechanism with no current call site, not a delete that cannot stick. Three
suites call `cleanup()` mid-test and they build member-only today; that is the only reason
it has not already taken the shared chapter out from under a shard.

**My #498 census was scoped to one API and published as the class.** The same
register-after-get-or-create shape written with `track_doc` sits in
`test_fuzzy_logic_modernization_validation`, and there it is *worse*: that drain commits
after every delete, so a borrowed User is deleted for good. Two occurrences; both fixed.
Two more rows of my nine-row table certified registrations for doctypes that **do not
exist** (`Verenigingen Volunteer`, `Volunteer Expense`), so every Volunteer the builder
creates is never cleaned up and `with_expense` is dead code (#491).

**"Four vacuous tests" was nine, and "noisily always-green" was false.** Their handlers
are still bare `frappe.logger()`, so they write nothing.

**The auditor's own documented command recorded nothing.** Verbatim from its README, on a
real module: `Ran 7 tests … OK`, **no log file created**, and then `recorded=0 … exit 0`.
A dead recorder and a clean module were byte-identical output — `cleanup_status ==
"skipped"` in a new costume, in the tool built to replace it. And two of its four controls
stayed green with the recorder entirely stubbed out.

## #482: the route was not what the issue said, and that changed the fix

Every number about #482 had come from calling `_remove_drained_record` directly or from
inference. Driven through a real teardown, one committed posted invoice produced **seven**
submits, not four:

```
Sales Invoice         ACC-SINV-2026-01002
Payment Ledger Entry  4g9c21ohcg     <- written during TEARDOWN
GL Entry              1a6af01165     <- written during TEARDOWN
GL Entry              604d164e0c     <- written during TEARDOWN
```

Afterwards: parent **gone**, 2 GL + 1 PLE resident, run reported `OK` with no leak
recorded.

**The survivors are not the invoice's original ledger rows.** The captured-insert drain
deletes those, because they were captured during the test. They are the **reversals the
drain's own cancel wrote**, created after `_captured_inserts` was snapshotted. So
exempting `GL Entry` / `Payment Ledger Entry` from the drains — the intuitive fix — makes
this **worse**, not better.

And they do not merely sit there. An identical second run took the same docname and read
`GL=4 PLE=2` *at the moment it posted*: `revert_series_if_last` rewinding the series,
+2 GL / +1 PLE per run under one `voucher_no`.

A global orphan count cannot see any of this — the orphan is created and consumed inside
the run. Record identity at **submit** time and ask afterwards, in another process.

PR #518 shares the rule in `tests/utils/ledger_rows.py` (the duplication *was* #482) and
sweeps after the parent is gone — the sibling base's *other* rule, not its carve-out.
Seven modules pairwise: identical outcomes and **identical leak counts on all seven**, so
it does not move the ratchet. `test_sepa_reconciliation` sweeps 4 rows on the branch and 0
on develop: the real-suite confirmation.

## The site dirt finally has a cause

`CustomerCleanupMustNotStrandLedgerRowsTest` errors on one test site and passes on another,
on every branch. Two sessions each spent a run establishing it was "not a branch signal"
without finding why. It is **#462**:

```
test_site_5: Company 'Nederlandse Vereniging voor Veganisme'
  default_income_account     = '8000 - Contributie Leden … - NVV'   exists: None
  default_receivable_account = '1350 - Te ontvangen bedragen - NVV' exists: None

test_site_3: that Company does not exist -> a different one is resolved -> the fixture works
```

`create_test_sales_invoice` reads `debit_to` from the receivable default, and the dangling
link surfaces frames later as `TypeError: cannot unpack non-iterable NoneType object`,
naming neither the Company nor the Account. **#462 names only one of the two broken
pointers.** Not checked on veg11 — if it is broken there, this is not a test-only problem.

## Two hypotheses I tested and rejected

Recorded because both are the sort of claim that otherwise gets asserted into a docstring.

- **A third #482 instance at `docstatus == 2`.** `_cancel_if_submitted` gates on
  `docstatus == 1`, so a cancelled voucher should walk past the carve-out into
  `delete_doc(force=True)` and strand its reversals. Probed: parent gone, **0 GL / 0 PLE
  on both trees.** The sibling's customer-cleanup path already purges them.
- **"#482 has no live impact."** My first end-to-end run stranded nothing, and I nearly
  read that as the answer. It had errored before reaching the code that commits — the #462
  failure above. A run that did not reach the mechanism is not evidence about it.

## Corrections to the 23b handoff

- It names `test_fee_change_settled_invoice_isolation` and `test_sepa_reconciliation` as
  stranding +2 GL / +1 PLE per occurrence. `test_sepa_reconciliation` is now **confirmed**
  (4 rows swept). The first **cannot be measured on these sites** — #462. Treat that suite
  count as unverified.
- Its claim that the stale `#445` sentence was "fixed in the skill" is true on
  `origin/develop` but my local checkout was 15 commits behind, so the skill I loaded still
  carried it. **A bare `bench` control is the live checkout, not `origin/develop`** — see
  below; it cost me a bogus 14-vs-13 test count.

## Traps worth carrying

- **`PYTHONPATH` loses to cwd inside `apps/verenigingen`.** Python's leading `''` precedes
  it, so `import verenigingen` resolves to the **main checkout** — the live tree. CLAUDE.md's
  verification snippet only works from `~/frappe-bench`. A whole branch-vs-develop
  comparison can run the same code twice and read as "identical".
- **Pin the control worktree.** `git worktree add <dir> --detach origin/develop`. A bare
  `bench` runs the installed app, which lags whenever a merge has landed and nobody deployed.
- **CodeQL cannot see a bare `frappe.logger()`.** Route the record through a real stdlib
  logger and `py/clear-text-logging-sensitive-data` fires — so a conversion that changes only
  *where* a message goes turns a long-standing exposure into a new CI failure. It flagged the
  interpolated exception first and then the password-dict **key**. Read the alert's
  `location.start_line` before assuming which expression it means; guessing cost a round trip.
- **`read -r -d ''` strips leading whitespace**, so an indented method in a shell heredoc
  silently became a module-level function and its test never ran. The tell was `Ran 1 test`
  where two were expected.
- **`pkill -f <script-name>` matches your own shell** and killed it mid-command (already in
  memory; it happened again).

## For whoever picks this up

1. **Merge order.** #511 and #518 both add a class to `test_harness_leak_attribution.py`.
   #511 first, then rebase #518. #510 deliberately no longer touches that file — its
   `_territory` import is lazy, which also removed an 8.1s / 2070-module collection-time
   import into a module whose tests all skip.
2. **All four PRs are now behind `origin/develop`** (`889b9af3`, #500 merged during the
   session). CI ran against the older base; re-check after merging develop in.
3. **#482 stays open on purpose.** #518 removes the measured harm but does not unify the two
   bases' policy. Adopting `_cancel_if_submitted`'s refuse-to-cancel rule is more
   conservative and arguably more correct, and would leave a submitted parent resident in
   every suite that commits a posted voucher — moving the leak ratchet by an amount nobody
   has measured. Measure that delta before deciding.
4. **#489 is still blocked, and now for a sharper reason.** #511 fixes #498, but the mid-test
   path measured above means giving `cleanup()` its commit makes the `tearDown` path durable
   too. Read #511's comment thread before touching it.
5. **#510 is not a gate and should not become one yet.** Its own census question is
   unanswered, and #517 shows why: the module it held up as a negative control strands four
   rows in one run of seven. A single zero from an intermittent process is not a control.
6. **#517 needs stderr.** Run `test_event_driven_payment_history` in a loop capturing stderr
   until it goes non-zero. There are **zero** `Error Log` rows for the failing run, so
   whatever ended that teardown early said nothing anywhere — itself the #485 class.
7. **Four handoff PRs are unmerged** (#503, #502, #507, and this one). They are accumulating,
   and #507 already had to note two claimed slots.
8. **MEMORY.md was over its size limit** and only partially loading. I trimmed 77 index lines
   to ~200 chars; 5 of them had their trailing hook text cut by a buggy first pass (the
   pointers were repaired and all 118 resolve, but that text is gone). Another session is
   writing to the same index concurrently — its entries survived.
