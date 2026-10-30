# Short Membership Application Page ("word lid") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public `/word-lid` landing page with three admin-managed doors (Regulier, Student, Huisgenoot), a short form per door, email confirmation, and hand-off into the existing manual approval.

**Architecture:** Door records configure each form. A guest submit stores a `Membership Application Submission` (no Member yet) and emails a signed confirm link. A POST on the confirm page turns the submission into an Address + Member (Pending) through the existing `application_helpers` functions. Approval is untouched.

**Tech Stack:** Frappe v16 (DocTypes, `templates/pages`/`www` pages, `frappe.sendmail`, scheduler), Python services, Tailwind markup as on `/apply_for_membership`.

**Spec:** `docs/superpowers/specs/2026-10-30-short-application-page-design.md`

## Global Constraints

- Do not change the behaviour of `/apply_for_membership` or `api/membership_application.submit_application`. The modules `tests/backend/unit/api/test_membership_application_api.py` and `test_membership_application_coverage.py` must stay green.
- Unconfirmed submissions never create Member, Address or Customer rows.
- The confirm link's GET has no side effects. Only the POST confirms.
- Refusals for unknown id / wrong token / expired / already confirmed are identical on every channel: HTTP status, message, response shape, `_server_messages`.
- Token: `generate_guest_return_token("application_email_confirmation", submission.name)`. Expiry is 7 days from submission `creation`. The daily job deletes Unconfirmed/Expired submissions older than 30 days.
- Every chosen amount (tier or own) goes to the old helpers as `custom_contribution_fee`, with `custom_amount_reason = "Bedrag gekozen bij aanmelding (<door title>)"`.
- `payment_method`: `"sepa_direct_debit"` if an IBAN is given, else `"bank_transfer"`.
- Edit DocType JSON **by line**. Never rewrite a JSON file with `json.dumps` (CLAUDE.md).
- `frappe.log_error(title=..., message=...)` keyword form only. No bare `frappe.db.commit()` in new code unless the task explains why; Frappe's request commit applies.
- User-facing strings wrapped in `_()` / `__()`.
- Run tests on **test_site_2** (developer_mode 0, matches CI), from the worktree:
  `cd ~/frappe-bench && PYTHONPATH=~/agent-worktrees/short-application-page bench --site test_site_2 run-tests --app verenigingen --module <module>`
  After adding DocTypes, first run `PYTHONPATH=~/agent-worktrees/short-application-page bench --site test_site_2 migrate`.
  Diff every red run against the same command without `PYTHONPATH` (CLAUDE.md).
- Test base class: `VereningingenUnitTestCase` (`verenigingen/tests/utils/base.py`), as the existing application API tests use it. Track created Members with `self.track_doc`.

## Review Focus

1. **Email normalisation:** `" Foo@Example.COM "` must be treated as the existing member `foo@example.com`. That covers the existing-member routing and the duplicate check at confirm. Test in Task 4.
2. **Two submissions for one email before either is confirmed:** confirming the second after the first must reach the existing-member path (update, or no-link refusal), never a second Member. Test in Task 5.
3. **Door disabled or edited between submit and confirm:** confirm still uses the stored payload and succeeds. The application was valid when made. Test in Task 5.
4. **Dutch decimal input:** an own amount typed as `"7,50"` is accepted as `7.50`, and `"7.50"` likewise. Test in Task 3.
5. **Slug `bevestig`:** it would shadow the confirm route, so the door must refuse it. Test in Task 2.

---

### Task 1: Answer masters and new Member fields

