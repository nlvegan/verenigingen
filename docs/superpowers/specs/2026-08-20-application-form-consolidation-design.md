# Application form consolidation — design

**Status:** revised after skeptical review, awaiting approval
**Revision:** review found a live defect (#420) that invalidated two of this spec's dispositions and added a Phase 0. Corrections are marked **[rev]**.
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
| product call | `middle_name` | **[rev]** `Member.middle_name` exists (Data) and `application_helpers.py:674` writes it, so this is a decision to prefer `tussenvoegsel` on this page, not an absent destination |
| **broken, not "no action"** | `payment_method` | **[rev]** see #420 — the collector's correct read is overwritten downstream, so every application is submitted as Bank Transfer |

## What was verified, and how

Every claim below was checked against a running system, not read out of source.

1. **`/apply_for_membership` is the live form.** It is the only page in `apps/` that loads
   `membership_application.js`; it instantiates `MembershipApplication`; `#btn-submit` →
   `submitApplication()` → `getAllFormData()` → `collectFormDataDirectly()` →
   `MembershipAPI` → POST `submit_application_with_tracking`, which resolves. The form
   carries `onsubmit="return false"`, so JS is the only route out.

2. **`/membership_application` has never been able to submit — since 2025-11-20.** **[rev]**
   It posts to `verenigingen.api.membership_application.submit_enhanced_application`:

   ```
   frappe.get_attr(...) -> AttributeError: module has no attribute 'submit_enhanced_application'
   ```

   **[rev]** That function never existed in `api.membership_application`. It existed in
   `api.enhanced_membership_application`, and the template was written pointing at the
   *wrong module* in the same commit that created it (`2dbea04e`, 2025-11-20). The other
   module was later deleted (`5f8dca99`), which
   `tests/integration/test_public_api_guest_access.py:92` documents — but that deletion is
   a coincidence, not the cause. The page has never worked.

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

9. **[rev] The submitted payload is not the one this spec first measured.**
   `collectFormDataDirectly()` emits 36 keys; the payload actually posted is
   `getAllFormData()`, which merges `getAdditionalFormData()` **after** it and therefore
   overrides. `getAdditionalFormData` reads five more ids and is **not parsed by the
   ratchet at all**. The two values it carries are the payment method and the contribution
   amount. Everything in #420 lives in those 40 unguarded lines.

10. **[rev] The ratchet is green under a configuration production does not have.** It
    renders on `test_site_1` where `enable_volunteer_signup = 1`. Under veg11's `0`, the
    whole block between `apply_for_membership.html:424` and `:560` disappears, and four
    more units break — including `additional_notes`, whose only surviving reader is
    `#volunteer_comments` inside that block. So `Member.notes` — what the approver reads —
    is always empty on the live configuration. The honest count is **12 broken with the
    volunteer step on, 16 with it off**. The guard must render both.

11. **[rev] `volunteer_interests` is a 13th instance the guard cannot see.**
    `getSelectedVolunteerInterests()` reads `$('#volunteer-interests ...)`, which the page
    never renders (it renders `name="volunteer_areas[]"`). It escapes the ratchet twice:
    the read is outside the parsed object literal, and the id regex cannot match a
    descendant selector. Tracked as #410.

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

**[rev] Six phases**, each its own PR. Each is independently revertable, with one
asymmetry: Phases 3 and 4 add database columns that a revert leaves behind (see Risks).

### Phase 0 — one payload builder, and fix the payment method **[rev]**

Added after review. This is both a live defect (#420) and the hardest blocker for Phase 5,
so it goes first.

Every application is currently submitted as `payment_method = "Bank Transfer"` whatever the
applicant chose: `collectFormDataDirectly()` reads the radios correctly, then
`getAllFormData()` overwrites the key with `getAdditionalFormData()`'s
`this.getPaymentMethod()`, which reads only `this.state`. Nothing writes that state from the
applicant's click — the two writers bind to `.payment-method-option` / `.payment-method-radio`,
which render **0** times — and `showPaymentMethodFallback()` seeds it to `'Bank Transfer'`
because `get_application_form_data()` returns no `payment_methods` key.

Work:

1. Make the applicant's selection the source of truth — bind the radios the page renders,
   or drop the state indirection and let the collector's read stand.
2. **Fold `getAdditionalFormData()` into the collector**, so there is exactly one payload
   builder and no last-writer-wins merge.
3. Extend the ratchet to the merged function. Until this lands, the guard covers the half
   of the payload that does not carry money.

Failing test first: the payload's `payment_method` equals the checked radio; round-trip that
`Member.payment_method` matches the choice.

This phase must also settle `custom_contribution_fee`, because the same merge hides it —
see Phase 5.

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

**[rev]** Two things this phase must also handle:
- `fixtures/custom_html_block.json` ("Page Links") contains `href="/membership_application"`.
  It is a **fixture**, so it re-imports on every migrate — editing the DB is not enough.
- `get_context()` in the surviving `.py` becomes unreachable while
  `tests/backend/portal/test_page_portal_cluster.py:366-385` still asserts its behaviour:
  two tests that can no longer fail for a real reason. Delete `get_context` or label the
  tests as covering a dead entry point. Note only `get_dues_schedules_for_membership_type`
  is `allow_guest` and actually called; the module's other two helpers are
  `@frappe.whitelist()` and unreachable by an applicant.

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

**[rev] Three corrections from review, without which this phase is not mergeable:**

1. `application_helpers.py:582` and `:689` **already default to `"Website"`**. The moment
   the field exists, every applicant who leaves the select blank is recorded as having come
   from the website — inventing exactly the data this spec's Decisions forbid inventing.
   Change the default to `None`.
2. `api/volunteer_application.py:289` sends
   `"Volunteer Application Form (also requested membership)"` into `submit_application`,
   **overwriting** the browser value. A Select whose options do not include that exact
   string throws and takes the volunteer's membership signup with it — the #280 Select
   bug class returning. Either widen the option list or shorten what that caller sends;
   decide in the PR, and cover it with a test.
3. `report/pending_membership_applications/pending_membership_applications.py:120`
   hardcodes `'' as application_source` behind a "Source" column (`:60`). Without updating
   it the new field is invisible to the people who triage applications.

Ratchet baseline 7 → 5.

### Phase 4 — record consent

Add `terms_accepted`, `privacy_accepted` (Check) and `consent_timestamp` (Datetime) to
Member. The collector reads the real `input[name="terms_accepted"]` /
`[name="privacy_accepted"]` controls. Delete `confirm_accuracy`: no element renders it and
nothing validates it, so it is Phase 2's category in disguise.

**No backfill**, and the field descriptions must say so: writing `terms_accepted = 1` for
members who applied before the field existed would fabricate the very evidence the field
exists to hold.

**[rev] A second writer already exists and this phase silently switches it on.**
`utils/csv/csv_data_validator.py:58` maps the Dutch header
`"privacybeleid geaccepteerd" → privacy_accepted`, with a transformer at
`utils/csv/data_transformers.py:68`, consumed by the Mijnrood CSV import — the importer
that produced veg11's 748 members. So consent evidence for existing members may genuinely
exist in the source CSVs, which cuts against a blanket "absence means not recorded". Decide
explicitly in the PR: either accept the importer's value as a real record, or gate it. What
is forbidden is *manufacturing* a value for members who have none.

Ratchet baseline 5 → 2, the survivors being `middle_name` and `payment_method`.

### Phase 5 — migrate the collector to FormData

The prize, and the riskiest step, so it lands last when the field set is already settled.
**Blocked on Phase 0** — until there is one payload builder, converting the collector
converts the half that does not carry money, and `getAdditionalFormData` goes on overriding
it.

Replace the hand-written lookups with `new FormData(document.getElementById('membership-application-form'))`
plus explicit `append()` for genuinely computed values, exactly as the deleted page did.

**[rev] `custom_contribution_fee` must not come from the control of that name.** There are
two amount-bearing controls and their pairing is crossed
(`apply_for_membership.html:405-415`): `id="selected_amount" name="contribution_amount"`
holds the **chosen plan's** amount, while `id/name="custom_contribution_fee"` is filled only
for a custom amount. Today the payload takes
`state.custom_contribution_fee || state.contribution_amount || $('#selected_amount').val()`
— i.e. the chosen amount either way — and `_apply_custom_contribution_fee`
(`application_helpers.py:462-493`) turns it into `Member.dues_rate`. If FormData naively
wins, a standard applicant submits `custom_contribution_fee=""` and their dues rate changes.
An earlier draft of this spec listed the key as both "already agreeing" and "computed": that
contradiction is exactly the bug class this work exists to remove, so the amount stays
**computed and explicit**, and `contribution_amount` is excluded only after the computed
value is proven correct by test.

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

**[rev] "Agree" here means the names match — for two of them that is not the same as
working.** `payment_method` is overridden downstream (#420) and `custom_contribution_fee`
is crossed with `contribution_amount` (below). Both are settled in Phase 0; the remaining
16 are safe to migrate mechanically. Name-level agreement was the measurement, and it is
not evidence of correctness — which is the mistake this spec is documenting elsewhere.

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
| `volunteer_areas[]` | `volunteer_interests` | **computed**, and **broken today** — `getSelectedVolunteerInterests()` reads a container id the page never renders, so it is always `[]`, and the key is read nowhere server-side (#410). Resolve #410 first or drop the key |
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

**[rev] The guard must render both volunteer configurations.** It currently renders only
with `enable_volunteer_signup = 1`, which is `test_site_1`'s setting and not veg11's. Four
more units break under `0`, `additional_notes` among them. A guard that is green only under
a configuration production does not run is the same trap as a green local run against a
bench that has gateway credentials.

## Non-goals

- Server-side **enforcement** of consent. Filed separately; needs every caller enumerated.
- Reviving the enhanced page's UI.
- **[rev]** The duplicated wrong ids in the `BaseStep` subclasses
  (`membership_application.js:~4003`). Only their **`getData()`** is dead: `StepManager` is
  never loaded, so nothing calls it. But `initializeSteps()` *does* instantiate all six
  steps and call `bindEvents()` and `render()` on each, so those are **live** —
  `VolunteerStep.bindEvents()` binds the `#interested_in_volunteering` → `#volunteer-details`
  toggle, and the `#application_source` → `#source-details-container` toggle Phase 3 needs.
  Delete `getData()` only; deleting the rest removes working UI, and Phase 3 gets its toggle
  for free rather than writing a second handler.
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
- **[rev] Rollback is asymmetric for Phases 3 and 4.** Reverting a merged PR reverts the
  DocType JSON but leaves the database column and anything written into it meanwhile.
  Revert means "revert the readers and writers, leave the column"; say so in those PRs.
- **[rev] `submit_application`'s non-browser caller is `api/volunteer_application.py:275-298`**,
  in process, sending 10 keys. It is unaffected by control renames (it sends payload keys),
  but Phase 5's two payload-key renames must be checked against it. `parse_application_data`
  ignores unknown keys, so the "deliberately excluded" list is hygiene, not breakage.

**Checked and dismissed** — recorded so nobody re-investigates: renaming `name` attributes
has no i18n impact (`_()`/`__()` wrap labels, never `name`); `label for=` binds to **id**,
not name, so accessibility survives provided Phase 5 renames names only and never ids; and
there is no draft/localStorage migration, because `storage-service.js` is not loaded on this
page and no draft is ever written.
