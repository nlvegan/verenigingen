# 2026-09-22 — a prior fix is not a verified precedent

Six PRs merged, six issues filed. The two findings worth carrying forward are both about
*evidence*, not about SEPA: a fix that already exists is not proof its source is right,
and a mutation run in the wrong environment proves nothing at all.

## What shipped

| PR | Issue | What it does |
|---|---|---|
| #1234 | — | 2026-09-21 session handoff |
| #1243 | #1196 | Weekly/Semi-Annual catch-up billed on running periods, not one lump |
| #1245 | #1230 | Post-submit `batch_log`/`status` writes persist; `Cancelled` declared as an option |
| #1246 | #1232 | Never-generated batches excluded from bank-return correlation |
| #1247 | #1227 | `membership` key restored in the `_secure` loader |
| #1248 | #1239 | **Both** loaders emit the real Membership, not a dues-schedule name |

Filed along the way: #1249, #1250, #1251, #1252, #1253, #1254.

## #1239 — the precedent was the thing carrying the false premise

`load_unpaid_invoices` selected `membership_dues_schedule_display as membership` — a Link
to Membership Dues Schedule aliased over the key `Direct Debit Batch Invoice.membership`
(Link → Membership, `reqd`) consumes. `direct_debit_batch.js` feeds those rows into
`frm.add_child('invoices', inv)` verbatim, so the live "Load Unpaid Invoices" button
populated the grid and the **save** died with `LinkValidationError`.

Three call sites resolve this same value, and **two had already been fixed for this exact
bug**. They disagree with each other:

| site | source | populated on veg11 |
|---|---|---|
| `sepa_race_condition_manager` — already "fixed", with a comment explaining the fix | `si.membership` | **0 of 1927** |
| `create_sepa_batch_validated` — comment says "the AUTHORITATIVE link" | `Membership Dues Schedule.membership` | 431 of 565 |
| `load_unpaid_invoices` — the bug | the dues-schedule name | wrong doctype entirely |

The race-manager repair reads as the obvious precedent to copy. Its column is empty on
every real invoice: it converted a `LinkValidationError` into a silent `None`, so the
`reqd` field now fails as `MandatoryError` instead. Copying it would have shipped a second
broken fix with a comment vouching for it. → **#1249**.

**A prior fix is evidence that someone believed a source was right, never that the source
has data in it.** One `COUNT(*)` per candidate discriminated instantly. When several sites
resolve the same value, do not pick by which has the better comment — and if they
disagree, that disagreement is itself the finding.

`dd_batch_optimizer` already emitted the correct value, so three producers now agree.

### The population nobody had counted

134 of those 565 invoices (~€13.4k) carry a **dangling** dues-schedule link: the schedule
row is gone and `si.member` is empty, so nothing can resolve them by any path. They are
returned with `membership` blank plus an `unbatchable_reason`, and the JS reports them
rather than adding them — dropping them silently would be the harm #1228 nearly shipped;
adding them keeps the batch unsaveable, which is the bug being fixed. The data defect
itself is **#1250**.

## The sharpest lesson: I ran my own mutation where it could not discriminate

The independent review of #1248 found a real defect **in my tests**, not in the fix. Two
of the four called `load_unpaid_invoices` with **no `membership_type` scope** at
`limit=500`. The endpoint caps at `limit` and orders by due date, so on a site holding
more than `limit` unpaid invoices the fixture is simply not on the returned page — and the
test fails *whether or not the bug is present*.