**Files:**
- Create: `verenigingen/verenigingen/doctype/membership_join_reason/` (`membership_join_reason.json`, `.py`, `__init__.py`). A master with `reason` (Data, unique, autoname `field:reason`) and `enabled` (Check, default 1).
- Create: `verenigingen/verenigingen/doctype/member_join_reason/`. A child table (istable) with `join_reason` (Link → Membership Join Reason, reqd), used as Table MultiSelect.
- Create: `verenigingen/verenigingen/doctype/membership_referral_source/`. A master with `source` (Data, unique, autoname `field:source`) and `enabled`.
- Modify: `verenigingen/verenigingen/doctype/member/member.json`. Add fields to the application section, by line: `magazine_delivery` and `starter_guide_delivery` (Select `\nDigitaal\nPapier\nBeide\nGeen`), `birth_year` (Int), `join_reasons` (Table MultiSelect → Member Join Reason), `join_reason_other` (Data), `referral_source` (Link → Membership Referral Source), `referral_source_other` (Data), `housemate_of_name` (Data), `application_door` (Link → Membership Application Door; added in Task 2, so add this one field there), `application_consent_at` (Datetime, read_only), `application_consent_version` (Data, read_only).
- Create: `verenigingen/patches/v0_9/seed_application_answer_masters.py`, listed in `patches.txt`.
- Test: `verenigingen/tests/backend/unit/doctype/test_application_answer_masters.py`

**Interfaces:**
- Produces: DocTypes `Membership Join Reason`, `Member Join Reason`, `Membership Referral Source`. Member fields as listed. `seed_application_answer_masters.execute()` is idempotent.
- Seed values (Procurios, verbatim):
  - Reasons: Promotie van veganisme/vegan levenswijze; Promotie van vegan eten/plantaardige voeding; Ondersteunen van de NVV; Voor de dieren; Informatie krijgen over veganisme; Zelf vegan (geworden); Hulp bij vegan zijn/worden; Duurzaamheid/het milieu/de wereld; Verbondenheid met andere vegans; Gezondheid; VEGAN Magazine; Ledenpasvoordeel.
  - Sources: Via onze website (veganisme.org); Via online zoeken (bijv. Google); Via vriend/kennis/collega/familie; Via VEGAN Magazine; Via een NVV-stand op een event; Via de VeganChallenge (NVV); Via de Veggie Challenge (ProVeg).

- [ ] **Step 1: Write failing tests**
  - `test_seed_creates_12_reasons_and_7_sources`: run `execute()` twice; assert `frappe.db.count("Membership Join Reason") >= 12`, each seeded name exists exactly once, and likewise for the 7 sources.
  - `test_member_accepts_application_answer_fields`: create a Member (existing factory) with `magazine_delivery="Papier"`, `birth_year=1990`, `join_reasons=[{"join_reason": "Voor de dieren"}]`, `referral_source="Via VEGAN Magazine"`; reload and assert the values round-trip.
