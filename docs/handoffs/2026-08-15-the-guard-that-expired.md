# Handoff — 2026-08-15: the guard that expired

Session goal was "read the handoff, migrate veg11, continue the verification task". The
two open items from the previous session were both confirmed — and confirming them turned
into a regression fix, three new issues, a PR, and two rounds of review that each found a
defect in work I had already called verified.

## Landed / open

| | | state |
|---|---|---|
| veg11 migrate | exit 0, no errors | done |
| PR #346 | `fix/donation-subscription-activation`, 3 commits | **open, blocked by #345** |
| #343 | REGRESSION: recurring donations no longer subscribe | open (PR #346 closes) |
| #344 | donation idempotency routing is degenerate | open, not started |
| #345 | **BLOCKER**: recurring charges are unbookable | open, not started |
| #328 | two new order-dependence instances added | open |
| #341 | two further instances of its own defect shape reported | merged, commented |

## What the verification task found

Both open items from the previous handoff were true, and the second was bigger than stated.

`utils.payment_gateways.mollie_subscription_webhook` cannot be reached by a donation on
**three** independent counts: it is `@frappe.whitelist()` without `allow_guest` while Mollie
posts unauthenticated (measured: 403, with the guest payment webhook as a passing control);
it returns "ignored" unless the payload yields a `sub_` id while Mollie posts `id=tr_...`;
and it gates on a Customer→Member lookup plus an unpaid Sales Invoice, which a donor — who
need not be a member — can never satisfy. The third was Foppe's, and it is the structural
one: it means **consolidating the two webhooks is the wrong fix**, because merging drags
Member+invoice assumptions onto donations.

`PaymentService.create_recurring_first_payment` has no production caller (one call site, in
a `@development_only_api` test entry point).

## The correction that mattered most

I wrote it up as "recurring donations never became a subscription". Foppe: *"in the past I
have been able to create subscriptions using the test API from the /donate page."*

He was right. Mollie's test account still holds five subscriptions from **2025-09-12**
(`sub_czjsX488aw` … `sub_LL9D84YA8o`) whose metadata matches
`_activate_direct_subscription_after_first_payment` exactly — `created_from:
"direct_subscription"` plus `payment_id`/`donation_id`/`original_amount`/`original_interval`,
and `webhookUrl: None` matching a payload that sets none. A sibling subscription from a week
earlier points at `verenigingen.utils.payment_gateways...` — the **pre-restructure** module
path. So this is a regression, the helper is good code, and what it lost was a reachable
caller. Git history begins at the repo's root commit (2025-11-20), after the fact, so the
exact breaking change is inferred, not proven — I said so in the issue.

**Lesson: "I have seen this work" outranks my code reading.** I had traced three blockers
correctly and concluded something false from them, because I never asked whether it had
ever worked.

## The fix, and what two reviews found in it

Activation now runs on the webhook Mollie actually calls, delegating to the existing builder.
Plus `_fetch_payment_from_mollie` was dropping `sequenceType`/`customerId`/`subscriptionId`
from its hand-listed whitelist, leaving three readers permanently dead on *every* donation
payment.

**Review 1 found that my own fix made the worst case worse.** I had activation failures
return an error so Mollie re-delivers. Reproduced: if Mollie commits the create and the
response is lost, nothing is recorded locally, so the retry creates a *second* subscription —
donor charged twice per period, forever, one of the two invisible. Fixed with a deterministic
`Idempotency-Key`.

**Review 2 (docs-vs-tests) found the key does not do what I assumed.** Mollie caches keys for
**1 hour**; its webhook retry ladder runs **26** (T+0, 1m, 3m, 7m, 15m, 31m, 1h, 2h, 4h, 26h).
Attempts 8–10 arrive unprotected — the exact ones a prolonged failure reaches. My comment
saying "a re-delivery cannot double-charge the donor" was false for them.

The durable fix asks Mollie what already exists: subscriptions carry `metadata.payment_id`,
which never expires — the same fingerprint that proved the regression. The key stays as the
fast path, so the row lock could be dropped and the transaction is no longer held across a
gateway round-trip.

