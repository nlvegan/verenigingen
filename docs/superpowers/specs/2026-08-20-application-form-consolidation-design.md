# Application form consolidation — design

**Status:** proposed, awaiting review
**Origin:** #201 → #409 / #413 → #412. Extended after discovering a second, dead
application page and that the surviving page collects its payload in a way that
guarantees the #412 bug class.

## Problem

`/apply_for_membership` builds its entire submission payload in
`collectFormDataDirectly()` (`verenigingen/public/js/membership_application.js`), by
hand-writing 32 `$('#id')` lookups. Nothing checks those ids exist, so a wrong one
transmits `''` or `false` forever without raising, logging, or failing a test. Fourteen
of its thirty-one id-reading keys were in that state; #413 fixed two and ratcheted the
rest.

The remaining twelve are not one problem. Grouped by whether a destination exists:

| group | fields | fact |
|---|---|---|
| duplicate of a working field | `newsletter_opt_in`, `transfer_iban`, `transfer_account_name` | `accepts_optional_communications` and `iban` / `bank_account_name` already work |
| no column yet | `application_source`, `application_source_details` | worth adding |
| destination exists, out of scope | `address_line2`, `state` | `tabAddress` has both |
| policy | `terms`, `gdpr_consent`, `confirm_accuracy` | no column, no reader |
| no action | `middle_name`, `payment_method` | superseded by `tussenvoegsel`; works via a `name` fallback |

## What was verified, and how

Every claim below was checked against a running system, not read out of source.

1. **`/apply_for_membership` is the live form.** It is the only page in `apps/` that loads
   `membership_application.js`; it instantiates `MembershipApplication`; `#btn-submit` →
   `submitApplication()` → `getAllFormData()` → `collectFormDataDirectly()` →
   `MembershipAPI` → POST `submit_application_with_tracking`, which resolves. The form
   carries `onsubmit="return false"`, so JS is the only route out.

2. **`/membership_application` has been unable to submit since 2026-01-08.** It posts to
   `verenigingen.api.membership_application.submit_enhanced_application`:

   ```
   frappe.get_attr(...) -> AttributeError: module has no attribute 'submit_enhanced_application'
   ```

   `verenigingen.api.enhanced_membership_application` was deleted in `5f8dca99`;
   `tests/integration/test_public_api_guest_access.py:92` already documents the removal.
   The page was left pointing at it.

3. **Its `.py` is load-bearing even though its `.html` is dead.**
   `templates/pages/membership_application.py` hosts `get_dues_schedules_for_membership_type`,
   which the live `apply_for_membership.html` calls. Deleting the page wholesale breaks
   the working form.

4. **A third orphan exists:** `verenigingen/templates/membership_application.html` (25KB,
   Jan 4) has no renderer at all.

5. **The dead page collected correctly.** `EnhancedMembershipApplication.collectFormData()`
   is `new FormData(form)` plus `append()` for computed fields. FormData serializes by
   `name` off the form itself, so it *cannot* reference an element that does not exist. It
   is structurally immune to the #412 class.

6. **`enable_volunteer_signup = 0` on veg11, `1` on test_site_1.** The volunteering step —
   skills, interests, availability — is currently switched **off** on the live instance.
   #201's fix is therefore correct but dormant there until the setting is turned on.

7. **No member has ever been created through either form on veg11**: 748 members, **0**
   with `application_id`, **0** with `application_date`, **0** with `pronouns` (a field
   only this collector sends). All 748 came from the CSV import. Consistent with the
   system not being live yet — so none of these defects has harmed a real applicant.

8. **When the volunteer step renders, its controls are inside the `<form>`** — all 30 skill
   checkboxes, `volunteer_skill_level` and `volunteer_comments`. `FormData(form)` will
   capture them.

## Decisions taken

- Consolidate onto **one form**, `/apply_for_membership`, and adopt the dead page's
  collection technique rather than its UI.
- Add real `application_source` / `application_source_details` Member fields.
- Record terms/privacy acceptance on Member. **Record only — do not enforce server-side
  yet**; closing that bypass needs every caller enumerated first, and is filed separately.
- Delete the five payload keys with no destination.
- **No backfill**, of either consent or acquisition source. Absence must mean "not
  recorded", never "not accepted" or an invented "Website".

## Design

Five phases, each its own PR, each independently revertable.

### Phase 1 — remove the dead pages

Delete `templates/pages/membership_application.html` and
`verenigingen/templates/membership_application.html`. **Keep
`templates/pages/membership_application.py` exactly where it is** — its whitelisted
helpers are live and `apply_for_membership.html` calls
`get_dues_schedules_for_membership_type` by dotted path, so moving the module to `api/`
would change that path and break the working form. Add a header comment explaining why a
page module outlives its page; relocating it is a separate change with its own callers to
update.

Removing the `.html` makes the route 404 rather than render a form whose submit button
cannot work.

### Phase 2 — delete the five dead payload keys

Remove `newsletter_opt_in`, `transfer_iban`, `transfer_account_name`, `address_line2`,
`state` from `collectFormDataDirectly`, and delete the two silent no-op assignments
`member.newsletter_opt_in = ...` (`application_helpers.py:579, 686`) — left in place they
keep telling the next reader the field works. Server-side `data.get("address_line2"/"state")`
reads stay, so the endpoint remains tolerant of other callers.

Ratchet baseline 12 → 7.

### Phase 3 — acquisition channel