- [ ] **Step 2: Migrate test_site_2 and run.** Expected: FAIL. The DocTypes don't exist.
- [ ] **Step 3: Add the DocTypes, Member fields and patch.**
- [ ] **Step 4: Migrate and run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(application): answer masters and Member fields for the short application`

---

### Task 2: Membership Application Door

**Files:**
- Create: `verenigingen/verenigingen/doctype/membership_application_door/` (json, py, js optional). The fields are the spec's door table: `title`, `slug` (unique), `enabled`, `sort_order`, `card_text`, `intro_text`, `membership_type`, `form_shape` (Select `Regular\nHousemate`), `monthly_dues_template`, `annual_dues_template`, `amount_options` (Table), `allow_custom_amount`, `postal_minimum_monthly`, `postal_minimum_annual`, `hidden_questions` (Table). Autoname `field:slug`. Permissions: System Manager and Verenigingen Administrator full access; no Guest or Website perms.
- Create: child `membership_application_door_amount/`: `frequency` (Select `Monthly\nAnnual`, reqd), `amount` (Currency, reqd).
- Create: child `membership_application_door_hidden_question/`: `question` (Select, reqd). Options are the hideable fixed list: `mobile_no\nbirth_year\njoin_reasons\nreferral_source\nmagazine_delivery\nstarter_guide_delivery`. This is a plain child table, not Table MultiSelect, because the options aren't a DocType.
- Modify: `member.json`. Add `application_door` (Link → Membership Application Door, read_only).
- Test: `verenigingen/tests/backend/unit/doctype/test_membership_application_door.py`

**Interfaces:**
- Produces: `MembershipApplicationDoor.validate()`; `get_template_for(self, frequency: str) -> str | None`; `minimum_for(self, frequency: str, postal: bool) -> float`, which returns the max of the template's `minimum_amount` and, when `postal`, `postal_minimum_<frequency>`; `hidden(self) -> set[str]`.
- Module constant `RESERVED_SLUGS = {"bevestig"}`.

- [ ] **Step 1: Write failing tests**
  - `test_slug_must_be_lowercase_url_safe`: `"Student Leden"` → `frappe.ValidationError`; `"student-leden"` saves.
  - `test_slug_bevestig_is_reserved` (Review Focus 5): `"bevestig"` → `ValidationError`.
  - `test_template_must_belong_to_door_type`: a template of another Membership Type in `monthly_dues_template` → `ValidationError`. The type's own template saves.
  - `test_non_template_schedule_refused`: a schedule with `is_template=0` → `ValidationError`.
  - `test_regular_door_needs_at_least_one_template`: Regular shape with both templates empty → `ValidationError`. Housemate shape with both empty saves.
  - `test_minimum_for_uses_postal_minimum_only_when_postal`: template minimum 2.50, `postal_minimum_monthly=3` → `minimum_for("Monthly", False) == 2.50`, `minimum_for("Monthly", True) == 3`. Derive the 2.50 from the template you create; don't hard-code it separately.
- [ ] **Step 2: Migrate and run.** Expected: FAIL.
- [ ] **Step 3: Implement the DocType and controller.**
- [ ] **Step 4: Migrate and run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(application): Membership Application Door doctype`

---

### Task 3: Submission DocType and form validation

**Files:**
- Create: `verenigingen/verenigingen/doctype/membership_application_submission/`. Fields: `door` (Link, reqd), `email` (Data, reqd), `payload` (JSON), `status` (Select `Unconfirmed\nConfirmed\nExpired`, default Unconfirmed), `confirmed_on` (Datetime), `member` (Link Member). Autoname hash. Permissions: System Manager and Verenigingen Administrator read and delete only.
- Create: `verenigingen/services/member/application/short_application_validation.py`
- Test: `verenigingen/tests/backend/unit/services/test_short_application_validation.py`

**Interfaces:**
- Produces: `validate_short_application(door: MembershipApplicationDoor, data: dict) -> dict`. It returns the **cleaned payload**: stripped strings, lower-cased email, `amount` as float, the key `selected_dues_schedule` resolved from frequency, hidden-question keys dropped, and `consent_given_at` / `consent_text_version` added for Regular shape. It raises `frappe.ValidationError` with a translated message on the first rule broken.
- Module constant `CONSENT_TEXT_VERSION = "2026-10-30"`.
- Payload keys (the form posts exactly these): `first_name, tussenvoegsel, last_name, email, mobile_no, address_line1, postal_code, house_number, house_number_addition, city, country, frequency, amount, magazine_delivery, starter_guide_delivery, iban, bank_account_name, consent, birth_year, join_reasons (list[str]), join_reason_other, referral_source, referral_source_other, housemate_of_name, housemate_confirmed, website` (honeypot).

