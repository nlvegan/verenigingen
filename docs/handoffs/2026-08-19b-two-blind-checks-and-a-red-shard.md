# Handoff — 2026-08-19b: two blind checks covering each other, and a red shard that was not the code

Continued #370 (Mollie reversal booking) through two skeptical reviews, and followed a red CI
shard far enough to find it was never about the branch. The through-line: **"it books once" and
"it books correctly" are different claims, and I shipped the first while believing the second.**
Both reviews returned REQUEST CHANGES; both were right.

## State

| | |
|---|---|
| `develop` | `4cc0c502` (12/12 green — the baseline all three branches were measured against) |
| **#379** `fix/mollie-reversal-booking` | `1e11080f`, draft, 9 commits past the first review |
| **#384** `fix/secure-operation-results-unchecked` | `026e20b1`, ready, review round applied |
| **#387** `fix/eboekhouden-test-owns-its-company` | `2a6990c2`, ready, small and self-contained |
| Issues filed | **#381**, **#383**, **#385**, **#386**, **#388** |
| Issue rescoped | **#382** (split; its defect half became #385) |
| CLAUDE.md | rule 5 added to Verification discipline |

## The reversal work (#379)

Round one of the review closed seven of nine findings. Round two found the two that mattered.

**C1 — I applied the artefact-dispatch fix to one of the two routes.** `process_reversal_webhook`
learned to mirror the forward artefact; `_process_pending_refunds` — *the route the payment webhook
actually takes* — got idempotency only, and still booked Bank Transaction + Journal Entry
unconditionally. For a donation forward-booked as a Payment Entry that is exactly the posting my own
commit message said must not happen: income debited that the payment never recognised, receivable
left cleared. Reproduced as `(0, 1) != (1, 0)`.

> **`find_booked_reversal` makes the two routes book *once*. Only dispatch makes them book
> *correctly*.** I had conflated them, marked the finding closed, and moved on.

Fixed by delegating to the one booker rather than repeating it, which also deleted the duplicated
config/party/currency resolution.

**C2 — the cleanup did not do what its code, docstring and commit message all said.**
`_discard_unposted_journal_entry` cancels then deletes. In the case it is most likely to meet — a
bad account — `cancel()` itself raises, because `on_cancel` re-posts the reversal GL row into the
same validation. So the delete never runs. Measured: submit raises, `docstatus=1` persists, cancel
raises, `docstatus=2` persists anyway, row survives. The safety property held **by accident**, and
the Error Log claimed the entry "still claims its reversal key" when `docstatus=2` means it does
not — a false alarm on the most likely path. Now cancel-only, with the outcome **re-read** rather
than assumed.

Also from that round: the new idempotency guard had removed the only self-heal for a missing
payment-history row; a booking failure went out as **HTTP 200**, so Mollie never redelivered, which
undercut the entire point of freeing the key on failure; and
`BankTransactionCreator._check_existing_by_reference` did not filter `docstatus`, so a cancelled
Bank Transaction was adopted by the next delivery and the Journal Entry then reconciled against a
cancelled document — swallowed.

Still open, recorded in the PR body rather than left as a silent gap: **concurrency** (no lock or
unique index on the reversal key, so "books once" holds under redelivery but not under genuine
concurrency) and a **third booking route** in `refund_handler.py` — latent, no production caller,
already #376. The **dues booker** and the **C4 reservation** remain unbuilt.

## The docstatus discovery, and what it cost to get right

An agent investigation refuted my framing entirely. I had recorded "a group-account JE submits fine
under `bench run-tests` but is rejected in plain bench". Both contexts reject it identically; what
differs is who catches the `ValidationError`.

**`Document.save()` runs `db_update()` before `run_post_save_methods()`, and `on_submit` is what
posts to the ledger.** So a submit that raises has already written `docstatus=1`. ERPNext validates
each GL row in `GLEntry.on_update` — *after* inserting it — so the ledger can be left one-sided.
`secure_document_operation` catches and does not roll back.

That turned a dead end into a real defect: `_create_refund_journal_entry` returned the JE name on a
failed submit, so a reversal that never reached the ledger was reported as a completed refund — and
because `find_booked_reversal` counts `docstatus != 2`, the unposted entry claimed the key and every
redelivery answered "already processed". **Reported done, permanently, having never posted.**