Add `application_source` (Select) and `application_source_details` (Data) to Member;
render a select plus a conditional details input on the page. Options: Website, Search
Engine, Social Media, Event, Word of Mouth, Volunteer Application Form, Other — the last
matching what `templates/pages/volunteer/apply.html:381` already sends.
`application_helpers.py:582, 689` already assign the value, so it starts working the
moment the field exists. The `#source-details-container` toggle at
`membership_application.js:3578` is in the dead `StepManager` path; live toggle logic must
be written.

**No patch.** Existing members' source is unknown; backfilling "Website" invents data.

Ratchet baseline 7 → 5.

### Phase 4 — record consent

Add `terms_accepted`, `privacy_accepted` (Check) and `consent_timestamp` (Datetime) to
Member. The collector reads the real `input[name="terms_accepted"]` /
`[name="privacy_accepted"]` controls. Delete `confirm_accuracy`: no element renders it and
nothing validates it, so it is Phase 2's category in disguise.

**No backfill**, and the field descriptions must say so: writing `terms_accepted = 1` for
members who applied before the field existed would fabricate the very evidence the field
exists to hold.

Ratchet baseline 5 → 2, the survivors being `middle_name` and `payment_method`.

### Phase 5 — migrate the collector to FormData

The prize, and the riskiest step, so it lands last when the field set is already settled.

Replace the hand-written lookups with `new FormData(document.getElementById('membership-application-form'))`
plus explicit `append()` for genuinely computed values, exactly as the deleted page did.

Measured on `test_site_1` with the volunteer step enabled: the form has **32 named
controls**, and the collector emits **36 payload keys**, of which **31 read an element id**
(the ratchet's unit) and 5 are computed — `custom_contribution_fee`,
`selected_membership_type`, `uses_custom_amount`, `volunteer_interests`,
`volunteer_skills`. **18 control names already agree with their payload key**:

`address_line1`, `birth_date`, `city`, `country`, `custom_contribution_fee`, `email`,
`first_name`, `iban`, `interested_in_volunteering`, `last_name`,
`opt_out_optional_emails`, `payment_method`, `postal_code`, `pronouns`,
`selected_chapter`, `tussenvoegsel`, `volunteer_availability`,
`volunteer_experience_level`

The rest is a small enumerable mapping. Rename the **control** to the payload key wherever
the server's name is the better one:

| control today | payload key | action |
|---|---|---|
| `mobile_no` | `contact_number` | rename control; keep `mobile_no` accepted server-side |
| `account_holder_name` | `bank_account_name` | rename control |
| `terms_accepted` | `terms` | keep the control name — it is the clearer one and Phase 4's Member fields use it — and rename the *payload key* to `terms_accepted`, updating the server to read it |
| `privacy_accepted` | `gdpr_consent` | as above, payload key becomes `privacy_accepted` |
| `volunteer_comments` | `additional_notes` | rename control |
| `volunteer_skills[]` + `volunteer_skill_level` | `volunteer_skills` | **computed** — combine into `[{name, category, level}]` as #409 does |
| `volunteer_areas[]` | `volunteer_interests` | **computed**, and currently read nowhere server-side (#410) — resolve #410 first or drop |
| `membership_type_selection`, `payment_plan_selection`, `schedule_selection`, `billing_frequency`, `contribution_amount`, `membership_type`, `selected_dues_schedule`, `volunteer_availability_time` | — | wizard/UI-only; must be **excluded** deliberately, not by accident |

Two semantic changes this migration forces, both of which need explicit handling:

1. **Unchecked checkboxes are absent from FormData**, not `false`. Every boolean key
   (`interested_in_volunteering`, `opt_out_optional_emails`, the consent pair) must be
   normalised to a boolean after serialization, or the server's `data.get(k, default)`
   silently takes the default — the same failure shape as `newsletter_opt_in`.
2. **`name="x[]"` arrives as repeated entries.** Use `getAll()`; do not let the bracket
   suffix leak into a payload key.

## Testing

Each phase carries its own failing-test-first, and the #413 ratchet enforces the
bookkeeping throughout: deleting a field without removing its baseline line fails
`test_the_baseline_names_only_fields_that_still_exist`.

Phase 5 changes what the ratchet should assert. Once the collector no longer reads ids,
`test_application_form_selector_contract.py` must be reshaped from "every `$('#id')`
resolves" to **"every payload key the collector emits is one the server reads, and every
named control is either mapped or deliberately excluded"** — the same comparison one level
up. The excluded list is part of the assertion, so a new UI-only control cannot silently
join the payload.

A round-trip test per phase, through `submit_application`, asserting the value reaches the
Member/Volunteer record — the shape of `test_ticked_skills_reach_the_volunteer_record`.

## Non-goals

- Server-side **enforcement** of consent. Filed separately; needs every caller enumerated.
- Reviving the enhanced page's UI.
- The duplicated wrong ids in the dead `BaseStep` subclasses
  (`membership_application.js:~4003`). Dead because `StepManager` is never loaded; Phase 5
  should delete them along with the id-reading code rather than migrate them.
- `#volunteer-interests` / `volunteer_areas` semantics (#410) — Phase 5 depends on that
  decision only for one row of the mapping table.

## Risks

- **Phase 5 changes a public endpoint's input contract.** `submit_application` is
  `allow_guest`; any other caller posting the old keys must keep working. Mitigation: the
  server keeps accepting today's key names, and only the browser's output changes.
- **`enable_volunteer_signup = 0` on veg11** means the volunteer half of Phase 5 cannot be
  verified on the live instance by inspection alone. Verify on `test_site_1`, where the
  step renders, and state that scope rather than generalising.
- Renaming control `name` attributes touches the template's own inline JS, which addresses
  some controls by name (`addCustomSkill`, the consent validator at line 725). Grep the
  template for each renamed name — the fix's explanation is the search query.
