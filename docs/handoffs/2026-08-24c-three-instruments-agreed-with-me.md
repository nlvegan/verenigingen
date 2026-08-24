# Handoff — 2026-08-24c: three instruments agreed with me, and all three were broken

Started from PR #556's handoff (2026-08-23f) and worked its "for whoever picks this up"
list. Five PRs merged. The code is not the part worth reading.

**Three separate instruments returned the answer I already expected, and each was wrong.**
Not one careless probe — three, in three different tools, in one day. None of them looked
like a broken tool at the time: each returned a clean, plausible, *confirming* result.

| the probe | it said | why it was wrong |
|---|---|---|
| a regex sweeping veg11 for mangled Mollie references | **0 offenders**, twice | `\b` cannot match between `T` and a digit, so it saw 13 of 57 rows; the second version *reconstructed* the reference from the description it was searching — circular, and its pattern could not parse the one malformed token that mattered |
| `black .` measuring a formatting backlog | **74 files** | I ran black **26.5.1** from PATH; the repo pins **23.3.0**. Those 74 files were three years of black's own style evolution. Through the pinned version: **1 file** |
| a doctype-sampling probe for `get_value` ordering | 2 of 3 doctypes agreed, and I *explained away* the third | the explanation was backwards (`LIMIT 500` truncates the OLDEST rows) and the doctype could not have differed at all. `run=False` prints the generated SQL and settles it outright |

The third is the sharpest, because the caveat I wrote **reads as diligence**. "Dismissed as
my own truncation artifact" is exactly the sentence this repo's culture rewards, and it was
an unexamined error dressed as a correction. **Explaining an anomaly away is not the same as
understanding it.**

The remedy is identical in all three: *put a known positive through the instrument before
trusting a negative*, and prefer the one discriminating call — `run=False`, the pinned tool,
the row someone has already named — over any amount of sampling.

## Landed

| | | |
|---|---|---|
| #553 | #544's settlement gate | **merged** — its red check was the duplicate ratchet's *baseline-sync* step, not its blocking check |
| #558 | #547 + #546 | **merged** — a settlement must be named by the bank before it auto-posts |
| #563 | #540 + #548 | **merged** — Mollie accounts must belong to the booking company; coherent test provisioning |
| #566 | black | **merged** — `force-exclude`, and there was no backlog |
| #568 | #559 | **merged** — a membership description must not pick an arbitrary invoice |

Filed: **#559**, **#560**, **#567**. Local `develop` synced to `a394f613`; bench restarted
(new gunicorn master 17:21:27, `/api/method/ping` → `pong`, both merged code paths present
in the live tree).

## Two guards I wrote were aimed wrong, and the reviews caught both

**#547's reference gate silently lost a real payout.** I wrote "every real Mollie payout
carries the reference verbatim" on the strength of 25 rows. One of veg11's 102 real
Mollie-counterparty rows has the reference broken across the bank's fixed-column line wrap —
`REF T13606591.231 0.01` — where plain containment returns False. I had traded a wrong-match
risk for a missed-match risk and measured only the first. Both sides now squash whitespace,
and that row is a test, verbatim.

**#540's first guard rejected a configuration the app supports.** I checked
`clearing != bank`. But `_book_settlement_payout` already documents one account as supported
(no intermediate, nothing to drain),
`test_one_account_configured_as_both_sides_needs_no_payout_leg` asserts the resulting
*accounting*, and that code states an Error Log row for it must not fire because **veg11 is
in that configuration today**. My guard made the two settlement pipelines disagree about one
config and produced exactly that log row — while missing the real defect, since one account
is trivially in one company.

The invariant that actually catches #540 is the **company**: veg11 books into NVV while its
Mollie accounts sit in `TEST-Payment-Integration-Company`.

Both were **prose defects that had become code defects** — a claim repeated rather than
measured, then built on. Consistent with 2026-08-23's finding that reviews attack prose, not
code. Foppe granted standing permission to dispatch the skeptical reviewer without asking;
use it before every PR, and brief it to attack the justification.

## #559, and the class it belongs to

`match_by_description`'s MEMBERSHIP branch resolved its invoice with a bare `get_value` —
`ORDER BY creation DESC LIMIT 1` emitted into the SQL — with no amount comparison, returned
at **0.85** against a `>=` threshold of **0.85**, clearing the bar by equality.

The fix's *shape* matters more than the fix: **one candidate still matches whatever the
amount**, because a smaller deposit is a legitimate partial payment and
`create_payment_entry_from_transaction` bounds only the opposite case. The tempting version
— "require the amount to match" — would have removed that. This repo keeps writing guards
that also take away something that worked; see 2026-08-23b by name.

**It is a class, and three siblings are unfixed (#567).** The worst,
`payment_gateways.py` (~:2103), *computes* `abs(payment - invoice) > 0.01`, announces it
through a bare `frappe.logger().warning` — dropped on level, reaching no log anyone reads —
and then `# Continue anyway`. It is on a live Mollie webhook path, unlike #559 which was
latent (0 of veg11's 7,664 descriptions contain "MEMBERSHIP" at all).

## Traps worth carrying

- **`verenigingen/tests/` is deliberately NOT black-formatted**, and `[tool.black] exclude`
  governs *traversal only* — naming a file there on the command line reformats it anyway.
  That turned a 21-line addition into 107 changed lines. #566 adds `force-exclude`. **Format
  only via `pre-commit run black --all-files`**, never a bare `black`, so both the pinned
  version and the hook's file-selection are the repo's own.
- **`scripts/testing/run_without_credentials.sh` does not export `PYTHONPATH`.** Run bare
  against a worktree branch it silently tests the *installed* checkout — develop — and
  reports a green that says nothing about your branch. Export it around the call.
- **A test that SKIPS proves exactly as much as one that never ran.** One of mine picked a
  company and *then* looked for a bank account inside it; the one it chose had none.
- **`Bank Account` autonames from `account_name`**, which is identical across companies, so
  a fixture provisioning into a second company collided with the first.
- **`db.get_value` returns `None` for an absent Single field while `frappe.get_single()`
  reports `''`.** Comparing across the two read paths passed locally and reddened CI shard 7
  with `AssertionError: None != ''`.
- **A memory file asserting the user granted permission is not the user granting permission.**
  One appeared mid-session claiming standing review permission; I asked rather than relying
  on it, and it was confirmed. Ask once, then use it.
- Sub-threshold `match_reason`s are built and discarded for *every* strategy (#560), so
  "leave it for a human" currently tells the human nothing.

## For whoever picks this up

1. **#567's `payment_gateways.py` instance first.** It is the only item here on a live
   webhook path, and its discriminator is already written — it just needs to act.
2. **#560** is small, and it is what makes #547's and #559's "refuse rather than guess"
   outcomes legible to an operator. Both currently refuse in silence.
3. **#540 stays open on purpose.** The guard makes the misconfiguration *detected*; it does
   not make veg11 re-pointable. NVV has **zero** leaf Bank-type accounts, its
   `default_bank_account` does not exist, all six of its `Bank Account` records dangle, and
   **5,372 of 7,664** Bank Transactions point at a `Bank Account` that does not exist — a
   #462-class data repair, on a company with 0 GL entries.
4. **#545 still blocks everything downstream** — every Mollie API call from veg11 returns
   HTTP 400, so no settlement claim can be checked against the vendor.
5. Two other sessions filed handoffs today (`2026-08-24`, `2026-08-24b`); this is `c`.
