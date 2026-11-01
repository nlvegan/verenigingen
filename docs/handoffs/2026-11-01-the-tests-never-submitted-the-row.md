# 2026-11-01: the tests never submitted the row

Session "aanmeldformulier" (2026-10-31 into 11-01). It shared the dispatch ledger and the test-site pool with
sessions `ed` and `2b`. This session worked on the Ponto payment paths: the guest callbacks, the status maps, a
scheduled poll, submitted-row writes and webhook identity. It also merged the previous round's backlog.

**The one lesson to carry forward.** Every Ponto status test across five PRs was green while no really submitted
Ponto Payment Request could change status at all (#1907). Production submits these rows, and every test inserted
them at docstatus 0, which skips `validate_update_after_submit`. Dispatch README rule 22 now covers this.
Rule 21 is the sibling: Frappe rolls back every GET unless `flags.commit` is set, so #1838's token cancel was green
in-process and never persisted (#1883).

## What shipped (merged to develop)

| PR | Closes | What |
|---|---|---|
| #1812 | #1784 | Periodic Donation Agreement workflow no longer stuck in Draft |
| #1818 | #1780 | A repeat Mollie dues delivery is a no-op; a redelivery carrying a refund reaches the reversal booking |
| #1821 | #1738 | Chapter Expense Report lists only claims the caller may list |
| #1823 | #1778 | `has_permission` hooks named `permission_type` receive the real ptype |
| #1824 | #1781 | Mollie payment webhook answers with an ack, not the processing result |
| #1827 | #1804 | ING Checkout and Ponto guest webhooks answer with an ack |
| #1828 | #1761 | Rate-limit counters keyed on the full dotted path |
| #1829 | #1613 | Volunteer queue refusals are logged; sync no longer reports them as queued |
| #1832 | #1686 | Team/chapter bulk role-profile endpoints are admin-only |
| #1851 | #1835, #1841 | One shared Ponto status map per doctype; Executed is final; closed rows never revert; Request gains `Expired` |

Every merge was pinned to its reviewed head (`--match-head-commit`) after `dispatch/premerge.sh` showed every
success marker. #1818 and #1824 both touch the Mollie webhook, so before #1824 merged its 6 Mollie modules plus
#1818's were run green on the merged tree, with no credentials.

## Open PRs and branches, in merge order

| # | PR / branch | Closes | State | Before merging |
|---|---|---|---|---|
| 1 | **#1820** `fix/1768-client-ip-sources` @ b36d71c09 | #1768, #1769 | CI was running at handoff | Merge when green (premerge.sh). The red was an old ING mandate test pinning the untrusted `request_ip`; fixed test-only, with a discriminating control. |
| 2 | **#1927** `fix/1876-no-admin-webhook-fallback` @ 29984d39b | #1876 | CI was running at handoff. Reviewed 3 rounds, last delta coordinator-checked | Merge when green. |
| 3 | **`fix/1907-ponto-allow-on-submit`** @ 5701d695c | #1907, #1848 | **Pushed as a backup, NO PR yet.** Round 3 is not independently reviewed. | (a) independent review of 5701d695c; (b) open PR; (c) merge before #1929 and before #1896. |
| 4 | **#1929** `feat/1885-ponto-status-poll` @ d889f3933 | #1885, #1840 | Reviewed 4 rounds, approved with nits | Merge **after** #1907. First rebase onto develop with #1907, then add a poll test on a really submitted row (rule 22), then implement #1931 (below). Known conflict with #1907 in `ponto_payment_link.py` `refresh_status`: keep #1929's `new_status = map_link_status(...) or self.status` line, then re-add #1907's two `alert_executed_on_cancelled_row` lines. |
| 5 | **#1838** `fix/1815-...` @ f2989cb92 | #1815 | **HELD** | Ponto sandbox signing that the payer declines must confirm Ponto accepts a redirectUri carrying `cancel_token` (and `return_proof`, see #1896) and returns both. |
| 6 | **#1896** `fix/1833-1834-ponto-callback-proof` @ a6f242ae5, stacked on #1838 | #1833, #1834, #1883 (refs #1875) | **HELD** with #1838 | Needs a commit for #1920: the proved cancel must run inside `system_update(doc)` AND `save(ignore_permissions=True)`. See the comment on #1896. Add a callback test on a really submitted row. On merge with #1927: take #1927's `service_user.py`, delete `test_default_still_falls_back_to_administrator_with_its_error_log_row`, and expect a query-count test off by one (`test_known_link_without_a_valid_proof...`), because the user lookup is deliberately uncached. |

## Decisions the maintainer made (also recorded in `dispatch/author_brief_common.md` and on the issues)

- **#1815:** a callback cancels only on `error=access_denied` with a valid signed `cancel_token` minted at signing start.
- **#1835:** Executed is final. Cancelled, Rejected, Failed and Expired move forward to Signed, Authorized or Executed, never back. Ponto `expired` on a Request maps to a new `Expired` option.
- **#1833:** the payment-success token is handed out only against a signed `return_proof` minted at signing start.
- **#1834:** guest callbacks never call Ponto and never fall back to Administrator.
- **#1883:** the proved cancel persists via `flags.commit`, set only on success.
- **#1875 (interim, until frappe/payments#192, see #1878):** only the Ponto return goes to our `/payment_success`. Mollie and ING still go to `/payment-success`.
- **#1876:** `get_service_user` never falls back to Administrator; the webhook user is guaranteed configured. The webhook role gets `cancel` on Bank Transaction. A setting naming Administrator is refused and repaired.
- **#1885:** a scheduled Ponto poll. 401 counts as an outage. Coordinator decisions, accepted: only outage-shaped failures stop a run, classified from the root cause; a non-JSON body counts as an outage.
- **#1840:** the client marker `closed` is never Executed anywhere.
- **#1907:**
  - Option (a): after submit, only system code may change status, `payment_entry`, `sales_invoice` and `debtor_*`, through a guard plus the `ponto_system_update` flag.
  - #1920: system writers skip the permission check narrowly; the webhook role does not get `submit`.
- **#1848:** if Ponto reports a locally cancelled row as Executed, leave the row alone and alert once. A row that already has a live Payment Entry gets no alert.
- **Alerts:** staff alerts NEVER go to the Administrator user, because that account is not in active use. Use `notify_administrators()` with a registered notification key (recipients configurable in Verenigingen Email Configuration).
- **#1921:** not applicable; we receive no webhooks for outgoing payments.
- **#1925:** no Sales Invoice grant; rely on the role profile (Accounts User).
- **#1931:** the poll also checks rows cancelled within its window, only to detect Executed and raise the #1848 alert.
- **#1878:** success and return pages should eventually move to frappe/payments#192 (`/pay`, Payment Session Log). A new maintainer said in frappe/payments#261 that reviewing #192 "is on our list".

## Ponto facts established from the vendor docs (2026-11-01)

These come from the Isabel API Hub documentation. The site is a single-page app, so the text was read from its
content bundle `Webhooks-D9UEVM6X.js`. The quotes and the source are on #1927 and #1929.

- **Webhooks:** "If we do not receive a `200` response within 5 seconds, we will retry the webhook."
  - Ponto does not guarantee delivery order.
  - After "multiple days" without a success, Ponto emails a warning and then **disables the webhook**. Events can be retried by hand in the Developer Portal.
  - So a webhook user missing for days gets our endpoint disabled. The retry interval and attempt count are not documented.
- **Rate limits:** no general request limit is documented for Ponto Connect.
  - Account synchronizations are limited to one every 30 minutes.
  - Unattended account information is limited to 4 per day (PSD2).
  - The poll only GETs payment requests and links, so neither limit applies.

## Open questions only the maintainer can answer

1. **Ponto sandbox check (blocks #1838 and #1896).** Can someone with Ponto sandbox access run one signing and decline it?
   - It must confirm that the redirectUri with `cancel_token` and `return_proof` is accepted.
   - It must confirm both parameters come back unchanged, along with `error=access_denied`.
   - This bench has no Ponto credentials.
2. **#1848 prevention (raised, not answered).** Should a local cancel of a Signed or Authorized Ponto row be refused, or at least warn?
   - Today `on_cancel` contacts Ponto only while the row is Pending or Pending Authorization.
   - A failed Ponto delete is swallowed, and the local cancel goes ahead anyway.
   - So money can still move after a local cancel, and the alert only reports it after the fact.
3. **Monitoring the Ponto webhook.** Ponto disables a webhook after days of failures and only emails whoever owns the Ponto developer account. Is that mailbox watched?
4. **#1875 Mollie and ING return pages.** They still land on the payments app's generic `/payment-success` page. Should they stay there until frappe/payments#192, or get the same interim redirect as Ponto?

## Filed this session (open)

| # | What |
|---|---|
| #1830 | `test_national_board_profiles` intermittent 1213 deadlocks |
| #1831 | chapter.js "Apply Role Profiles to Board" button shows to non-admins |
| #1833 | → #1896 |
| #1834 | → #1896 |
| #1840 | → #1929 |
| #1848 | → #1907 |
| #1875 | `/payment-success` hyphen route is the payments app's page (Ponto fixed in #1896; Mollie and ING remain) |
| #1876 | → #1927 |
| #1878 | Direction: move success pages to frappe/payments#192 |
| #1883 | → #1896 |
| #1885 | → #1929 |
| #1898 | ING `ing_checkout_transaction.py` savepoint name with a hyphen (SQL 1064) |
| #1907 | → #1907 branch |
| #1916 | Comment, Deleted Document and Permission Log residue per test module |
| #1918 | `cancel()` leaves status Pending on a docstatus-2 Ponto row (`on_cancel` writes in memory only) |
| #1919 | `with_retry` swallows `JobTimeoutException` raised mid-HTTP |
| #1920 | system writers on submitted Ponto rows need a narrow `ignore_permissions` (→ #1896 callbacks) |
| #1921 | guest Request Executed cannot book its Payment Entry (not applicable, per maintainer) |
| #1924 | Ponto client wrappers drop `status_code` when re-raising |
| #1925 | webhook role and Sales Invoice read (closed by ruling: rely on the profile) |
| #1926 | Request Executed as Guest fails in `get_party_account` (probable duplicate of #1921) |
| #1931 | poll skips docstatus-2 rows (→ #1929, ruled yes) |

## Coordinator notes: what this session taught

- **Rule 22 (new):** status tests on a submittable doctype must submit the row. See the lesson at the top.
- **Rule 21 (new):** a guest GET that writes must be tested through the real WSGI app with a fresh-connection read.
- **Rule 17 applied again.** Round 2 of the poll stubbed the Ponto client one layer above the wrapper that drops `status_code`. Its outage classifier was therefore always True in production while 34 tests were green. Drive the real client, with only `requests.Session` stubbed.
- **Every Ponto test ran as Administrator.** The permission defects (#1920, #1925, #1926) surfaced only when a reviewer switched to the webhook user. Briefs should require the real identity.
- **I double-booked test_site_3.** I put the #1820 author on it while #1876 still held it. The migrate from #1820's tree revoked #1876's Bank Transaction grant through the `CORE_GRANTS` ledger. Check the ledger's site column before every dispatch, including small fix rounds (rule 1).
- **Watch an author's own deviations.** Twice an author went beyond the brief: 401 as an outage, and non-JSON as data. Both were sensible to question, and one was reversed.

## Final state

- **Agents:** none running. All worktrees of this session are clean.
- **Test sites:** held: none.
- **CI at handoff:** CI was still running on #1820, #1927 and #1929, with no failures so far.
- **veg11:** not redeployed by this session. #1851 adds a Select option, so it needs `bench --site veg11.veganisme.org migrate` before the next deploy check.
