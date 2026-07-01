# Handoff — eBoekhouden `rest_full_migration` coverage sweep (2026-06-17)

Coverage push on the single biggest gap: `verenigingen/e_boekhouden/utils/eboekhouden_rest_full_migration.py`
(4230 LOC, ~36% covered, the heavy document-creation functions were untested).

## Result: 5 commits, LOCAL/UNPUSHED on develop (interleaved with a concurrent session's commits)

```
c9e171e9 test(eboekhouden): REST invoice-creation path (19 tests)            [cluster A / probe]
15275849 fix(eboekhouden): correct inverted memorial debit/credit + 31 tests  [cluster B + BUG]
69f7673b test(eboekhouden): REST payment & money-transfer path (21 tests)     [cluster C]
039e0506 fix(eboekhouden): stock opening-balance temp account idempotent + 29 [cluster D + BUG]
87419e33 fix(eboekhouden): generic party get_meaningful_description dict + 36  [cluster E + BUG]
```
~136 new real-integration tests. Method: a probe agent validated the setUp recipe, then 4 parallel
agents (sites 2-5) wrote one cluster each; I reviewed, fixed the bugs they surfaced, and committed
per-cluster. Two cluster agents (D, E) hit the session limit mid-run; I finished both.

## 3 REAL production bugs found + fixed
1. **Memorial debit/credit inversion** (`15275849`) — `_get_memorial_booking_amounts` fetched eBoekhouden
   ledger "categories" via the API but never used them; its only live effect was that
   `EBoekhoudenAPI(settings)` raises without a token, dropping into an except-fallback that used the
   OPPOSITE debit/credit convention from the main branch. So memorial bookings imported WITHOUT API
   credentials (CI, or a transient token failure mid-import on prod) posted each leg on the wrong ledger
   side. Removed the dead API call; single verified convention everywhere (positive amount → credit row,
   debit main; mutation 1334). **Production output unchanged** (it ran the main branch); only
   credential-less/transient-failure paths now match it. Foppe chose "also remove the dead API call".
2. **Stock temp account not idempotent** (`039e0506`) — `_get_or_create_stock_temporary_account` looked
   the account up by `f"Stock Opening Balance (Temporary) - {company}"` (full name) while ERPNext
   autonames `"<name> - <abbr>"`. The existence check never matched the account it creates, so every
   re-call hit the create path, the duplicate insert() threw, and it silently fell back to the wrong
   (temp-diff) account → stock opening balances could land in the wrong account on re-import. Fixed to
   look up by `(account_name, company)` like the sibling `_get_or_create_temporary_diff_account` does.
3. **Generic party creation always errored** (`87419e33`) — `_get_or_create_generic_party` passed the raw
   description STRING to `get_meaningful_description`, which expects a mutation DICT (`mutation.get(...)`).
   Every non-empty description threw AttributeError → except → returned `"Default Customer"`/`"Default
   Supplier"` without creating a named party. Fixed to pass `{"description": description}`. **Latent**:
   the generic-party trio has no live callers (`_get_or_create_customer/_supplier` resolve via the party
   resolver), but the path is now correct if revived.

## Dead-code defects DOCUMENTED (not fixed — zero non-test callers, flagged for a removal decision)
- `_process_money_transfer_mutation` sets `voucher_type="Bank Entry"` but never sets `cheque_no`/`date`,
  so `je.submit()` always raises. Pinned by a test that turns red when fixed. (`69f7673b`)
- `_get_appropriate_income/expense_account` can only succeed via the no-mapping fallback because the
  Payment Mapping DocType's `account_type` Select offers only Bank/Cash. (`69f7673b`)

## Reusable setUp recipe (for the next cluster / re-runs)
- `EnhancedTestCase` subclass, `@classmethod` setUp, company created once + reused (EUR, NL, unique abbr).
- Accounts under auto-made root groups; set company `default_receivable/payable`. Cost center root+leaf.
- `E-Boekhouden Ledger Mapping` rows with **`ledger_id == ledger_code`** (line resolution is a two-hop
  ledgerId→code→account keyed on ledger_id, so id==code lands both hops on your account).
- Parties pre-created with `eboekhouden_relation_code == relationId` (resolution tries the API, fails
  gracefully, then matches on relation code — no API needed).
- Fiscal Year: append your company to a FY covering today() (erpnext global setup binds the current FY
  to `_Test Company`, else submit fails "not in any active Fiscal Year").
- **Omit `vatCode`/`BTWCode`**: `BTW_CODE_MAP` points tax codes at hard-coded account names on a
  different test company → cross-company-account guard. Drop it; grand_total == net_total.
- Mutation shape: `{"id","type","date":nowdate(),"amount","relationId","invoiceNumber","description",
  "ledgerId" (top-level main account),"Regels":[{"ledgerId","amount","quantity","description"}]}`.
  Types: 0 OB, 1/2 invoices, 3/4 payments (Payment Entry), 5/6 money (JE via PaymentProcessor),
  7 memorial. For `_process_single_mutation`, stub `EBoekhoudenRESTIterator().fetch_mutation_detail`.
- test-quality-enforcer: `insert(ignore_permissions=True)` must live in a helper named `_make_`/`_ensure_`/
  `_setup_` — NOT in a test body.

## Still OPEN
- **`test_opening_balance_import.py::test_force_deletes_existing_then_reimports` is `skipTest`-flagged.**
  In the harness, `_import_opening_balances(force=True)` reports success but the seeded OPENING_BALANCE JE
  survives and no new JE is produced from the mocked payload. Could be a real force-delete/re-import
  defect OR a test-state interaction — needs a reliable standalone repro to decide. (The force-delete
  branch and existence query read fine on inspection; the mocked-payload → new-JE build is the murky part.)
- The orchestration functions remain largely uncovered (API-heavy): `start_full_rest_import`,
  `_import_rest_mutations_batch_enhanced`, `_cache_all_mutations`, `_process_mutation_with_coordinator`,
  export/debug whitelist endpoints. These need the eBoekhouden REST iterator/API boundary stubbed.

## Env note
A concurrent "Live API coverage sweep" session committed to develop throughout (volunteer/anbi/dues/
schedule fixes). All eBoekhouden commits used explicit pathspecs + post-commit `git log -1` HEAD checks.
