# Membership Application as Its Own Record: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo, dispatched authors also follow `~/frappe-bench/dispatch/author_brief_common.md` (red → fix → green, class sweep, self-review before push).

**Goal:** A membership application is stored as its own record and touches no Member until a reviewer approves it, so an anonymous submission can no longer overwrite an existing member's name or IBAN (#1740).

**Architecture:** `Membership Application Submission` (MAS), which `/word-lid` already uses to hold submissions until email confirmation, becomes the single application record for both forms. Confirming the email moves a MAS to `Pending Review`, and nothing else happens. Approval *materialises* the Member: it creates the Member or applies the application to the existing one under explicit field rules, then hands over to the existing locked approval core, which is unchanged. Rejection writes only to the MAS. Review surfaces and chapter-board permissions key on the MAS's `chapter` instead of a Pending Chapter Member row.

**Tech Stack:** Frappe v16 / ERPNext, Python services under `verenigingen/services/member/`, desk JS, `EnhancedTestCase` tests.

**Spec:** issue #1765 together with its maintainer-answers comment (2026-10-30). Background is in #1740.

## Global Constraints

- **One record for both forms.** The old `apply_for_membership` page and `/word-lid` both write a MAS. Both require email confirmation before review.
- **A Member is created only on approval.** This includes brand-new applicants. Submit and confirm create no Member, Address, Customer, Contact, Chapter Member row, Volunteer or `chapter_membership_history` row.
- **Review shows what would change.** For an existing member, list every field where the application differs from the Member.
- **No applicant-supplied field is excluded in principle.** An absent or blank field never clears an existing value. The application never writes `email`, `status`, `application_status`, the linked `user`/`customer`, `member_id`, `payment_reference`, or a fee override that staff set (#1730's `_fee_came_from_application` rule).
- **IBAN history is kept** through the normal `Member.save()` path (`payment_mixin.validate_bank_details` → `track_iban_change`). Never write the IBAN with `db_set`/`set_value`.
- **Retention:** Unconfirmed, Expired, Rejected and Superseded applications are deleted 30 days after their last change. Approved applications are kept.
- **No data migration.** Existing Pending-as-Member rows are test data (maintainer, 2026-10-30).
- **Guest responses are uniform.** Submit returns the same response, `message_log` and Error Log rows whether or not the email belongs to a Member. Only the email that goes out differs (the `short_application.py` module contract).
- **Repo rules apply:** no bare `frappe.db.commit()`; `frappe.log_error(title=..., message=...)`; `get_harness_logger` in tests; run tests on test_site_1..5 only; existence-oracle refusals must match on every channel (CLAUDE.md checklist).
- **Sequencing:** start after the #1741/#1737 PR merges. It edits `_ensure_dues_schedule_exists` and the `_reset_application_dues_choice` docstring, both of which this plan touches.

## Review Focus

1. **Two confirmed applications for the same email.** Only the newest is reviewable; the older one becomes `Superseded`, and approving it is refused. (Task 2)
2. **The member's state changes between confirm and approval** (they become Active, are terminated involuntarily, or are banned). Approval re-runs `_handle_existing_member` and refuses. (Task 4)
3. **A blank or absent field in the application** (IBAN, phone, birth date) leaves the Member's value intact, and the change preview does not list it as a change. (Tasks 4, 6)
4. **Approval fails part-way.** No Member, Address, Customer or Contact survives, and the MAS stays `Pending Review`. (Task 4)
5. **A board member of chapter A probes chapter B's application, or an unknown name.** The refusal is identical for both, on every channel. (Task 3)

---

## File Structure

| File | Responsibility |
|---|---|
| `verenigingen/verenigingen/doctype/membership_application_submission/membership_application_submission.json` | New fields and statuses (Task 1) |
| `.../membership_application_submission.py` | Status transitions and `supersede_older()` (Tasks 1, 2) |
| **Create** `verenigingen/services/member/application/application_record.py` | Staging and confirmation shared by both forms (Task 2) |
| **Create** `verenigingen/services/member/application/application_materialiser.py` | Field rules, change preview, and creating or updating the Member on approval (Tasks 4, 6) |
| `verenigingen/api/membership_application.py` | `submit_application` stages instead of writing a Member (Task 2) |
| `verenigingen/api/short_application.py`, `services/member/application/short_application_confirm.py` | Delegate to `application_record` (Task 2) |
| `verenigingen/api/membership_application_review.py` | `approve_application` / `reject_application` by MAS name (Tasks 4, 5) |
| `verenigingen/services/chapter/chapter_security.py`, `verenigingen/permissions.py`, `hooks/permissions.py` | MAS permissions by chapter (Task 3) |
| Review page, pending report, chapter dashboard, `member.js` | Read the MAS (Task 7) |
| `templates/pages/application_status.py`, `doctype/membership_dues_schedule/membership_dues_schedule.py`, the purge job | Status page, template guard, retention (Task 8) |

---

### Task 1: Extend the MAS doctype into the application record

**Files:**
- Modify: `membership_application_submission.json`, `membership_application_submission.py`
- Test: Create `verenigingen/tests/backend/unit/doctype/test_membership_application_submission.py`

**Interfaces:**
- Produces:
  - `status` Select `Unconfirmed\nPending Review\nApproved\nRejected\nSuperseded\nExpired`. Default `Unconfirmed`. `Confirmed` is removed; no migration (test data).
  - New fields:
    - `source` Select `Short Form\nFull Form`
    - `applicant_name` Data, in list view
    - `membership_type` Link Membership Type
    - `chapter` Link Chapter (the suggested chapter, resolved at confirm)
    - `application_id` Data, unique
    - `reviewed_by` Link User
    - `review_date` Datetime
    - `review_notes` Small Text
    - `rejection_category` Data
    - `superseded_by` Link MAS
  - `door` stops being required, because the full form has no door.
  - Permissions: read for System Manager, Verenigingen Administrator and Chapter Board Member; write for nobody; changes go through the service.
  - `class MembershipApplicationSubmission(Document)` gains `def set_status(self, status: str) -> None`. It allows only these transitions:
    - Unconfirmed → Pending Review / Expired
    - Pending Review → Approved / Rejected / Superseded
  - Anything else throws `frappe.ValidationError`.

- [ ] **Step 1: Write the failing tests**
  - `test_allowed_transitions_persist`: each allowed pair, `set_status` then `frappe.db.get_value(...,"status")` equals the target.
  - `test_forbidden_transition_raises`: `Approved → Pending Review`, `Rejected → Approved` and `Unconfirmed → Approved` each raise `frappe.ValidationError`.
  - `test_full_form_row_needs_no_door`: insert with `source="Full Form"` and no `door` succeeds.
- [ ] **Step 2: Run them and see them fail.**
  `cd ~/frappe-bench && PYTHONPATH=<wt> bench --site test_site_1 run-tests --app verenigingen --module verenigingen.tests.backend.unit.doctype.test_membership_application_submission`
  Expected: FAIL. `set_status` does not exist, and `door` is mandatory.
- [ ] **Step 3: Edit the JSON line by line** (never `json.dumps` the file). Implement `set_status`, then `bench --site test_site_1 migrate`.
- [ ] **Step 4: Run them and see them pass.** Also run `test_short_application_cleanup`; it uses `Confirmed`, so update it to `Pending Review` and state that in the commit.
- [ ] **Step 5: Commit.** `feat(application): Membership Application Submission becomes the application record (#1765)`

### Task 2: Both forms stage; confirming creates no Member

**Files:**
- Create: `verenigingen/services/member/application/application_record.py`
- Modify: `api/membership_application.py` (`submit_application` :427-624), `api/short_application.py` (`_route`), `short_application_confirm.py` (`confirm_submission`, `_write_member` and the functions below it), `public/js/membership_application.js` (success screen :1483-1531, :4246-4265)
- Test: Create `verenigingen/tests/backend/unit/services/test_application_record.py`, and update `test_short_application_confirm.py` and `test_short_application_submit.py`

**Interfaces:**
- Consumes: Task 1's `set_status`.
- Produces:
  - `stage_application(source: str, email: str, payload: dict, door: str | None = None) -> None`
    - Applies the daily mail cap and the existing-member routing.
    - Then either inserts an `Unconfirmed` MAS and sends the confirmation mail, or sends the "already member" mail.
  - `confirm_application(name: str, token: str) -> dict`
    - Covers the existing refusal checks (POST only, token, row lock, 7-day expiry, template still valid, member still allowed to reapply).
    - Sets `applicant_name`, `membership_type` and `chapter`, then moves the MAS to `Pending Review` and calls `supersede_older(email, keep=name)`.
    - Creates nothing else.
  - `supersede_older(email: str, keep: str) -> int`: every other `Pending Review` MAS with this email becomes `Superseded`, with `superseded_by=keep`.
  - **The payload is stored in the helper shape.** That is the output of `to_helper_payload` for the short form, and the parsed `submit_application` data for the full form. Task 4 then reads one shape.
- `submit_application` keeps its validation (required fields, eligibility, amount). Then it calls `stage_application("Full Form", ...)` and returns `{"status": "confirmation_sent"}` with the message "Check your email to confirm your application." Every other response field is removed, including `member_record` and `status_token`.
- The confirm route stays `/word-lid/bevestig`, so the full form's mail links there too.

- [ ] **Step 1: Write the failing tests** (through the real endpoints)
  - `test_full_form_submit_creates_no_member`: as Guest, call `submit_application` with a new email. Assert `frappe.db.count("Member", {"email": e}) == 0`, `count("Address", ...) == 0`, `count("Customer", {"customer_name": <name>}) == 0`, and exactly one MAS with `status == "Unconfirmed"` and `source == "Full Form"`.
  - `test_full_form_response_identical_for_existing_member`: compare the response dict, `frappe.local.message_log` and the count of new Error Log rows for an unknown email and for an Active member's email. All equal.
  - `test_confirm_creates_no_member`: confirm a short-form submission for a new email. MAS `status == "Pending Review"`, `chapter` is set, and there are 0 Members, 0 Chapter Member rows and 0 Volunteers for that email.
  - `test_reapplication_confirm_leaves_member_untouched`:
    - Setup: a voluntarily-Quit member (through the real termination flow) with IBAN `NL91ABNA0417164300`.
    - Confirm an application carrying another IBAN and name.
    - `Member.iban`, `last_name`, `status` and `modified` are unchanged.
  - `test_second_confirm_supersedes_first`: confirm two applications for the same email. The first is `Superseded` with `superseded_by` = the second; the second is `Pending Review`.
- [ ] **Step 2: Run them and see them fail.** Today a Member is created, or overwritten, at submit or confirm.
- [ ] **Step 3: Implement `application_record.py`.**
  - Move `_route` and the mail helpers out of `short_application.py`.
  - Move the confirm checks out of `short_application_confirm.py`.
  - Delete `_create_member_with_savepoint`, `_write_member`, `_unasked_member_values`, `_link_chapter`, `_set_answers` and `_set_dues_fields`. Their behaviour moves to Task 4.
  - Wire `submit_application`.
  - Change the old JS success screen to show the "check your email" message.
- [ ] **Step 4: Run them and see them pass.** Then run the whole `/word-lid` and submit suites listed in the census (`test_short_application_*`, `test_submit_application_chapter_steps`, `test_membership_application_api`) and fix or rewrite any test that asserted a Member at submit. Each rewrite says in the commit which old behaviour it encoded.
- [ ] **Step 5: Class sweep.** Find the other callers of `submit_application`: `api/volunteer_application.py:316-325` and `debug_api.py:98`. Route the volunteer one through `stage_application`. Check whether the debug one is reachable, and if not, delete it with evidence. Then commit `feat(application): both forms stage an application; confirmation creates no Member (#1765, #1740)`.

### Task 3: Board members review applications by the MAS's chapter

**Files:**
- Modify:
  - `services/chapter/chapter_security.py`: `can_user_manage_application` :82, `filter_applications_by_permission` :149, `validate_chapter_permission_or_throw` :201
  - `verenigingen/permissions.py`: add MAS handlers
  - `hooks/permissions.py`: register them
- Test: Create `verenigingen/tests/member/test_application_record_permissions.py`

**Interfaces:**
- Produces:
  - `can_user_manage_application(application_name: str, user=None) -> bool`. True for `Roles.ADMIN_ROLES`; otherwise true when the user holds an active board seat in `MAS.chapter`. A MAS with no chapter can be reviewed by admins only.
  - `validate_chapter_permission_or_throw(application_name, action, user=None)`. It keeps the same refusal message for an unknown name and a foreign one.
  - `has_application_permission(doc, ptype, user)` and `get_application_permission_query(user)`, registered under `"Membership Application Submission"`.
- Remove the `include_pending` clause from `_is_member_in_chapters` (`permissions.py:376`). No Pending Chapter Member row is created any more, so the clause has nothing to match.

- [ ] **Step 1: Write the failing tests** (the caller has no blanket doctype access, per the CLAUDE.md oracle checklist)
  - `test_board_member_sees_only_own_chapter_applications`: a `frappe.get_list("Membership Application Submission")` by a chapter-A board member returns the A application and not the B one.
  - `test_foreign_and_unknown_refused_identically`: `approve_application` on B's MAS and on `"nonexistent-xyz"`. Exception type, message, `message_log` length and content, and the Error Log row delta are all equal.
  - `test_unassigned_application_admin_only`: a MAS with `chapter=None` is refused to a board member and allowed to a Verenigingen Administrator.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Grep for every caller of the three `chapter_security` functions and switch each to the application name.
- [ ] **Step 4: Run them and see them pass.** Then run `test_member_approval_permissions` and `test_member_list_permission_matches_doc_permission`.
- [ ] **Step 5: Commit.** `feat(application): chapter boards review applications by the application's chapter (#1765)`

### Task 4: Approval materialises the Member

**Files:**
- Create: `verenigingen/services/member/application/application_materialiser.py`
- Modify: `api/membership_application_review.py` (new `approve_application`; `_approve_membership_application_locked` :669 stays the core)
- Test: Create `verenigingen/tests/integration/test_application_record_approval.py`

**Interfaces:**
- Consumes: Task 2's payload shape (helper keys) and Task 3's `validate_chapter_permission_or_throw(application_name, ...)`.
- Produces:
  - `PROTECTED_FIELDS: frozenset` holds `email`, `status`, `application_status`, `user`, `customer`, `member_id`, `payment_reference`, `fee_override_by`, `fee_override_date`, `fee_override_reason` and `dues_rate`, with the last four honoured only under `_fee_came_from_application`.
  - `materialise_member(application: Document) -> Document`
    - **No existing Member:** calls `create_member_from_application(data, application_id, address)`.
    - **Existing Member:** applies every non-blank supplied key that is not in `PROTECTED_FIELDS` and saves through `Member.save()`, so IBAN history fires.
    - Either way it sets `application_status="Pending"` (and `status="Pending"` for a new Member) so the core's preconditions hold.
    - Then it creates a Pending Chapter Member row for `application.chapter` through `create_pending_chapter_membership`, and a Volunteer when `interested_in_volunteering` is set.
    - Answers (`join_reasons`, `magazine_delivery`, ...) and dues fields are written as `short_application_confirm._set_answers` / `_set_dues_fields` did.
  - `approve_application(application_name: str, membership_type=None, chapter=None, notes=None, create_invoice=True, activate_as_volunteer=False) -> dict`
    - Whitelisted, `@high_security_api()`.
    - Order: permission check, then `advisory_lock(f"approve_application:{application_name}")`.
    - Then lock the MAS `for_update`. If it is not `Pending Review`, refuse with "This application cannot be approved in its current state".
    - Re-run `_handle_existing_member`; refuse if blocked.
    - Under a savepoint: `materialise_member` → `_approve_membership_application_locked(member.name, ...)` → MAS `set_status("Approved")`, `member=member.name`, review fields.
    - On an exception, roll back to the savepoint and re-raise. Let `NON_RESUMABLE_DB_ERRORS` propagate unchanged.
- Suppress the generic "Membership Status Update: Pending" email that `member_event_emission_service` sends when the Member is inserted. Set `member.flags` to the bulk flag that the service already honours (`:41-45`), and say which flag in the code.

- [ ] **Step 1: Write the failing tests**
  - `test_approve_new_applicant_creates_active_member`: real flow (submit → confirm → `approve_application`).
    - Exactly one Member with `status == "Active"` and `application_status == "Approved"`; `application_id` equals the MAS's.
    - One submitted Membership; an Active Chapter Member row in `MAS.chapter`; MAS `status == "Approved"` and `member` set.
  - `test_approve_reapplication_applies_supplied_fields`: Quit member with IBAN A, application with IBAN B and a new last name. After approval:
    - `Member.iban == B`, and the last name is the new one.
    - The `iban_history` row for A has `is_active == 0` and a `to_date`; the row for B has `is_active == 1`.
  - `test_blank_field_keeps_member_value`: the application omits `contact_number` and `birth_date`. After approval the Member keeps both earlier values.
  - `test_protected_fields_not_written`: the application payload carries `email="other@example.org"` and `status="Banned"`. After approval the Member's email is unchanged and the status is `Active`.
  - `test_member_became_active_meanwhile_refused`: confirm a Quit member's application, then approve a separate earlier path that makes the Member Active. `approve_application` raises, and the MAS stays `Pending Review`.
  - `test_failure_leaves_nothing`:
    - Patch `MembershipCreationService._create_membership_invoice` to raise `frappe.ValidationError`. That is below `_approve_membership_application_locked`, and no layer between it and the savepoint swallows the error (dispatch README rule 17: verify this by reading the call path and say so in the test docstring).
    - Afterwards there are 0 Members, Addresses, Customers and Contacts for the email, and the MAS is `Pending Review`.
  - `test_superseded_application_refused`: approving the older of two applications raises.
  - `test_single_applicant_email_on_approval`: count `Email Queue` rows to the applicant during approval. No "Membership Status Update: Pending" subject.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** `application_materialiser.py` and `approve_application`.
- [ ] **Step 4: Run them and see them pass.** Then run the approval suites from the census (`test_membership_approval`, `test_canonical_approval_chapter_activation`, `test_chapter_membership_approval_integration`, `test_concurrency_safety`, `test_reapplication_dues_template`, `test_membership_creation_service`) and the #1741 test module.
- [ ] **Step 5: Mutants.** For each, at least one test must redden:
  - drop the blank-skip;
  - drop `PROTECTED_FIELDS`;
  - write the IBAN with `db_set`;
  - skip the existing-member re-check.

  Then commit `feat(application): approval creates or updates the Member from the application (#1765, #1740)`.

### Task 5: Rejection touches only the application

**Files:**
- Modify: `api/membership_application_review.py` (new `reject_application`)
- Test: extend `test_application_record_approval.py`

**Interfaces:**
- Produces: `reject_application(application_name: str, reason: str, email_template=None, rejection_category=None, internal_notes=None) -> dict`
  - Whitelisted, with the same permission order as approve.
  - Sets the MAS to `Rejected` with review fields, then sends `send_rejection_notification` to `MAS.email`. That function currently takes a Member; give it an `email`/`name` overload or a thin wrapper.
  - `process_refund` is dropped. It was unreachable: the census found `application_invoice` is never persisted.

- [ ] **Step 1: Failing tests**
  - `test_reject_new_applicant_creates_nothing`: 0 Members, and the MAS is `Rejected`.
  - `test_reject_reapplication_leaves_member_untouched`: the Quit member's `modified`, `iban` and `status` are unchanged.
  - `test_rejected_application_can_reapply`: a new submit and confirm for the same email produces a fresh `Pending Review` MAS.
- [ ] **Step 2: Run them and see them fail.** `reject_application` does not exist yet.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit.** `feat(application): rejecting an application leaves the Member alone (#1765)`

### Task 6: Change preview for reviewers

**Files:**
- Modify: `application_materialiser.py`, and `page/membership_application_review/membership_application_review.js`
- Test: extend `test_application_record_approval.py`

**Interfaces:**
- Produces: `get_application_changes(application_name: str) -> list[dict]`
  - Whitelisted, with the permission check from Task 3.
  - Each row is `{"field": str, "label": str, "current": Any, "proposed": Any}`.
  - It covers exactly the fields `materialise_member` would write, sharing one function with it (`_writable_values(application, member) -> dict`) so the preview cannot drift from the write.
  - It returns `[]` for a new applicant.
  - The IBAN shows in full only to Verenigingen Administrator; board members see the last 4 characters.

- [ ] **Step 1: Failing tests**
  - `test_changes_list_only_differing_supplied_fields`: Quit member; the application changes IBAN and last name, and omits phone. The result is exactly two rows, `iban` and `last_name`.
  - `test_preview_matches_write`: for the same fixture, the fields changed by `approve_application` equal the preview's `field` set.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Render the table in the review page's approve dialog.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit.** `feat(application): reviewers see which member fields an application changes (#1765)`

### Task 7: Review surfaces read applications

**Files:**
- Modify:
  - `get_pending_applications` (`membership_application_review.py:1043`)
  - the review page JS (:554, :578, :801, :873, :908)
  - `report/pending_membership_applications/pending_membership_applications.py:69-124`
  - `templates/pages/chapter_dashboard.py:526-608`
  - `api/chapter_dashboard_api.py` (`quick_approve_member` :218-260, `get_pending_applications_count` :449-469)
  - `public/js/chapter_dashboard.js:141`
  - `doctype/member/member.js` (review button :1158-1200 and dialogs :2442-2680)
  - `api/admin_membership_operations.get_application_stats` :157-219
- Test: update `test_membership_application_review_coverage`, `test_chapter_dashboard_api_coverage` and `test_membership_applications_page_1502`, plus the report test if one exists.

**Interfaces:**
- Consumes: Tasks 3-5.
- Produces:
  - `get_pending_applications(chapter=None, days_overdue=None) -> list[dict]` reads `Pending Review` MAS rows. Keys: `name`, `application_id`, `applicant_name`, `email`, `membership_type`, `chapter`, `application_date` (= `confirmed_on`), `days_pending`.
  - `quick_approve_member` is renamed `quick_approve_application(application_name)` and calls `approve_application`. This removes the branch that flipped only the Chapter Member row (census §1).
  - `member.js` drops the review button and the approve, reject and request-more-info dialogs.

- [ ] **Step 1: Failing tests**, one per surface:
  - the pending list returns a confirmed MAS and no Members;
  - the dashboard count equals the number of `Pending Review` MAS rows in that chapter;
  - the report lists the MAS.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Then grep for the leftovers: `application_status.*Pending`, `"status": "Pending"` on Member, and `cm.status='Pending'`. Every remaining hit is either converted, or left with a one-line reason in the PR. Expected leftovers: the MijnRood sync (out of scope, see below), `member_list.js` indicators and `member_utils.update_termination_status_display`.
- [ ] **Step 4: Run them and see them pass.** Then run the census's page and dashboard suites.
- [ ] **Step 5: Commit.** `feat(application): review list, report and chapter dashboard read applications (#1765)`

### Task 8: Status page, template guard and retention

**Files:**
- Modify:
  - `templates/pages/application_status.py:33-77` and `.html`
  - `doctype/membership_dues_schedule/membership_dues_schedule.py:68-95`
  - the purge job, which moves into `application_record.py`; update `hooks/scheduler.py:64`
- Test: `test_page_application_status.py`, a new `test_template_frequency_guard_pending_application`, and `test_short_application_cleanup.py`

**Interfaces:**
- `application_status` page: gated by a guest return token on the **MAS name**, minted in the confirmation success response. It shows `status`, `application_id`, the date, and `review_notes` only when Rejected.
- `validate_template_frequency_not_in_use` also refuses when a `Pending Review` MAS's payload `selected_dues_schedule` equals this template.
- `expire_and_purge_applications() -> dict`: expire Unconfirmed rows older than 7 days; delete `Unconfirmed`/`Expired`/`Rejected`/`Superseded` rows whose `modified` is more than 30 days old; keep `Approved` and `Pending Review` rows.

- [ ] **Step 1: Failing tests**
  - `test_status_page_reads_application_by_token`
  - `test_status_page_refuses_bad_token_identically`
  - `test_template_frequency_change_refused_while_application_pending`
  - `test_purge_deletes_old_rejected_keeps_approved_and_pending` (set `modified` with `db.set_value(..., update_modified=False)` and say so in the docstring)
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Commit.** `feat(application): status page, template guard and retention follow the application record (#1765)`

### Task 9: Remove the submit-time Member writers

**Files:**
- Modify: `services/member/approval/application_helpers.py`. Remove `update_member_from_reapplication` (:763), `_reset_application_dues_choice` (:744) and `_sanitize_application_names`, unless `materialise_member` now uses one of them. Remove the submit-time call to `create_volunteer_record`; it moves to Task 4.
- Remove the deprecated `approve_membership_application` and `reject_membership_application` in `api/membership_application.py:837-939`, together with their tests.
- Retire the member-keyed whitelisted `approve_membership_application` and `reject_membership_application` in `api/membership_application_review.py`. Task 3 changed `validate_chapter_permission_or_throw` to take an application name, so these endpoints must not stay reachable. Keep `_approve_membership_application_locked` as the internal core that `approve_application` calls. Do the same for `api/background_approval_api.approve_membership_application_background`, which has no JS caller (census §3).
- Exemption: **pure deletion of dead code.** Show it with `grep -rn "<name>" --include=*.py --include=*.js` returning only the deleted definitions and their tests.

- [ ] **Step 1: Grep each symbol and record the hits in the commit body.**
- [ ] **Step 2: Delete them.** Run the six `--update-baseline` validators from `.github/workflows/code-validation.yml` and commit any shrink (dispatch rules 15/16).
- [ ] **Step 3: Run** `test_application_helpers`, `test_application_helpers_coverage`, `test_application_helpers_reapplication` (delete what tested the removed code) and `test_membership_application_coverage`.
- [ ] **Step 4: Commit.** `refactor(application): remove the submit-time Member writers (#1765)`

---

## Out of scope (file or link before starting)

- **MijnRood sync** (`mijnrood_sync/services/event_application/application_sync_service.py:127-160, 256-310`) creates Pending Members on its own and approves them by setting fields directly. It is a separate route into the same states. File an issue and link it from #1765.
- **The `/word-lid` short path never applied `_only_if_selectable_chapter`** (census §2.4). Task 2's `confirm_application` resolves the chapter for both forms; apply the #1731 check there and note the fix.
- **Whether an IBAN change at approval cancels the old SEPA mandate** is not established (comment on #1765). Measure it during Task 4; if it does not, file the finding as its own issue rather than widening this plan.
- **`request_more_info` / "Under Review"** is unreachable in the canonical flow (census §1). Task 7 removes the button. Bringing the state back is a product decision and is not included.
