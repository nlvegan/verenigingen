# Coverage-pipeline flag backlog — triage (2026-06-21)

Flags surfaced (not fixed) across sweep sets 1–12. Triaged into: **FIX** (live bug),
**DELETE** (dead + broken, verify no callers first), **DECIDE** (needs Foppe — design/
security/not-in-prod-yet).

## FIX — live bugs (TDD, fail-before/pass-after)
1. **bulk_update_payment_history fed SalesInvoice doc instead of `invoice.name`** (set 5)
   `services/billing/bulk_invoice_generation_service.py` `_process_sequential` does
   `invoice_data["invoice"] = invoice` (the doc), then passes it where every other
   caller passes the invoice *name* → coverage/payment-history entries silently dropped
   for ALL bulk-generated invoices. Money-path. Pass `invoice.name`.
2. **get_parallel_status AttributeError** (set 5)
   `services/billing/bulk_invoice_generation_service.py` (~817-844) iterates
   `get_jobs()` expecting `{job_id: dict}` but it returns `{site: [method_str,...]}` →
   `AttributeError` whenever any long-queue job exists. Rewrite the iteration.
3. **department_hierarchy.py:71 missing `f`-prefix** (set 9)
   `dept_name = "{team.team_name} ({team.team_type or 'Team'})"` is a literal →
   `_create_team_departments` creates literally-named departments that never match the
   correctly f-stringed lookup at :162. One-char fix + a test.
4. **retry_with_backoff docstring mismatch** (set 11) — doc claims permanent errors are
   skipped by default, but with retry_on/skip_on both None it retries ALL errors.
   Either fix the docstring OR make the default classify permanent → fail-fast. (Lower risk: doc fix.)

## DELETE — dead + broken (grep-verify ZERO production callers first; check self./parser. receivers per prior lesson)
5. **SEPABatchApprovalService + SEPABatchStateMachine** (set 11)
   `services/payment/sepa_batch_approval_service.py` + `sepa_batch_state_machine.py`.
   Operate on Direct Debit Batch `status` Select with values belonging to the separate
   `approval_status` field. Live workflow is `verenigingen_payments/api/dd_batch_workflow_controller.py`.
   Only re-exported in `services/payment/__init__.py`. Delete pair + the re-export + the
   characterization tests that pin their broken-ness.
6. **bulk_update_mandate_payment_history** (set 10) `utils/optimized_queries.py`
   (OptimizedSEPAQueries) — phantom `last_payment_date` col + `frappe.db.begin()` mid-txn,
   no callers. Delete (+ its characterization test).
7. **Dead Mollie customer helpers** (set 4) `services/customer_handling_service.py`:
   `update_customer_mandate`, `get_customer_mollie_info`, parts of `link_customer_to_mollie`
   reference phantom `mollie_customer_id`/`custom_mollie_dues_mandate`. No callers. Delete
   or repoint to `custom_mollie_customer_id`.
8. **process_application_payment / get_payment_instructions_html** (set 7)
   `services/member/approval/application_payments.py` — no callers; process_application_payment
   also reads the phantom `invoice.membership`. Delete.
9. **national-chapter dead feature** (set 7) `services/chapter/chapter_utils.py:132-161` +
   `utils/performance_cache.py:354` — call `frappe.get_cached_single` (NOT a real Frappe API)
   + phantom `national_chapter` field. Whole feature inert. Fix the API call (→ get_single)
   only if also adding the missing field; else delete the dead branch.

## DECIDE — Foppe call needed (do NOT touch unilaterally)
10. **suspension get_suspension_status_safe MEDIUM gate** (set 3) — `@standard_api(MEMBER_DATA)`
    makes its own guest/ordinary-member branches unreachable. Lower the gate or rework? Security-sensitive.
11. **submit_application eligibility gate ordering** (set 5) — runs before `_handle_existing_member`,
    so Rejected/Pending reapplication is dead through the public endpoint. Intended or reorder?
12. **donation earmarking JE path / process_financial_entries trio** (set 2) — dead via phantom
    Settings account fields. Memory KEEP decision: donation feature "not in prod use yet". Likely DEFER.
13. **ConfigurationManager.load_from_settings stale fields** (set 10) + **settings_utils field drift**
    (set 9: is_e_boekhouden_enabled/is_mollie_enabled ref non-existent fields) — remap to real
    fieldnames (make the feature work) OR delete the dead loaders? Needs intent.
14. **suspend_team_memberships_safe dead docstatus==1 branch** (set 6) — Team Member is a child
    table (always docstatus=0); the cancel branch is dead. Cleanup vs leave.

## STATUS — ALL DECIDED ITEMS DONE 2026-06-21 (LOCAL/UNPUSHED on develop)

### Flag batch 1 (`2ea9e320..7cb522f5`, 10 commits, review APPROVE-WITH-FIXES):
- FIX 1 (bulk payment-history doc-vs-name), FIX 2 (get_parallel_status), FIX 3 (dept f-prefix), FIX 4 (retry docstring) — DONE.
- DELETE 5 (SEPABatch service pair), DELETE 6 (bulk_update_mandate_payment_history + orphan fixture), DELETE 7 (2 Mollie customer helpers) — DONE.

### Flag batch 2 (`8961826e..1bd9c047`, 11 commits, all Foppe-decided item-by-item):
- Item 8 → **DELETED** process_application_payment + get_payment_instructions_html (`8961826e`, −307 LOC; confirmed dead, live path elsewhere).
- Item 9 (national-chapter) → **FIXED** get_cached_single→get_single_value + national_chapter→national_board_chapter (`0a1db3da`,`76535b8a`). NOTE: branch proved REDUNDANT (main board loop already grants national access) — hygiene fix, no behavior change.
- Item 13 (settings drift) → **FIXED/remapped** is_e_boekhouden_enabled/is_mollie_enabled/get_e_boekhouden_api_credentials + ConfigurationManager loader to real fields (`b12f1c08`,`7ba36104`).
- Item 14 (team suspend) → **REAL DATA-LOSS BUG FIXED** (`9b03bac0`): suspend DELETED team rows, unsuspend restore was a no-op → members permanently lost teams. Now soft-disables (is_active=0 + marker) so restore works.
- Item 10 (suspension MEDIUM gate) → **FIXED**: @standard_api(MEDIUM)→@public_api(PUBLIC), body is the real gate; skeptical review CONFIRMED no cross-member leak (`d5f26bcc`,`253ed1c6`).
- Item 11 (submit_application gate) → **FIXED**: lookup moved before gate; Rejected/Pending/Quit-Voluntary can reapply, Active/blocked still blocked, no dup-member (`74d07be9`).
- Item 12 (donation earmarking) → DEFERRED (Foppe earlier KEEP = not-in-prod-yet).

### NEW follow-up flags surfaced during the fixes (NOT done — for a later session):
- **Same national_chapter phantom-field drift in 3 MORE places** (item-9 agent found): `permissions.py:1458` get_termination_permission_query (national block is the SOLE grantor → genuinely broken, national-board members denied a termination permission they should get — real fail-before/pass-after fixable); `api/membership_application_review.py:778`; `report/pending_membership_applications/...py:256`. (`permissions.py:1910` already uses the correct form.)
- **Team-controller assignment-history reconciliation** (item-14 review): toggling child-row is_active via set_value bypasses the parent Team controller's Volunteer Assignment history reconciliation (pre-existing, not worsened by the soft-disable fix).