- [ ] **Step 1: Write failing tests.** Use one Regular door fixture and one Housemate door fixture. Derive minimums from the fixture templates.
  - `test_valid_regular_payload_is_cleaned`: the result has `selected_dues_schedule == door.monthly_dues_template`, `email` lower-cased, `consent_text_version == CONSENT_TEXT_VERSION`.
  - `test_monthly_without_iban_refused`
  - `test_amount_below_template_minimum_refused`, at `minimum - 0.01`.
  - `test_amount_below_postal_minimum_refused_when_papier`: an amount between the template minimum and the postal minimum, `magazine_delivery="Papier"` → refused; the same amount with `"Digitaal"` → accepted.
  - `test_papier_refused_for_non_nl_address`: `country="Belgium"`, `starter_guide_delivery="Beide"` → refused.
  - `test_frequency_without_door_template_refused`: a door with no annual template, `frequency="Annual"` → refused.
  - `test_missing_required_field_refused`, parametrised over `first_name, last_name, email, address_line1, postal_code, city, country`.
  - `test_regular_without_consent_refused`
  - `test_housemate_requires_payer_name_and_confirmation`
  - `test_housemate_ignores_amount_and_iban`: the cleaned payload has no `amount` and no `selected_dues_schedule`.
  - `test_hidden_question_values_are_dropped`: the door hides `birth_year`; the payload carries `birth_year=1990`; the cleaned payload has no `birth_year`.
  - `test_dutch_decimal_comma_amount_accepted` (Review Focus 4): `"7,50"` → `7.5`; `"7.50"` → `7.5`.
  - `test_birth_year_out_of_range_refused`: `current_year + 1` and `current_year - 121` refused.