- `test_site_1` (mine): under 500 → my mutation run looked clean.
- `test_site_3` (the reviewer's): **584** → both tests failed with the fix applied **and**
  with it reverted. Zero discriminating signal.

**Choosing the environment is part of the experiment.** I did not treat it as one. This is
the class #1223 already names, in the one file whose other tests all scope.

Fixed by construction rather than by raising the limit: the integration test now uses an
unresolvable shape that still carries a `membership_type` to scope by, and the *dangling*
shape — the one the live data actually exhibits, and which cannot be scoped at all, since
a nonexistent schedule has no type to filter on — is pinned in a helper-level test needing
no site data.

**Second-order, worth keeping:** the new twin-parity test does *not* redden under a
shared-helper mutation, and that is correct — both twins move together. It had to be proven
with a mutation that diverges *one* twin. A mutation that moves everything cannot test a
relation between two things.

## What the review round bought

Six PRs, six independent skeptical reviews. **No review found a defect in a PR's production
diff.** The findings were in the record, in a test suite, and in what sat *next* to the
diff:

- **#1247 — premise false in three places.** PR body, source comment and test docstring all
  claimed `direct_debit_batch.js` consumes the `_secure` endpoint. It does not: zero `.js`
  references to `load_unpaid_invoices_secure` anywhere, and `can_load_unpaid_invoices` (the
  button's visibility gate) checks the non-secure twin. Corrected in all three before merge,
  because two of them ship into develop permanently.
- **#1246 — "0 additional instances" was 1.** The sweep grepped `frappe.get_all(...)` and raw
  SQL; `match_by_batch_reference` uses `frappe.db.exists(..., ["like", ...])`, which neither
  pattern matches. No status/`sepa_file_generated` filter at all, confidence 1.0, and unlike
  the function #1246 fixed, it sits in front of a live Payment Entry writer. → **#1253**.
- **#1245 — the sweep looked for the wrong thing.** It grepped *consumers of the string*
  `"Cancelled"`, not *writers of* `Direct Debit Batch.status`, so it missed **#1237**
  (`"Partially Processed"`, undeclared, reachable from a whitelisted financial endpoint, with
  an existing test that asserts the bug and passes).

**The generalisable one:** each sweep was scoped by the shape its author already had in mind.
A grep pattern is a hypothesis about how the bug is written, and it inherits the author's
guess.

## #1254 — a nondeterministic test that can redden any PR

`test_logged_in_own_member_can_read_via_own_id_param_with_no_token` reddened #1248's shard
1/12. It is worth recording *how* it was cleared, because a green rerun on its own would
have proved nothing:

- The change's own strings appear **zero** times in the shard log.
- It passes solo, and passes behind the exact 17-module CI prefix on two sites, with and
  without the branch (`order_dependence_detector.py`, 238 tests, 0 failures).
- The single job was re-run — same tree, no push between — and the prefix diffed **identical
  in set and order**. Original `✖`, rerun `✔`.

A shard rerun reproduces co-tenancy and order by construction, so a deterministic
order-dependent failure repeats identically. This did not, so it is nondeterminism, not
packing. The mechanism was **never reproduced locally**, and #1254 says so rather than
inventing one. A timezone theory fit the 23:06 UTC timestamp and was rejected for want of a
mechanism — there is no naive clock read anywhere in that path. **A fitting timestamp is not
a mechanism.**

It is in neither `order_dependence_baseline.txt` nor `known_test_failures.txt`, so it will
block an unrelated PR at random until fixed.

## Still open

1. **#1254** — the nondeterministic portal test above. Highest nuisance value: it can redden
   anyone.
2. **#1251** — three `direct_debit_batch.js` child-table handlers are registered on
   `'Direct Debit Invoice'`, a doctype that does not exist. Mandate auto-fill and total
   recalculation have **never run**. Fix before #1252, since #1252's endpoint is the dead
   handler's only consumer.
3. **#1253** — `match_by_batch_reference`, no filter, live Payment Entry writer downstream.
4. **#1250** — the 134 dangling dues-schedule links. Find what deletes a schedule out from
   under its invoices *before* repairing the rows, or it recurs.
5. **#1249**, **#1252** — the empty `si.membership` column and the two latent aliases.
6. **#1204 + #1201** — unchanged from the previous handoff.

## Process notes against myself

- I wrote two of #1239's four tests **after** applying the fix. Mutation proved all four
  redden, so the evidence stands, but the order was inverted and the mutation was recovery,
  not design.
- I reported that four reviews found "no code defects." True of the diffs, but two had
  surfaced live defects adjacent to them (#1237, #1253). The sentence undersold the round.
- An `order_dependence_detector.py` run was killed by my own `timeout 590` and printed
  `Terminated`; I read that as a result for a moment. **A cap shorter than the job is not a
  measurement.**
