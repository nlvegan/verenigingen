# 2026-08-25d — the shrink that looked like progress

Two PRs merged: **#575** (`1fffeb4ac`, closes #567) and **#585** (`98003ca45`, closes #578).
Both are fine. The part worth reading is that **every artifact that reported progress today
was reporting its own blind spot**, and in three of four cases the reported number, colour or
diff direction was the thing that made the blind spot invisible.

Three other sessions filed handoffs today — `2026-08-25`, `2026-08-25b` and `2026-08-25c`.
This is `d`, and it starts from `c`'s top item.

---

## The lead: four instruments, four false readings

| the instrument | what it said | what was true |
|---|---|---|
| unittest's `====== FAIL ======` block | shard 11 failed at **11:23:28**, and the module that provisions the shared fixture is not in this shard | that block is the **end-of-run summary**. The class ran at 11:18:11; the provisioning module ran at 11:22:57, i.e. **after**. It was in the shard all along |
| a grep window (`LIMIT 1` within 1200 chars of `tabSales Invoice`) | **13** occurrences, "each verified by reading the code" | **11**. The window swallowed `LIMIT 1`s belonging to unrelated queries in the same file — three attributed to a report that has **none** on that table |
| the Swallowed-Exception Guard | a line **left** the baseline; CI says regenerate | the swallow did not go away. Its return changed from `None` to `InvoiceChoice(None, 0)`, and `_is_falsy_return` matches only literals, so the **ratchet went blind** |
| a red control | red, therefore the mechanism is proven | red as an **ERROR** on a missing stub attribute, before the assertion ran. Twice today, on two different controls |

The common shape is not "I was careless." Each artifact answered a *slightly different question*
than the one I asked it, and its output was well-formed enough to read as an answer to mine.
A timestamp that is really a print time. A proximity match that is really a parse. A baseline
line that is really a classifier verdict. A non-zero exit that is really any exception.

> **The tell in all four: the reading was the one I wanted.** A shard that isn't at fault, a
> census that is bigger than the issue's, a ratchet count that went down, a control that went
> red. When an instrument confirms you, that is the moment to ask what question it actually
> answered.

### The one that would have shipped

`error_swallow_validator._is_falsy_return` (lines 200-215) recognises `None`, a falsy
`ast.Constant`, and an empty `Dict`/`List`/`Tuple`/`Set`. Nothing else. So changing a handler
from `return None` to `return InvoiceChoice(None, 0)` — **no behavioural change whatsoever** —
takes it out of `scripts/validation/error_swallow_baseline.txt`.

CI's instruction on that failure is `--update-baseline`, and the resulting diff shows a
**removed** line. Both read as progress. Committing it silently converts a guarded site into
an unguarded one.

Scope, stated as scope: **I checked one site.** Any handler returning an `OperationResult`, a
`create_service_result(...)`, a dataclass, a namedtuple or an enum member is invisible on the
same grounds, and this app has three coexisting result conventions. The count is unmeasured.
**#586.** Note the heuristic had already been widened once — from `None`/`False` to any falsy
literal — after `return ""` got through. This is the same gap one step out, which is the
argument for measuring the class rather than patching the instance.

What #585 did instead of banking the shrink: regenerated the baseline (CI requires it) **and**
replaced that handler's `frappe.logger().warning` with a real `frappe.log_error`, so the site
keeps the observability the baseline entry stood for.

---

## Both skeptical reviews reversed the fix. The second caught a regression worse than the bug.

Run before opening each PR, per the standing permission — and on #575 also before merging.

**#575.** The review's lead finding was that my *diagnosis* was wrong (the timestamp above),
and that correction moved the fix. I had provisioned the bank account from inside the fixture,
which means `frappe.db.commit()` in a test **body**, committing the caller's in-flight
fixtures including a submitted Sales Invoice. `ReconBase.setUpClass` exists to prevent exactly
that and says so at `test_sepa_reconciliation.py:97`. The replacement is what five other suites
already do — `get_eur_bank_account(get_eur_test_company())` in `setUpClass` — and is smaller
than the thing it replaced. My "load-bearing suspension" measurement was correct but only
load-bearing *for a design that shouldn't exist*.

**#585.** The review found that adding a refusal to an invoice matcher **created an invoice**:

- `_resolve_invoice_fresh` falls from `not match_result.found` straight to
  `_create_invoice_if_safe`, and `complete_partial_payments` passes
  `create_missing_invoice=True`.
- Member two months in arrears on a flat fee pays one month → matcher refuses → the calculated
  window is the NEXT period (measured: 2026-08-22 to 2026-09-21) → overlaps neither arrears
  window → the overlap guard permits the create.
- The member is **billed a third period for having paid**, both arrears still open. Strictly
  worse than the arbitrary pick the refusal replaced, on the one path that is explicitly a
  money-mover.

> **When you add a refusal to a resolver, find every caller that reads a falsy return as
> "nothing exists".** Carry the refusal as its own state and branch on it before any
> create / retry / fallback path. `ambiguous_candidates` existed in my first commit and had
> no consumer, which is precisely why it did not prevent this.

Three more from the same review, all real: strategy 2 could **launder** strategy 1's refusal
(it filters on amount, strategy 2 does not, so a €25 payment landed on a €40 invoice with both
€25 arrears open and nothing logged); item 1 compared `grand_total`, the column its own SQL had
already filtered on, so rule 2 was **inert** there; and the coverage-keyed sites should not
consult the amount at all, because a duplicate on a window usually exists *because* the price
changed — so the invoice matching an unchanged standing order is the stale one, and an amount
discriminator picks it every time rather than sometimes.