- [ ] **Step 2: Run.** Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the DocType and `validate_short_application`. Use `validate_iban_api` / the IBAN validator the old flow uses for the IBAN format.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(application): submission doctype and short-form validation`

---

### Task 4: Submit endpoint and confirmation email

**Files:**
- Create: `verenigingen/api/short_application.py`
- Test: `verenigingen/tests/backend/unit/api/test_short_application_submit.py`

**Interfaces:**
- Consumes: `validate_short_application` (Task 3); `_handle_existing_member(existing_member, data)` from `api/membership_application.py`, imported, not copied.
- Produces: `submit_short_application(door: str, **data) -> dict`, which is `@frappe.whitelist(allow_guest=True)` with the same security decorator stack as `submit_application` (`@public_api(operation_type=OperationType.MEMBER_DATA)`, `@handle_api_error`) plus `check_rate_limit("submit_short_application", ...)`. It **always** returns `{"success": True, "message": _("Check your email to confirm your application.")}` for any payload that passes validation, whatever the email's status. Validation failures return the validation message.
- Produces: `CONFIRM_TOKEN_PURPOSE = "application_email_confirmation"`; `build_confirm_url(submission_name: str) -> str` → `/word-lid/bevestig?submission=<name>&token=<token>`.
- Email routing: no existing Member, or `_handle_existing_member` returns `("update", None)` → store the submission and send the confirm email with the link. Blocked → store **no** submission and send the "you already have a membership, contact us" email **without a link**. Matching on email is case- and whitespace-insensitive.
- Honeypot `website` filled → return the same success response, store nothing and send nothing.

- [ ] **Step 1: Write failing tests**
  - `test_valid_submit_creates_submission_and_one_email_but_no_member`: Member, Address and Customer counts unchanged; one `Membership Application Submission` (Unconfirmed); one `Email Queue` row to the email whose message contains `build_confirm_url(name)`.
  - `test_active_member_email_gets_same_response_and_no_link_email`: an Active Member exists; the response equals the new-email response (dict equality); `frappe.local.message_log` matches in both cases; no submission; the email has no `/word-lid/bevestig`.
  - `test_email_matching_is_normalised` (Review Focus 1): an Active Member `foo@example.com`; submit `" Foo@Example.COM "` → no-link email path.
  - `test_rejected_applicant_gets_confirm_link`: a Member with `application_status="Rejected"` → a submission plus a link email.
  - `test_honeypot_returns_success_and_stores_nothing`
  - `test_validation_error_is_returned`: monthly without IBAN → `success False` with the validation message.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Email text is Dutch, wrapped in `_()`, sent with `frappe.sendmail(recipients=[email], subject=..., message=...)`.
- [ ] **Step 4: Run.** Expected: PASS. Also run `test_membership_application_api` to show it is unaffected.
- [ ] **Step 5: Commit** `feat(application): short application submit endpoint with email confirmation`

---

### Task 5: Confirm endpoint

**Files:**
- Modify: `verenigingen/api/short_application.py`
- Create: `verenigingen/services/member/application/short_application_confirm.py`
- Test: `verenigingen/tests/backend/unit/api/test_short_application_confirm.py`

**Interfaces:**
- Consumes: `create_address_from_application(data)`, `create_member_from_application(data, application_id, address=None)`, `update_member_from_reapplication(member_name, data, application_id, address=None)`, `generate_application_id()` (all in `services/member/approval/application_helpers.py`); `determine_chapter_from_application`, `_save_suggested_chapter` and `_create_pending_chapter_membership_safe`, exactly as `submit_application` uses them; `verify_guest_return_token`.
- Produces: `confirm_short_application(submission: str, token: str) -> dict`. It is whitelisted guest and **POST only**: if `frappe.request.method != "POST"`, return the generic refusal. On success it returns `{"success": True, "message": _("Thank you, your application is received and will be reviewed.")}`. Any refusal returns exactly `{"success": False, "message": _("This confirmation link is invalid or has expired.")}`.
- Produces: `to_helper_payload(cleaned: dict, door) -> dict`. It maps to the old helper keys: `selected_membership_type=door.membership_type`, `selected_dues_schedule`, `custom_contribution_fee=amount`, `uses_custom_amount=1`, `custom_amount_reason`, `payment_method`, `iban`, `bank_account_name`, `contact_number=mobile_no`, `address_line1` (street + house number + addition), `postal_code`, `city`, `country`, `email`, `first_name`, `last_name`, `application_source=door.slug`. The `tussenvoegsel` goes to wherever `create_member_from_application` takes it: check whether it reads `tussenvoegsel`; if not, set it on the Member afterwards.
- After the helper call, set the Task 1 Member fields and `application_door`, then `member.save()`. Mark the submission `Confirmed`, `confirmed_on=now`, `member=<name>`.

- [ ] **Step 1: Write failing tests**
  - `test_valid_post_creates_one_pending_member_with_answers`: Member `application_status == "Pending"`, `application_dues_schedule` == door monthly template, `dues_rate == amount`, `magazine_delivery`, `join_reasons`, `application_door`, `application_consent_at` and `application_consent_version` set; submission Confirmed.
  - `test_get_request_confirms_nothing`
  - `test_refusals_are_identical`: wrong token, unknown id, expired (set `creation` to 8 days ago with `frappe.db.set_value(..., update_modified=False)`) and already-confirmed each return the same dict and the same `message_log`, and create no Member.
  - `test_second_confirm_creates_nothing`
  - `test_second_submission_same_email_does_not_duplicate_member` (Review Focus 2): two submissions; confirm the first; confirming the second results in exactly one Member with that email.
  - `test_door_disabled_after_submit_still_confirms` (Review Focus 3)
  - `test_reapplication_updates_existing_member`: a Rejected Member → confirm → same Member name, `application_status` back to Pending, `application_door` overwritten.
  - `test_approval_creates_monthly_schedule_at_chosen_amount`: confirm, then call `api.membership_application_review.approve_membership_application` (as the existing approval tests do) → the dues schedule has `billing_frequency == "Monthly"` and `dues_rate == amount`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Wrap the address + member + field writes so a failure leaves the submission Unconfirmed: use `frappe.database.savepoint`, never a bare commit.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(application): confirm endpoint creates the pending Member`

---

### Task 6: Pages and route

**Files:**
- Create: `verenigingen/www/word-lid.html` + `verenigingen/www/word_lid.py` (landing and form, chosen by the `door` path param), following the hyphenated-html / underscored-py pattern of `www/dues-coverage-manager.html` + `dues_coverage_manager.py`.
- Create: `verenigingen/www/word-lid-bevestig.html` + `word_lid_bevestig.py` (confirm page: a GET renders a "Bevestig" button that POSTs to `confirm_short_application`).
- Create: `verenigingen/public/js/short_application.js` (client-side mirror of the rules, posting to `submit_short_application`).
- Modify: `verenigingen/hooks/portal.py` to add `website_route_rules = [{"from_route": "/word-lid/bevestig", "to_route": "word-lid-bevestig"}, {"from_route": "/word-lid/<door>", "to_route": "word-lid"}]`. Modify `verenigingen/hooks/__init__.py` to import it. The order matters: `bevestig` comes first.
- Test: `verenigingen/tests/backend/unit/pages/test_word_lid_page.py`