Six of seven Mollie claims the tests encode were confirmed verbatim against the docs. Only
the retention window contradicted us — and everything rested on it.

## Measured against the Mollie API (not inferred)

Each with a control that discriminates:

- a `sequenceType:"first"` payment carries **no** `subscriptionId`
- `startDate` defaults to today, but the first charge falls one interval **later** — control:
  an explicit future `startDate` makes `nextPaymentDate` equal it. So omitting it does not
  double-charge on signup day
- same `Idempotency-Key` + identical payload → the **same** subscription and only one;
  different keys → two. Mollie 400s a reused key with **different parameters** or on a
  **different URL**, and keys persist across runs (both learned by getting 400s)
- mandates can be created directly for IBAN/PayPal only; cards need a first payment

That last one matters strategically: `CompletePaymentService._provision_and_create_subscription`
**already implements** mandate-first subscription creation. The only thing between /donate and
a synchronous, webhook-free recurring donation is that the form has no IBAN field. Recorded as
option B on #345.

## The bug the new tests found on their first run

The `form_data` orphan scan reported nine candidates. Checking rather than ratcheting them:

```python
"donor_email": form_data.get("email", ""),
"donor_name": f"{form_data.get('first_name','')} {form_data.get('last_name','')}".strip(),
```

`collectAllStepData()` collects only `input.name` attributes; the form posts
`donor_email`/`donor_name`. `donate.py:149-150` puts `first_name`/`last_name` in the **page
context** to prefill fields — never reaching `form_data`. So **every recurring donation created
its Mollie customer with an empty email and an empty name.** Corroborated by a nameless
customer in the test account (`cst_FUCWPh4KVn`, both `None`) that I had listed hours earlier
without understanding.

Same shape as #341, same file, one function later. The check written for that shape found it
immediately.

## What CI caught that local runs did not

Two shards red, six tests: `_Subscriptions.create() got an unexpected keyword argument
'idempotency_key'`. The stubs were already narrower than the real SDK signature; my change
merely exposed it.

**Why my local run missed it:** my first control matrix covered 12 modules including the two
that fail here. Rebuilding it after the review fixes, I trimmed to 10 — dropping exactly those
two. *Narrowing a control because it is slow is how a control stops being one.*

The same class then recurred immediately in a form the new check cannot see: a lambda stubbing
one of our own methods. Filed as item D on #344.

## Traps worth keeping

- **The exception message can be buried.** A shard log put the real cause under a
  4,000-character hooks dump. My first reproduction guessed a producer from a bank *name* in
  the traceback, came back clean, and was **inconclusive, not exonerating**. Extract the
  exception first, then hypothesise.
- **A scripted string replace silently no-ops** when black has reformatted the target onto one
  line. Cost a confusing red run where the fix looked wrong but the wiring was.
- **Running a different `black` than pre-commit's** reformats pre-existing lines and the
  commit then fails with "Stashed changes conflicted with hook auto-fixes". Take the hook's
  version.
- **A fake can be more forgiving than reality in the dimension that matters.** Twice: the
  payment fake was a plain object where a real Mollie `Payment` subclasses `dict` (so tests
  exercised the branch production never takes), and the subscriptions fake's key cache never
  expired (so it reported the guard as working when it was not).
- **A control that punishes the fix is a bad control** — one added test demanded set equality
  where a subset was correct, and would have failed the next legitimate improvement.

## State

- Worktree `wt-donsub` on `fix/donation-subscription-activation` @ `8a8566ac`, pushed.
- Verification: 12 modules, branch vs untouched `develop`, all PASS / all PASS. Every new
  assertion mutation-proven. `error_swallow_validator` exit 0 without a pragma or a baseline
  bump; `black` clean.
- CI at the time of the last push had 9/12 shards green; shards 9 and 11 are fixed by
  `d79f13e9` and shard 3 belongs to #328.
- **Do not merge #346 before #345.** Before this fix a recurring donor was under-charged once;
  after it they are charged every period into an unbooked void. That is a worse accounting
  position than the bug.