---

## State

| | |
|---|---|
| **#575** | **merged** `1fffeb4ac` — closes #567. Four sites resolving ONE invoice out of a candidate set |
| **#585** | **merged** `98003ca45` — closes #578. Five more, incl. one on the live Ponto webhook that #578 does not list |
| **#581** | filed — three un-converged copies of a stamp-and-borrow bank-account helper; borrows by `creation DESC` then **commits** the borrowed row into `Company.default_bank_account`, which five production readers consult. The duplicate ratchet records `::2` because it keys on the function NAME and cannot see the third |
| **#582** | filed — a test nulls `Company.default_bank_account` with no `finally` restore while calling production code; an independent producer of #575's symptom |
| **#583** | filed — three test sites resolving a Bank account with no company filter, or with a global fallback under the comment explaining why that breaks them. ~97 occurrences of the broad pattern stated as **unaudited**, not cleared |
| **#584** | filed — two Active SEPA Mandates → `ORDER BY sm.creation DESC LIMIT 1` → the JS writes the chosen mandate's IBAN into the row the SEPA XML is built from, so **an arbitrarily chosen account is debited**. I first dismissed this as "same shape, different object"; that undersold it |
| **#586** | filed — the swallow-ratchet blind spot above |

`develop` is at `98003ca45`.

---

## Traps worth carrying

- **A `====== FAIL ======` block in a Frappe `run-tests` log is printed at end-of-run.** To
  establish order in a shard, grep the per-class start lines (`verenigingen.tests....ClassName`
  appears once, at its start) and sort by timestamp. Observed discovery order: **per directory,
  then alphabetical by filename** — so `tests/payment/test_b*` runs before `test_i*` before
  `test_p*`. Which suite provisions shared master data first is decided by **filename sort**,
  not by shard membership: a suite that sorts *after* its consumer can never help it.
- **A fixture needing shared master data must provision it in its own `setUpClass`.** Never
  rely on an earlier module in the shard. Five suites in this repo do it correctly; the two
  that didn't are what reddened shard 11/12.
- **`_is_falsy_return` is literal-only** (above). **Read every baseline SHRINK before
  committing it.**
- **A control that fires is not yet a control that fires for your reason.** Twice today: one
  went red on `DuplicateEntryError` because my probe had neutralised the account the fixture
  wanted to create; one errored on a missing stub attribute before its assertion ran. Both
  looked like proof. Read the failure TEXT.
- **A `SimpleNamespace` stand-in for a dataclass drifts silently.** Seven fakes of
  `InvoiceMatchResult` broke on a new field. Update the fakes — do NOT
  `getattr(..., default)` in production code to defend it against a test double.
- **`gh issue view --comments` is broken here** (Projects-classic GraphQL, same as
  `gh pr edit`). Use `gh api repos/<o>/<r>/issues/<n>`. And **backticks in a `gh` `--title`
  argument are command substitution** — it silently ate a fragment of #586's title; fix with
  `gh api -X PATCH`.
- **A downloaded Actions job log was truncated to 0 bytes mid-session** while I was still
  grepping it, and every subsequent grep returned 0 hits — which reads exactly like "the
  string isn't there". Re-download before trusting a grep that suddenly comes back empty.
- **`black` accepts 114-character lines** in `verenigingen_payments/**/tests/` even at
  `--line-length=110`, and `pre-commit run black --files` passes on them. The pinned black is
  what CI runs, so match it rather than the stated limit.
- **The "fix end of files" pre-commit hook rewrites the file and ABORTS the commit.** Re-stage
  and commit again; the first attempt is not a failure of anything else.

---

## For whoever picks this up

1. **#586 first, and measure before fixing.** The question is not "how do I widen
   `_is_falsy_return`" but "how many handlers in this app return a sentinel object". Until
   that number exists, every swallow-baseline shrink is unverifiable — including any that
   land between now and then.
2. **#581** is the one with production reach: three copies of a helper that commits a
   creation-DESC-borrowed account into `Company.default_bank_account`. Own the account by
   name the way `get_eur_test_company` owns its company, then converge the two
   `_ensure_default_bank_account` copies and update the duplicate baseline. Doing that also
   makes #583's suggested fix available, and unlocks the pin I declined to write in #585
   (plant a decoy a borrow would prefer, require the owned account anyway — the shape already
   proven at `test_sepa_reconciliation.py:349-379`).
3. **#584 needs one empirical answer before any code**: can a member hold two `Active` SEPA
   Mandates? If a validation hook cancels siblings on activation, this is latent and the fix
   is a guard; if not, it is live and an arbitrary IBAN is being debited.
4. **#576** is still open and #574 could not see it: `process_individual_return`'s catch-all
   has no savepoint rollback, so neither #574's guards nor its ratchet reached it, and a 1213
   deadlock there is swallowed while `process_sepa_return_file` reports `{"success": True}`.
5. **#560** still makes #547's, #559's and now #578's refusals legible to an operator. #585
   added four more refusals whose whole value is their Error Log rows.
6. **#545 still blocks vendor-side verification** — every Mollie call from veg11 returns
   HTTP 400.
