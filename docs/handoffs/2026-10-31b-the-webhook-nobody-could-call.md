# 2026-10-31b: the webhook nobody could call

This session started from `2026-10-30b-the-fix-closed-it-only-at-save.md` (PR #1759, still open). It
ran alongside another coordinator session (10-30e, which wrote `2026-10-31-...`). The ledger in
`~/frappe-bench/dispatch/ledger.md` tags this session's lines `2026-10-30d`.

What the maintainer asked for, in order:
1. Read the handoff.
2. Finish #1753, do not repeat the veg11 setup (the maintainer did it), and have an agent investigate
   #1034.
3. Do option A for #1034 and make its guard test actually assert something.
4. Put agents on #1763 and #1764 while waiting.
5. Merge #1762, then "merge them both when green" (#1767 and #1770).
6. Start on #1771.
7. Write this handoff.

## Merged

| PR | Issue | What it did |
|---|---|---|
| #1753 (`1cecc2fd5`) | #1743 | `_get_member_name` reads one row. Chapter bulk-save cap goes 290 → 205 (measured 294 → 204 on test_site_2 with develop merged; CI estimated about 199). |
| #1762 (`3d1e2247a`) | #1034 (Refs) | Guest `per_user` rate-limit counters key on `Guest:<get_client_ip()>`, not one shared `Guest` bucket. A new guard asserts that two anonymous IPs never share a key across all 75 engine-limited guest endpoints, with a floor of ≥ 74 names. |
| #1767 (`e418513ff`) | #1764 | The in-process webhook limiter, and ING `get_request_ip`, use `get_client_ip()`. **This closed an authentication bypass.** On develop, a spoofed Pay.nl IP (leftmost XFF, a bare `X-Real-IP`, or a direct connection) got an **unsigned** ING webhook accepted (HTTP 400 = past auth); the branch returns 401. nginx here sets no `X-Real-IP`. |
| #1770 (`3fb124cbe`) | #1763 | `mollie_subscription_webhook` COR goes from global 30/h to 5000/h, plus a patch for existing rows. **This turned develop red, see below.** |

## Open: PR #1779 (#1771), head `2ffc9bea7`, CI running when this was written

**The defect.** `Mollie Settings.get_subscription_webhook_url()` pointed at
`payment_gateways.mollie_subscription_webhook`, which is `@frappe.whitelist()` **without** `allow_guest`.
Mollie calls anonymously, so every subscription notification, including every recurring dues charge, was
refused at dispatch. Measured: `in frappe.guest_methods` is False, while its same-named twin in
`mollie/api/webhooks.py` is True.

**Adding `allow_guest` would NOT have fixed it.** That handler needs a subscription id, and Mollie's body is
only `id=tr_…`. My brief guessed that the signature check would refuse unsigned calls, and the author showed
that guess was wrong: it only verifies a signature when one is present.

**The fix.** The URL now points at the generic `mollie_payment_webhook?env=…`, which donation subscriptions
already used.

**Test.** One test, `TestSubscriptionWebhookBooksTheDuesPayment`, does a real Guest dispatch with only
`fetch_payment` stubbed. It asserts exactly one Bank Transaction with the deposit from the **payment**
(invoice + 1.37), the right party, and the right member. Mutants that ignore the payment, take the deposit
from the invoice, or use a constant all go red.

**What the generic path does NOT do** (measured by #1779's review; all pre-existing):
- It books an `Unreconciled` Bank Transaction only, with no invoice allocation. The scheduled reconciler
  filters `Pending`, so the invoice stays unpaid until someone reconciles by hand.
- A 2nd delivery of the same `tr_` posts an **unallocated** Payment Entry (#1780).
- Dues refunds and chargebacks never reach reversal (comment on #370).
- The response returns the member id and invoice details to an anonymous caller (#1781).

## Develop is red: #1782, owned by session 10-30e

`test_the_31st_call_through_the_real_decorator_is_not_refused` (#1770) fails in CI shards with
`len(keys) 0 != 1`. It passed in #1770's PR CI, and in my pre-merge check (develop + #1767 + #1770
merged, module run alone, 4/4 on test_site_3). So it is order- or co-tenancy-dependent, not broken when
run alone. The other session has an author on it (test_site_1, `worktrees/issue-1782`). **My pre-merge
check ran the module alone, which is exactly the kind of check that cannot catch this.** A shard-scale
failure can only be caught by CI, and this one was not caught on the PR run either.

## Owed (in order)

1. **#1779:** merge when CI is green, apart from #1782's test (that red already exists on develop). The
   maintainer has not said "merge" for this one.
2. **Before launch, on the same money path:**
   - #1780: retries are not idempotent.
   - #1781: the webhook response leak and existence oracle.
   - #370: dues reversals.
   - Pre-#1779 subscriptions keep the old URL. Drift repair only rewrites it on an amount PATCH. None
     are known live; veg11 has 0, read by the reviewer.
3. **#1034 is still open for option C:** explicit high limits for the provider webhook routes. Each provider
   source IP is still 100/h per endpoint on the fallback. #1766 tracks the loss of any aggregate guest cap,
   and IPv6 being per /128.
4. **Filed this session, not started:**
   - #1761: COR rules and counters keyed on the bare function name. Two measured instances:
     `get_payment_methods`, and the two `mollie_subscription_webhook` functions sharing one global counter.
   - #1768: IPs sent to Pay.nl (mandate consent) and to the bank.
   - #1769: about 16 audit sites record spoofable or proxy IPs.
   - #1772: the ING refusal leaks whether the webhook secret is set.
5. **Handoff PRs still open:** #1736, #1759, #1760 and this one.

## Rulings I made without the maintainer

- **Cap 205** on the chapter bulk save. It sits above the local 204, so this bench passes too; the old 290
  failed locally against 294.
- **#1762:** when `get_client_ip()` cannot tell, Guests share one `Guest:unknown` bucket (documented and
  tested). The security trade-off (IP rotation, no aggregate cap) was accepted and filed as #1766, rather
  than blocking the merge.
- **#1767:** ING no longer reads `X-Real-IP`. Behind a proxy that sets **only** `X-Real-IP`, ING now refuses
  instead of accepting, and writes an Error Log row.
- **#1770:** the limit is 5000, copied from the sibling Mollie rules, not derived from traffic. The patch
  skips rows an operator has tuned.
- **#1779:** the generic payment webhook is the canonical subscription target. I judged this forced by the
  evidence (the old handler could not work), not a product choice.

## What went right, and what nearly didn't

- **I posted a false claim twice.** I wrote "moot" on #1763 and #1771: I said the rate limit didn't matter
  while the URL was unreachable. #1770's reviewer measured otherwise. The guest twin and the registered
  handler share one global counter, so 30 anonymous calls shut the real endpoint. Corrected on both. I had
  reasoned from "the registered one is unreachable" and never asked what *else* writes that key.
- **Every review this session found something the author's own self-review missed:**
  - #1762: the scan floor accepted losing a third of the endpoints.
  - #1767: no control for `X-Real-IP` behind a trusted proxy.
  - #1770: a guard pinned on only one of its three fields.
  - #1779 round 1: there was no booking test at all.
  - #1779 round 2: the deposit equalled the invoice, so where it came from was invisible.

  Each fix round was then reviewed again, and that second review is what caught the last one.
- **The #1034 investigation's census held up.** 56 per_user guest endpoints were counted by AST plus
  runtime, and the per_ip ones served as the control. The handoff's "57" was close, but three Ponto
  callbacks it listed as shared were actually per_ip.
- **Session overlap:** the other coordinator thought this session had ended, and had already opened a
  `docs/handoff-2026-10-31` worktree. Check `ListAgents` and the ledger before picking branch names; that
  is how this collision was avoided.