**Interfaces:**
- Produces: `word_lid.get_context(context)`. Without `door` it sets `context.doors` (enabled doors, ordered by `sort_order`, with title/card_text/slug). With `door` it sets `context.door` and `context.hidden` (the set); unknown or disabled raises `frappe.PageDoesNotExistError`. Branding comes from Brand Settings, as `apply_for_membership.py` does.

- [ ] **Step 1: Write failing tests**
  - `test_landing_lists_enabled_doors_in_order`
  - `test_unknown_or_disabled_door_is_404`
  - `test_hidden_question_not_rendered`: render the page HTML (`frappe.website.serve.get_response("word-lid/<slug>")` or `render_template`) for a door hiding `birth_year` → no `name="birth_year"`; the same door without the hide → present.
  - `test_route_rule_resolves_bevestig_before_door`: `frappe.get_hooks("website_route_rules")` contains both, `bevestig` first.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the pages and JS. Markup follows the wordlid blocks (*Mijn keuzes*, *Mijn gegevens*, *Extra informatie*).
- [ ] **Step 4: Run.** Expected: PASS. `npx eslint verenigingen/public/js/short_application.js` is clean.
- [ ] **Step 5: Commit** `feat(application): word-lid landing, form and confirm pages`

---

### Task 7: Expiry and cleanup job

**Files:**
- Modify: `verenigingen/services/member/application/short_application_confirm.py` to add `expire_and_purge_submissions() -> dict`.
- Modify: `verenigingen/hooks/scheduler.py` to add the job to `"daily"`.
- Test: `verenigingen/tests/backend/unit/services/test_short_application_cleanup.py`

**Interfaces:**
- Produces: `expire_and_purge_submissions()`. It marks Unconfirmed rows older than 7 days as Expired and deletes Unconfirmed/Expired rows older than 30 days. **Confirmed rows are kept.** It returns `{"expired": n, "deleted": m}`.

- [ ] **Step 1: Write failing tests**
  - `test_old_unconfirmed_expire_and_ancient_ones_are_deleted`: rows at 1, 8 and 31 days (backdate `creation`) → the 1-day row is untouched, the 8-day row is Expired, the 31-day row is gone.
  - `test_confirmed_rows_are_never_deleted`: a 40-day Confirmed row survives.
  - `test_job_is_registered_daily`: the dotted path is in `frappe.get_hooks("scheduler_events")["daily"]`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(application): expire and purge unconfirmed submissions`

---

### Task 8: Self-review, gates and veg11 configuration

No new product code.

- [ ] **Step 1:** Run the CLAUDE.md self-review checklist on the branch. Mutate each fix away and watch its test redden, including at least the always-True mutant on the identical-refusal and existing-member tests.
- [ ] **Step 2:** `pre-commit run --all-files` and `pre-commit run --hook-stage pre-push --all-files`, including the duplicate-helper clone-family sync from `~/frappe-bench/dispatch/author_brief_common.md`.
- [ ] **Step 3:** Run every new test module plus `test_membership_application_api` and `test_membership_application_coverage` on test_site_2. All must be green.
- [ ] **Step 4: veg11 configuration** (`bench --site veg11.veganisme.org migrate` from the live tree after merge, not from the worktree): create the `Huisgenootlid` type with an Annual €0 template; create the real Student type with its templates (amounts from the association); create the three doors. Then smoke-test by hand: submit, confirm, approve one Regulier. Record whether Huisgenoot approval creates a €0 invoice; the spec says to accept it and note it in the PR.
- [ ] **Step 5:** File the follow-up issues from the spec (student re-approval, welcome + follow-up email, postcode autofill), each after a `gh issue list --state all --limit 500 --search` check.
