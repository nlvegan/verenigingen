# 2026-09-09 — four retractions and a dependency that moved

**State at handoff:** `develop` at `c37e65738`. PR **#1103** open at `0053c9f31`, carrying
**5 commits of mine** on top of the previous session's two; two independent skeptical reviews
run against it (one complete and acted on, one in flight at handoff). Issues filed:
**#1110, #1111, #1112, #1113** (plus **#1109** by a dispatched agent). Two agents were still
running when this was written: the #1112 sweep, and the second review.

The session began by acting on the previous handoff's top recommendation. That handoff's own
top item had already been refuted by *its* author, and the pattern repeated all day — mostly
against me.

---

## The through-line

**Every wrong claim today came from an instrument whose scope was narrower than the claim
made from it.** Not from missing evidence — from evidence that could not have shown the
thing being asserted. The strongest instances were mine.

| the claim | the instrument | what it could not see |
|---|---|---|
| "my tests pin the refusal cost exactly" | `_count_queries`, which patches `frappe.db.__class__.sql` | any other channel. A review re-added the removed audit log through `frappe.cache()` and got a **1.50x** existence gap with every assertion green |
| "the shard red is not caused by this branch" | a shard-log grep for my own error strings (zero hits) | that my *tests* might perturb shared state, a different causal path entirely |
| "shard re-packing exposed it" | shard *numbers* | the class sets, which turned out **byte-identical** (330 classes, 2098 tests, same order) |
| "147 of 740 baselined functions are exposed" (as filed: 116) | nothing — I invented the number | itself. Measured afterwards: 147 |
| "four merges in 20s cancelled the develop runs" (#1113) | run timestamps | the workflow's `concurrency:` block, which gives trunk pushes their own group *precisely* to prevent that, and its `paths:` filter, which is the real reason |
| "`server-tests.yml` has no `workflow_dispatch`" | reading 30 lines of a file | line 35 |
| "#1074: 66 guest endpoints are refused" (previous handoff) | a census counting the keyword's **presence** | its **value**. Real population: 0 |
| "#1097: 224 rules are ungated" | an AST sweep over six decorator names | three more decorator names. A runtime instrument said **83** |

The tell is the same every time: the mechanism is real, so confirming the mechanism *feels*
like confirming the claim.

---

## The one that cost the most: a dependency moved, and it looked like a bisect

Shard 10 went red on all three of my pushes while the pre-existing branch tip was green. That
shape reads exactly like a bisect result, and I spent most of a session treating it as one.

It was not. **CI installs `erpnext_branch: version-16` — a branch, not a pinned SHA.**

```
last green run of that shard started   2026-09-07T20:46:25Z
ERPNext 6ec30350d2 landed              2026-09-08T12:13:05Z
   "fix(accounts): reject same-account internal transfers (backport #58529) (#58877)"
every run since                        red
```

The new guard is three lines:

```python
def validate_internal_transfer_accounts(self):
    if self.payment_type == "Internal Transfer" and self.paid_from and self.paid_from == self.paid_to:
        frappe.throw(_("Paid From and Paid To accounts must be different for an Internal Transfer."))
```

`test_bank_transaction_creator_coverage._make_internal_transfer_pe` had **always** built
`paid_from == paid_to`: its `or self.gl_account` fallback returned the account it was meant to
differ from, because `_ensure_gl_account` *creates* `self.gl_account` as a non-group Bank
account for the company and `frappe.db.get_value` returns the newest match. Measured in-test:

```
PROBE gl_account='BTCreator Cov Bank - _TC2' paid_from='BTCreator Cov Bank - _TC2' collapse=True n_bank=1
```

Older ERPNext accepted the invalid document. **This bench is 569 commits behind CI** — v16.30.0
against v16.34.2 — and in it `validate_internal_transfer_accounts` does not exist at all, which
is why the module passed 22/22 locally while failing in CI. Fixed in `0053c9f31`; #1111 has the
full account.

**Two things to carry from this:**

1. **"It was green yesterday" is not a control when the dependency pin is a branch.** Two runs
   of the same branch days apart differ in the merge base *and* the dependency tree, and
   neither is visible in the diff. Nothing in CI records which frappe/erpnext SHA a run used,
   so attribution means reading the dependency's own history by hand. Logging the resolved
   SHAs into the job output would turn a day of wrong hypotheses into one grep.
2. **`CLAUDE.md`'s "erpnext skew 16.20 vs CI 16.30" note is stale.** Local is **16.30.0**, CI is
   **16.34.2**. The direction of the lesson still holds; the numbers do not.

---

## What shipped

- **#1105** (`f5b2099c0`) — the existence-timing oracle in `validate_payment_document_access`.
  Ownership is now proven before the document is read; the return token is an HMAC over
  `doctype:docname` so it needs no read at all. Measured 10.43x (Donation) / **28.36x**
  (Sales Invoice, which the issue never measured) → 1.02x / 1.00x. The largest single component
  was an `INSERT INTO tabError Log` written only on the existing-docname path — a
  guest-triggerable append to a MyISAM table. Also added the dedicated `per_ip` rate-limit rule
  the issue asked for, **deliberately looser** than the fallback: the page polls every 10s for
  5 minutes, so `retry_payment`'s 5/60s would have broken it.
- **#1105, part 2** (`657dc6f21`) — the rate limit would have been **inert on every existing
  site**. `setup_critical_operation_rules` runs in `after_install` only, never `after_migrate`,
  so a fixture-only rule reaches fresh installs and nothing else. `patches.txt` already carried
  `add_retry_payment_critical_operation_rule` for exactly this reason; I had followed half a
  two-part convention.
- **Review fixes** (`4f0560509`) — see below.
- **#1111** (`0053c9f31`) — the fixture fix above.
- **#1110** — deleting one of a function's several swapped `log_error` calls makes the "Every
  shrink was actually a fix" **PR** gate blame a *surviving* call, with the false reason "the
  file left SCAN_ROOTS". Reproduced on an untouched file with a control. 147 of 740 baselined
  functions are exposed.
- **#1112** — `expectErrorLog()` only *suppresses* the harness check; it asserts nothing. A test
  named for a `log_error` kept passing after #1105 deleted that call. 326 call sites, 33 in
  tests whose name claims logging, 2 confirmed vacuous, and **no positive `assertErrorLog`
  helper exists**, which is the root cause. A sweep was dispatched.
- **#1113** — rewritten after retraction (below). What survives: `scripts/` appears **nowhere**
  in `server-tests.yml`, so a trunk push touching only that tree — live code, 121 whitelisted
  endpoints — never triggers the server suite. Same class as #1044/#1069/#1076/#1083/#1094, but
  in a workflow trigger rather than a validator's `SCAN_ROOT`.

---

## Corrections to my own work — read these before trusting anything above

1. **The independent review defeated my tests, and it was right to.** `_count_queries` patches
   `frappe.db.__class__.sql` only. Re-adding the removed audit log through `frappe.cache()`,
   still conditioned on existence, produced a **1.50x** gap — *larger* than the ~1.20x residual
   I had disclosed as acceptable — with every assertion green. My docstring called the pinning
   "exact". Fixed in `4f0560509` with three layers, each with its own control: SQL capture; a
   `frappe.cache` recording proxy (which now reddens on the review's own mutation); and coarse
   min-based latency parity (which reddens at 18.94x on an existence-conditioned `sleep` that
   touches neither SQL nor cache). **The remaining limit is written into the file:** layer 3
   cannot separate a ~1.2x residual from a ~1.5x re-added side effect.
2. **I filed #1110 with an invented figure.** "116 of 740" was never measured. The real number
   is **147**. Corrected in the body and in a comment, because the wrong one had been cited.
3. **I retracted #1111's attribution twice** before getting it right — first "not caused by the
   branch" (justified by a grep that could not see the path it needed to), then "shard
   re-packing" (disproved by a byte-identical class-set diff).
4. **#1113's premise was false in two ways** and I rewrote it: the concurrency fix I proposed as
   new is already in the file, and `workflow_dispatch` exists at line 35. I had read too few
   lines and inferred the rest.
5. **My own change made a pre-existing test dishonest.** `test_validate_payment_id_mismatch_logs_security_event`
   kept passing after #1105 deleted the `log_error` it was named for. Rewritten to assert what
   now holds, verified red when the write returns.
6. **My first two mutation attempts were both too weak**, and I initially expected one to
   redden that correctly did not. Restoring `exists()` alone is not vulnerable — the refusal
   still precedes any load. "Which mutation" is what makes mutation evidence mean anything.

---

## Highest-value open items

- **#1112's sweep** — dispatched, unfinished at handoff. 33 candidate tests, and my
  `log|logs|logged|error_log` naming pattern is a **lower bound** (it misses
  `..._records_...`, `..._audits_...`). The root fix is adding a positive `assertErrorLog`.
  `test_page_payment_success_coverage.py` was excluded from that sweep because I own it on
  #1103 — its `test_validate_disallowed_doctype_logs_security_event` is a confirmed second
  vacuous instance and is **deferred to whoever lands #1103**.
- **#1110** — the shrink gate blocks a legitimate one-of-several deletion. Cheap to hit, and the
  printed remedy does not apply.
- **#1113** — before widening any path filter, check whether the server suite imports `scripts/`
  at all. It may need a different workflow, not a wider trigger.
- **#1097** — re-derived from 224 to **83** by a runtime instrument. One caveat on that number:
  one of the three crediting decorators is `development_only_api`, which **blocks the endpoint
  entirely in production**, so 83 is a floor for production reachability, not the answer.
- **#1105's residual** — the wrong-`payment_id` shape is 1.20x / +74µs, not zero. Stated on the
  issue; bounded by the new rate limit only in the DoS sense, not the sampling sense.

---

## Traps worth knowing

- **CI resolves `frappe`/`erpnext` from a BRANCH at run time.** See above. This is the single
  most expensive thing in this handoff.
- **This bench is 569 ERPNext commits behind CI.** Any local "it passes here" on an accounting
  path is weak evidence; say so when it limits a conclusion.
- **`expectErrorLog()` does not assert.** `assertNoErrorLog()` is the only assertion helper in
  `error_log_guard.py`; there is no positive counterpart, so "a log must be written" is
  currently inexpressible and tests have been written as if it were.
- **A query-count guard is blind to `frappe.cache()`**, and to files, and to the network. If a
  test's claim is about *cost*, counting one channel proves nothing about the others.
- **`flags.ignore_validate = True` genuinely skips `validate()`** — `frappe/model/document.py:1405`,
  before `run_method("validate")`. That is why one same-account Internal Transfer fixture is
  immune to the new ERPNext guard. Immune by a flag, not by correctness.
- **PR runs test `refs/pull/N/merge`.** The merge base is resolved at run time, so a PR run from
  before a develop merge and one from after are different trees.
- **`bench run-tests --module` does not accept repeats** — the last one silently wins, and you
  get a green run of one module while believing you ran several.
- **`gh run view --log` refuses while the run is in progress** ("logs will be available when it
  is complete"), and `--allow-escape-sequences` is **not** a flag on `run view`.
- A red shard can report `Failing: 0, Errors: 1`. Read the `check_new_test_failures.py` block,
  not the failure count.

---

## If you do one thing

Land **#1111**'s fix wherever it needs to go beyond this branch. **It is not branch-specific:**
until it merges, every open PR and every develop push reddens on the same test, because the
cause is an upstream ERPNext release. Everything else here can wait; that cannot.

https://claude.ai/code/session_01TS8PzQDJZXjpgmtzhVJo7K
