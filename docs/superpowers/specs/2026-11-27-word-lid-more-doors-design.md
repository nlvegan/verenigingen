# Design — configurable /word-lid doors: unlisted doors, access codes, fixed-date billing

**Status:** approved by the maintainer, 2026-11-27
**Builds on:** `2026-10-30-short-application-page-design.md` (the `/word-lid` page and
`Membership Application Door`, merged via #2127/#2131)
**Source:** the stakeholder's Procurios field sheet, kept bench-local (not in git) at
`~/frappe-bench/dispatch/requirements/aanmeldformulier-procurios-velden.csv`.

## Principle

**This spec builds settings, not routes.** Nothing in code, fixtures or patches names a door,
a referral source, a membership type, an amount, a date or a consent text. Admins configure all
of that in the Desk. The stakeholder's routes (appendix) are the use case that shows the
settings are sufficient. They are an illustration, not something shipped.

Every new field defaults to today's behaviour, so existing doors are unchanged after migrate.

## Why

The sheet has more entry routes than the doors built in October, and they need things a door
cannot express yet:

| Need | Setting |
|---|---|
| a door reachable only by its link or QR code | `show_on_landing` |
| the route already answers "how did you find us" | `preset_referral_source` |
| only people given a code may use a door, and which code they used is recorded | `access_codes` |
| a door where the IBAN is always required | `require_iban` |
| different consent wording per door | `consent_text` |
| a door with no fee at all | form shape `No payment` |
| billing periods that start on a fixed day of the year, with the fee waived for late joiners | plan `period_anchor` |

## Non-goals

- **Gift membership.** Its own spec. Stakeholder answers so far: the giver need not be a member;
  "1 year then stops" vs "until cancelled" is the giver's choice; **both** giver and recipient
  consent; the recipient gets the magazine, starter guide and the normal acceptance emails.
- **Periodic review** of memberships per type. That is #1733, generalised beyond students.
- **Converting a membership to another type** through `/word-lid`. Re-applying does **not** work
  for this: an active Member gets the "you already have a membership" email with no link.
  Conversion already exists as an admin action: a Contribution Amendment Request of type
  *Membership Type Change* (`contribution_amendment_approval_service.py:382`). What this spec
  must add is in "Fixed-date billing periods" → *Changing type*.
- **The hardcoded "Netherlands"** in `/word-lid` (five sites, including the paper-delivery rule).
  Tracked in #3438.
- Postcode autofill and captcha, as in the October spec.

## Changes to `Membership Application Door`

| Field | Type, default | Behaviour |
|---|---|---|
| `show_on_landing` | Check, **1** | `www/word_lid.py` lists only doors with this on. The door's own URL works either way. |
| `preset_referral_source` | Link → Membership Referral Source, empty | When set, the "how did you find us" question is not rendered. The validator **stores the preset and drops any submitted `referral_source` and `referral_source_other`**, as it does for a hidden question. |
| `access_codes` | Table → new child `Membership Application Door Code` (`code` Data, `label` Data, `enabled` Check), empty | With at least one enabled row, the form shows a required access-code field. See "Access codes". |
| `access_code_label` | Data, empty | Label of the access-code field on the form; empty → a translated default ("Access code"). |
| `access_code_help` | Small Text, empty | Help text under the field. |
| `require_iban` | Check, **0** | IBAN required for every plan on this door. Today only Monthly requires one. |
| `consent_text` | Text Editor, empty | The consent checkbox text. **Required** on a door that collects payment (Regular shape). |
| `form_shape` | Select: add **`No payment`** | See below. |

**Migrating existing doors:** `consent_text` is required on Regular doors, so a patch fills it
on existing Regular doors with the text the template renders today. Otherwise an admin's next
save of an existing door fails. Nothing else needs a patch.

### Form shape `No payment`

Like Regular without the payment block: no plan, amount, IBAN or consent. The delivery
questions are rendered. Submitted payment fields are dropped, not stored.

It is a shape rather than a €0 plan because `_validate_template` refuses a Fixed template whose
rate is 0 or less (`membership_application_door.py:60`), and `_parse_amount` refuses an amount
of 0 or less (`short_application_validation.py:205`). Loosening either would affect every
Regular door.

**Approval still needs a dues template**, so the door's membership type needs a €0 template, as
the October spec did for Huisgenoot. The no-payment path sends no `selected_dues_schedule`, and
approval falls back to the type's template (`short_application_confirm.py:53`). The builder checks
which template that is when a type has several.

Code keyed on `form_shape == "Regular"` that must also accept `No payment`:
- `_clean_delivery` returns early for anything but Regular (`short_application_validation.py:146`);
- `word-lid.html:48-147` renders the delivery questions inside the Regular block;
- `short_application.js` switches on `data-shape`;
- `door_alerts.py:27` decides which doors need a plan (a no-payment door does not).

Paper delivery has no postal minimum on a no-payment door, because there is no amount.

## Access codes

- A code is matched **trimmed and case-insensitively** against the door's **enabled** rows,
  with `hmac.compare_digest`.
- A wrong, disabled or missing code gets **one** translated refusal ("This access code is not
  valid."). The code is checked **before** every other validation, so that refusal is the same
  whatever else is wrong with the form.
- The rate limit (10/h, `api/short_application.py:36`) is per client and does not stop a
  distributed guess. Door validation requires codes of **at least 8 characters**: a security
  floor, not a business rule.
- The staged payload stores the **row name** of the matched code, never the code (payloads are
  kept up to 30 days). **Confirm re-checks that the row is still enabled**, next to the existing
  `chosen_plan_still_on_door` check, because confirmation can come up to 7 days later.
- The row's **label** is stored on the Member as `application_access_code_label` (Data,
  read-only, application section), so a report can show which code someone used. It needs an
  entry in the materialiser's answer fields (`application_materialiser.py`, `_ANSWER_FIELDS`).
- Codes are unique within a door. An admin rotates a code by disabling its row and adding a new
  one. Past Members keep their label.
- The code is a filter, not security: every application is still approved by hand.

## Fixed-date billing periods

New fields on `Membership Application Door Plan`:

| Field | Type, default | Meaning |
|---|---|---|
| `period_anchor` | Select *Join date* / *Fixed date*, **Join date** | Join date = today's behaviour |
| `anchor_month`, `anchor_day` | Int, empty | The day periods start on; required for *Fixed date*, validated as a real date (29 February refused) |
| `waive_final_months` | Int, **0** | Joining within this many months before the next anchor starts the membership at the next anchor, with nothing billed until then |

**Rule.** At approval, take the most recent anchor on or before the approval date. If the next
anchor is within `waive_final_months`, use the next anchor instead. Periods then run from that
anchor as ordinary running periods of the plan's frequency. The reference date is the
**approval** date, because the membership starts at approval.

**This is opt-in anchoring, not calendar billing.** The period calculator and the running-period
policy (CLAUDE.md "The billing model", #207, #884) are unchanged. A plan that does not opt in
behaves as today.

**What has to be built** (approval does not use an anchor today; verified 2026-11-27 by review
and re-checked):

1. **Write the anchor at approval.** The only writer of `coverage_anchor_date` today is
   `reactivate_for_rejoin` (`dues_schedule_lifecycle_service.py:162`). Schedule creation
   (`TemplateCreationService.create_from_template`) must set it for a *Fixed date* plan.
2. **Start approval's first invoice at the anchor.** `create_membership_on_approval` step 5 calls
   `create_membership_invoice_with_amount(..., period_start=None)`, which uses `today()`
   (`application_payments.py:48`). So:
   - anchor **in the past**: pass `period_start = anchor`; one invoice, not prorated, covering
     the full period from the anchor;
   - anchor **in the future**: create **no** invoice at approval (the existing
     `create_invoice=False` path, or a parameter) and leave the first invoice to the scheduler.
     `_floor_at_coverage_anchor` (`coverage_calculator.py:323-336`) starts coverage at the
     anchor, so the waived weeks are not billed as catch-up;
   - the **retry path** (#1900) passes `membership.start_date` as `period_start` and needs the
     same treatment.
3. **The scheduler needs no change** (measured, see "Spike results"). With no invoice and an
   anchor set, the next coverage period starts **at the anchor**, in both directions. Under a
   cutoff before the anchor nothing is generated. Under a cutoff on or after it, the invoice is
   for the period that *begins* at the anchor: ordinary advance billing, the same as any
   member's renewal under that cutoff. The waived weeks are never covered by any invoice. An
   earlier draft had the scheduler skip future anchors; that is dropped.
4. **`renewal_date`.** Approval sets Membership `renewal_date` to approval date + 1 year,
   which does not match periods running from the anchor. Find its readers; if any drives
   billing, notices or status, set it from the anchor-based period end. Otherwise record that it
   is cosmetic. *(Resolved during the build: it is not cosmetic, and approval now moves it for
   a future anchor. See "Build findings"; the spike table's `renewal_date` row below shows the
   state before that change.)*

### Spike results (2026-11-28, test_site_10, real stage → confirm → approve with `create_invoice=False`)

An Annual type at €5, then `coverage_anchor_date` set directly on the schedule (the shortcut the
build replaces):

| | no anchor | anchor today+45 | anchor today−60 |
|---|---|---|---|
| Member status / Membership status | Active / Active | Active / Active | Active / Active |
| `application_payment_status` | empty | empty | empty |
| `check_member_status`, `check_active_membership`, `check_eligibility` | pass | pass | pass |
| `calculate_next_coverage_period` | today → +1y | **anchor** → +1y | **anchor** → +1y |
| `should_generate_for_cutoff_period` with cutoff < anchor | True | **False** | n/a |
| … with cutoff ≥ anchor | True | True | True |
| `renewal_date` | approval + 1y | approval + 1y | approval + 1y |

So an approved member with no invoice is **not** treated as unpaid or inactive; that unknown is
closed. Throwaway test: `verenigingen/tests/integration/test_spike_fixed_anchor.py` in a
discarded worktree (not merged).

**Changing type.** A member on a fixed-date schedule can be moved to another type by a
*Membership Type Change* amendment. That service sets `next_invoice_date` from the effective
date (`contribution_amendment_approval_service.py:538`) and does not touch
`coverage_anchor_date`. The builder checks what a carried-over anchor does to the new type's
schedule, and makes the rule explicit: the anchor follows the **new** type's plan (cleared for a
*Join date* plan). Not established: whether the amendment creates a new schedule or edits the
old one. Read it before choosing where the rule goes.

**Build findings (#3450, 2026-11-28).**
- `renewal_date` is not cosmetic: `process_expired_memberships` expires an Active membership whose
  `renewal_date` is past, and the renewal reminders key on it. It is computed from `start_date` when the
  Membership is created (`set_renewal_date`) and is not recomputed by later saves. For a **future** anchor
  approval therefore moves it to the anchor plus the same number of months it already spans
  (`MembershipCreationService._move_renewal_date_to_anchor`), so a year from approval does not end the
  membership before the period that starts at the anchor is over. A past anchor leaves it alone. Nothing
  extends `renewal_date` when later periods are paid; that is true for every member and is tracked in #3461.
- The type-change amendment **edits the existing schedule** in place (`update_schedule_for_type_change`);
  it creates a new one only when the member has none. The rule is therefore implemented there: an anchor
  that is still **in the future** is cleared and `next_invoice_date` becomes today. A reached anchor is left
  alone: coverage chains from the last invoice, so it no longer changes anything, and a rejoining member's
  anchor (set by `reactivate_for_rejoin`) must not be cleared before its first invoice.
- The anchor is written in `MembershipCreationService` after the schedule step rather than inside
  `create_from_template`, so a created, an existing and a reactivated (rejoin) schedule all get it.
- A future anchor is handled by the approval caller (`_invoice_due_at_approval`), which turns
  `create_invoice` off for it: no invoice, no #1900 failure marker, and the approval mail goes out without
  a payment link. The retry path uses the schedule's anchor as `period_start` when it is on or before the
  membership start.

- Limitation, not fixed: with Verenigingen Settings `enable_sequential_coverage = 0` the coverage
  calculator takes its date-based branch and ignores `coverage_anchor_date`. The setting defaults to on, and
  the existing rejoin anchor has the same limitation.

**Configuration precondition** (no code): a Fixed plan whose rate is below the membership type's
`minimum_amount` is dropped from the door (`door_plans.py:136-146`), and the door alert reports
it.

## Consent record

The consent version is a constant today (`CONSENT_TEXT_VERSION = "2026-10-30"`). With text per
door, store the **text as shown** in the submission payload, and copy it onto the Member as
`application_consent_text` (Small Text) next to `application_consent_at`. A SEPA mandate is only
as good as the record of what was agreed to. `application_consent_version` becomes
`<door slug>:<the door's modified date when the text was shown>`. Doors without consent
(Housemate, No payment) leave all three empty, as Housemate does today.

## Tests (red before green)

**Use values unlike the appendix** (another anchor month, other names and amounts), so a test
cannot pass on a hardcoded value.

- Landing lists only enabled doors with `show_on_landing`. An unlisted door's URL still renders,
  and a disabled one is still 404. Existing doors are listed after migrate (the default is 1).
- Preset referral: the question is not rendered; a submitted `referral_source` and
  `referral_source_other` are dropped and the Member gets the preset. Without a preset,
  behaviour is unchanged.
- Access code: right code (other case, padded) accepted and its label lands on the Member; wrong,
  disabled and missing refused with an **identical** response (message, `success`,
  `_server_messages`), and none stages a submission. A wrong code on an otherwise invalid form
  gets the code refusal. The staged payload contains no code. A code disabled after submit
  refuses the confirm. A door without codes ignores a submitted code. Mutant: an always-True
  matcher must turn a test red.
- `require_iban`: a plan without an IBAN refused on a `require_iban` door and still accepted on a
  door without it.
- No payment: no plan, amount or IBAN required; delivery answers stored; submitted payment fields
  dropped; paper delivery accepted with no amount; approval yields the type's €0 template.
- Consent: the Member carries the door's text and version; two doors with different texts give
  different stored texts; a Regular door without `consent_text` cannot be saved; the patch fills
  existing Regular doors.
- Fixed-date billing, end to end through approval with the approval date frozen, in the site
  timezone (test sites are Asia/Kolkata, CI is UTC). With an anchor of, say, 1 April and
  `waive_final_months` 2:
  - approved mid-May → anchor 1 April, one invoice covering 1 April to 31 March;
  - approved mid-February → anchor next 1 April, **no invoice at approval**; a scheduler run in
    February under a Monthly cutoff generates nothing; under a Yearly cutoff it generates one
    invoice whose coverage **starts on 1 April** (never one covering February–March);
  - approved 31 March → as February; approved 1 April → current period, invoiced now;
  - `waive_final_months` 0 → mid-February is invoiced from the previous 1 April;
  - the retry path (#1900) gives the same coverage as approval;
  - the next period chains on from the anchor;
  - the member approved in February is active and not marked unpaid before the anchor.
- A *Membership Type Change* from a fixed-date type to a join-date type leaves no anchor
  behind: the next invoice runs from the change, not from the old fixed date.
- A *Join date* plan behaves exactly as before (regression).
- Door validation: *Fixed date* without a valid month/day refused; a duplicate code within a door
  refused; a code shorter than 8 characters refused.

## Tracker

- #884: commented (2026-11-27) that fixed-date anchoring is an opt-in plan setting, not a
  regression of the running-period fix.
- #1733: commented (2026-11-27) that periodic review should be per membership type.
- #3438: the five "Netherlands" hardcodes in `/word-lid`.
- No conversion issue: type change exists as an amendment; the anchor rule is in this spec.
- Still to do: the gift membership spec, after the open questions in "Non-goals" are settled.

## Appendix: how the sheet's routes would be configured (illustration, not shipped)

| Sheet column | Door settings |
|---|---|
| `VC-cont` | Regular, not on landing, preset referral = the VeganChallenge source* |
| `event` / `stand` | one door: Regular, not on landing, preset referral = the stand source* |
| `VSA` | Regular, not on landing, `require_iban`, one access code per local VSA (label = the VSA), one Fixed Annual plan with *Fixed date* 1 September and `waive_final_months` 2, magazine and starter guide hidden, the VSA consent text from the sheet |
| `KB` | No payment, not on landing, access codes, a type with a €0 template |

\* The sheet's `VC-cont`, `event` and `stand` columns are empty, so "same questions as Regulier"
is an assumption to confirm with the stakeholder. It changes configuration, not this design.