Two things follow, both filed: `docstatus == 1` is not evidence a Journal Entry posted (**#382** —
117 such assertions across 52 ledger-touching test files, of which **3** check a GL row at all), and
`secure_document_operation`'s `success=False` cannot tell a caller that a failed *submit* already
persisted state (**#385**). The reliable failure injection is an **unbalanced JE** — the only
submit-time failure leaving no ledger debris.

## The validator (#384), and its own hole

`secure_document_operation` does not raise for an ordinary failed write; it returns `success=False`.
Every instance of the resulting defect had exception handling wrapped around it that could never
fire. That is why it needs a validator rather than a review habit: **it reads as handled.**

A sweep of all 206 non-test call sites found exactly three violations, all fixed here — so the rule
ships with **no baseline**. The three: an access **revocation** that failed silently (the user kept
the role profile while the caller reported it removed — and the caller's own comment records this
same path being fixed once before for the same class of lie); a manual-review escalation whose flag
write was discarded, so the schedule retried forever with nobody told; and a best-effort cleanup
whose log could never fire.

Its own review then found the hole in the thing it was for: **the opt-out pragma was unpoliced**, so
`# secure-op-ok: i just do not feel like it` silenced a finding — on a no-baseline rule, the only way
it could quietly die. Plus a false positive on `result = ...; return result`, and three misses, of
which `if secure_document_operation(...)` is the worst: `SecureOperationResult` defines no
`__bool__`, so that branch is **unconditionally true**. It reads as a check and is not one.

Fittingly, the commit fixing all that was **blocked by the sibling validator** for an opt-out reason
I had invented.

## The red shard, and why it took so long

#379's shard 3 failed with 35 `setUpClass` errors. It was not the branch's code — zero hits for any
of the nine error strings it introduces, none of the failing modules in its diff, and `develop` at
the same base green. Following it properly found a real bug and three traps.

**The real bug (#386, fixed in #387):** `TEST-Payment-Integration-Company` had two owners.
`sepa_test_company` builds it inside `suspend_insert_capture()` and then verifies it;
`TestPaymentProcessingIntegration._ensure_test_company` built the same name with a plain `insert()`
and no suspension anywhere in the file. **Nothing deletes the chart of accounts on purpose** — the
rows were never marked as fixture data, so the harness's own drain removed them. The "leaks" in the
report are the deletions that *failed*; the ones that succeed are the damage. `get_eur_test_company()`
then refuses the stub, which is the 35 errors — the refusal working as designed. Its sibling class in
the same file already uses its own company, which is what makes it look accidental.

I described this to Foppe as "an e-boekhouden test wipes the chart of accounts". That is wrong and
points at the wrong fix; corrected on #379.

**A hypothesis I raised and refuted**, recorded so nobody re-runs it: I suspected my own
`@shared_fixture` marking on `ensure_mollie_reversal_accounts` was leaving an account under the
asset tree. It is not — that helper targets `Verenigingen Settings.company`, not the SEPA company,
and its account does not survive its own module's run. Checked by deleting the fixture first.

## Traps that cost real time

- **A shard that "fails" may never have run a test.** My first control run came back with four
  shards cancelled at *exactly* 60 minutes — 58 minutes of silence after an `apt-get` fetch, **zero**
  test lines in the log. I nearly read "8 pass, 4 cancelled" as a result. Job **duration** is the
  tell. Second occurrence of this trap in two sessions.
- **I nearly reported a false regression on my own branch.** A module gave `FAILED (errors=1)` on the
  branch and `OK` on develop — damning, and entirely my doing: I ran the branch immediately after
  perturbing the site, and develop on the settled site. Same state, both green. **Run the control on
  the same state, and re-run before writing it up.**
- **A savepoint cannot wrap code that commits.** Wrapping the BT+JE pair in
  `savepoint(catch=Exception)` made every reversal fail with `(1305, 'SAVEPOINT ... does not exist')`
  — `_reconcile_bank_transaction` commits, a commit destroys every open savepoint, and the release
  error then *replaces* the real one. Same trap CLAUDE.md records for deadlocks, reached another way.
- **My own "remove the unused import" edit matched the wrong one of two identical blocks** and broke
  a live method. `ruff` did not catch it; a test I had written an hour earlier did.

## What I would tell the next session

Last session's lesson was that the *premises* were unverified. This one is narrower and sharper:
**I closed a finding because I had fixed the thing it named, in the place I happened to be looking.**
The review found the same defect one function away, on the route that actually runs in production.
When a finding is about a *class* of mistake — a lookup that sees one doctype, a check that reads one
route — closing it means grepping for every instance, not fixing the instance in front of you. Two
blind checks covering each other's blind spots is the shape to look for; it appeared three times in
this branch alone.

And on CI: **a red shard here currently carries almost no information until triaged.** Of the failing
shards examined today, one was `apt-get` hanging, one was pre-existing, and the rest were
co-tenancy — three branches off one green base produced three *unrelated* failure sets (**#388**).
Triage before diagnosing, and check duration before anything else.

## Where to pick up

1. **Land #387** — small, self-contained, removes the most destructive landmine (35 tests). Do not
   stack #379 on it: this repo gates the suite on `base=develop`, so a stacked PR gets pylint-only
   green, which is the decorative-tick failure from #325.
2. **Re-run #379's shard** on updated develop once #387 lands. That is the only real signal available.
3. **#379's remaining work**: the dues reversal booker, the C4 insert-first reservation, then
   concurrency (#376 for the third route).
4. **#381** is the same failed-submit-reported-as-success defect on the *forward* donation path, and
   additionally makes such a donation impossible to reverse.
