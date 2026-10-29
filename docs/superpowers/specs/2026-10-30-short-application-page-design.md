# Design — short membership application page ("word lid")

**Status:** draft, awaiting maintainer approval
**Leaves alone:** `/apply_for_membership` and `api/membership_application.submit_application`

## Why

The association's current sign-up (Procurios, `wordlid.veganisme.org`) is a short, single-page
form reached through a landing page that asks *what kind of member are you becoming*. The
in-app `/apply_for_membership` is a long 5–6 step wizard (1578-line template, 4457-line JS) that
asks for more than the association wants to ask up front. The stakeholder wants the Procurios
shape: a landing page with doors, one short form per door, an email confirmation, then manual
approval. The existing wizard stays as it is for now.

## Goals

1. A public landing page with three **doors**: Regulier, Student, Huisgenoot.
2. Per door, one short single-page form asking the same questions as the Procurios forms
   (listed below).
3. **Email confirmation** before an application reaches the approval queue.
4. Confirmed applications enter the **existing** manual approval flow unchanged: an admin
   approves, and approval creates the Membership, dues schedule and first invoice as today
   (`MembershipCreationService.create_membership_on_approval`).
5. Doors are **admin-managed records**: text, order, membership type, amount options and
   hidden optional questions are edited in the Desk, not in code.

## Non-goals (this version)

- **Gift membership** (cadeaulidmaatschap). Dropped by the maintainer; a third party paying is
  the part that would touch the billing code.
- **Welcome email and the follow-up email ~2 days later** asking the extra questions. A later
  phase. The extra-information questions stay on the form for now.
- **Periodic re-approval of student memberships.** The reason Student is its own type, but a
  separate feature; Membership Type has no such mechanism today. File it as its own issue.
- **Postcode → street/city autofill.** Procurios has it; no lookup exists in this app. Manual
  entry in v1 *(my call; easy follow-up)*.
- **Captcha.** Honeypot + rate limit only *(my call; approval is manual anyway)*.
- Krappe beurs (reduced-budget) stays an email-to-admin process; no door.

## Anti-goals

- Changing the behaviour of `/apply_for_membership` or `submit_application`. Shared helpers may
  be reused; if one has to change, the old page's tests must stay green.
- Creating Member / Address / Customer rows for **unconfirmed** submissions.
- A GET request with side effects on the confirmation link (mail scanners prefetch links).
- Doors that list Membership Types directly. A door is a curated record pointing at a type.

## The doors

| Door | Membership Type | Form shape | Payment |
|---|---|---|---|
| Regulier | `Lid` | Regular | monthly or yearly, amount tiers or own amount |
| Student | a real Student type (to be set up; veg11's `Student` / `Student Member` are demo data with min €50 > rate €15) | Regular (same questions) | own amounts |
| Huisgenoot | `Huisgenootlid` (min €0; defined in `setup/__init__.py:1473` but **absent on veg11**) | Housemate | none |

Creating/fixing these three types and their dues templates on veg11 is configuration, done by an
admin; the amounts are the association's to set.

**Huisgenoot still needs a dues template.** Approval throws if neither the type's
`dues_schedule_template` nor the Member's `application_dues_schedule` is set
(`membership_creation_service.py` `_validate_and_get_membership_type`). So `Huisgenootlid` gets
an Annual **€0 template** as configuration, and approval stays unchanged *(my call)*. The builder
checks whether approval then creates a €0 first invoice. If it does, that is accepted for v1 and
noted in the PR; changing approval to skip it is out of scope.

### Door DocType: `Membership Application Door` *(name: my call)*

| Field | Type | Notes |
|---|---|---|
| `title` | Data | Shown on the door card and as the form heading |
| `slug` | Data, unique | `[a-z0-9-]+`; URL part |
| `enabled` | Check | Disabled/unknown slug → 404 |
| `sort_order` | Int | Landing page order |
| `card_text` | Text Editor | Short text on the landing page card |
| `intro_text` | Text Editor | Above the form |
| `membership_type` | Link Membership Type | |
| `form_shape` | Select: Regular / Housemate | |
| `monthly_dues_template`, `annual_dues_template` | Link Membership Dues Schedule | Regular shape only. Validate: `is_template=1` and `membership_type` matches. Either may be empty → that frequency is not offered |
| `amount_options` | Table → `Membership Application Door Amount` (`frequency` Monthly/Annual, `amount` Currency) | The tier buttons, e.g. 15/12/9/6 and 180/144/96/60 |
| `allow_custom_amount` | Check | "Eigen keuze" |
| `postal_minimum_monthly`, `postal_minimum_annual` | Currency | Higher minimum when magazine and/or starter guide go by post (Procurios: €3 / €36; otherwise the template minimum, e.g. €2.50 / €20) |
| `hidden_questions` | Table MultiSelect over a **fixed list of optional questions** | So the stakeholder can drop questions per door later without code. Required fields are never in the list |

Permissions: System Manager / Verenigingen Administrator write. Guests never read the DocType;
they see what the page renders.

## The forms (Procurios parity)

**Regular shape** (Regulier, Student), one page, three blocks:

1. *Mijn keuzes* — payment frequency (monthly default, checkbox for yearly; only frequencies the
   door has a template for); amount (door tiers + own amount if allowed); magazine delivery
   (Digitaal / Papier / Beide / Geen); starter guide delivery (same four).
2. *Mijn gegevens* — first name\*, tussenvoegsel, last name\*, address\* (postcode, house number,
   addition, street, city, country), email\*, mobile (optional, with country code), IBAN, account
   holder name. Consent\*: 12-month minimum, and direct-debit authorisation when an IBAN is given.
3. *Extra informatie* (optional) — birth year; up to 5 reasons for joining (+ "other" text); how
   you found us (single choice + "other" text).

Rules, all enforced **server-side** (the client mirrors them for UX only):
- Monthly requires an IBAN (direct debit). Yearly without IBAN → pays by transfer / payment
  request, mapped through the existing `map_payment_method`.
- Amount ≥ the chosen template's `minimum_amount`, and ≥ the door's postal minimum when either
  delivery choice includes Papier.
- Non-NL address → Papier/Beide not allowed for magazine and starter guide.
- `selected_dues_schedule` must be the door's template for the chosen frequency (approval
  re-checks this anyway in `_resolve_dues_template`).
- **Every chosen amount, tier or own, is sent as `custom_contribution_fee`** *(my call)*. That is
  the only way an amount reaches the dues schedule: approval reads `member.dues_rate`, which only
  `_apply_custom_contribution_fee` sets. The old form does the same. Use the reason text
  "Bedrag gekozen bij aanmelding (<door>)".
- **Payment method values:** `sepa_direct_debit` when an IBAN is given, else `bank_transfer`
  (keys of `PAYMENT_METHOD_MAP`, `application_helpers.py:159`). What happens next (mandate,
  payment request) is whatever the existing approval path does for those values today. The new
  page matches it and does not extend it.
- **Consent record** *(my call)*: store `consent_given_at` (datetime) and `consent_text_version`
  in the submission payload, and copy them onto Member (`application_consent_at`,
  `application_consent_version`). The IBAN, account holder and consent date are what a SEPA
  Mandate needs later (`sign_date`). Whether the old flow creates a mandate automatically or an
  admin does, the new page leaves that unchanged.

**Housemate shape:** *Mijn gegevens* (as above, no IBAN/consent/amount), *paying member at my
address*: full name\* (free text) and a required checkbox confirming a paying member lives at the
address; then the same *Extra informatie* block. The admin checks the paying member during
approval *(maintainer-confirmed guess)*.

**Date of birth:** the old endpoint requires a full `birth_date`; this form asks only an
optional birth **year**. The builder must check that nothing downstream of
`create_member_from_application` / Member validation / approval needs `birth_date` (age checks,
validations) and handle an empty one.

## Where the new answers live *(my call)*

New fields on **Member** (application section unless noted):
- `magazine_delivery`, `starter_guide_delivery` — Select (Digitaal/Papier/Beide/Geen). Magazine
  is an ongoing preference, so it belongs on Member, not the submission.
- `birth_year` — Int.
- `join_reasons` — Table MultiSelect → new master `Membership Join Reason` (admin-editable
  options, seeded with the 12 Procurios reasons); `join_reason_other` — Data.
- `referral_source` — Link → new master `Membership Referral Source` (seeded with the 7 Procurios
  options); `referral_source_other` — Data.
- `housemate_of_name` — Data; `application_door` — Link to the door (reporting: which door).

Masters rather than Select options so the follow-up-email phase and the stakeholder can change
options without a deploy.

## Flow

```
landing /word-lid ──door──▶ /word-lid/<slug> form ──POST──▶ submission (Unconfirmed)
                                                            │ email with confirm link
                              /word-lid/bevestig?id&token ◀─┘
                              page shows a "Bevestig" button ──POST──▶ confirm:
                                  create Address + Member (application_status Pending)
                                  → existing approval queue
```

*(routes: my call; Dutch because the audience is.)* Routing: a page under `templates/pages/` plus
a `website_route_rules` entry for `/word-lid/<door>`; no route rules exist in `verenigingen/hooks/`
yet.

### Submission staging DocType: `Membership Application Submission` *(my call)*

Why a staging record: unconfirmed (incl. bot) submissions must not create Members, Addresses or
Customers.

Fields: `door` (Link), `email`, `payload` (JSON, the validated form data), `status`
(Unconfirmed / Confirmed / Expired), `confirmed_on`, `member` (Link, set on confirm),
`submitted_ip` *(optional, builder's call)*.

- **Submit endpoint** (new, `allow_guest`): validate everything above, store the submission,
  send the confirmation email. Use the same security decorator stack as `submit_application`
  (`@public_api`), plus a honeypot field and a rate limit. Validation is the new rules in this
  document. Reuse the old shared validators only if they pass the short payload **unchanged**
  (they may require `birth_date`). Otherwise write a new validator, and do not edit theirs.
- **An email that already belongs to a Member** *(my call; behaves like the old endpoint, without
  revealing anything)*:
  - The submit response is **always** "check your email". It never reveals whether the email is
    known.
  - The email sent differs. For a status the old endpoint lets reapply (`_handle_existing_member`
    in `api/membership_application.py`: application Rejected, application Pending, or Quit after
    an executed termination), the normal confirmation link goes out. Otherwise (active member,
    etc.) the email says "you already have a membership; contact us" and contains no link.
  - On confirm, a reapplication **updates the existing Member** the way the old flow does
    (`update_member_from_reapplication`), instead of creating a second one. The new fields and
    `application_door` are **overwritten** with the latest answers. Prior values remain
    in the Version history.
- **Token:** `generate_guest_return_token("application_email_confirmation", submission.name)`
  (`utils/security/guest_return_tokens.py`). That helper has no expiry, so expiry is enforced by
  the submission: Unconfirmed older than **7 days** → refuse and mark Expired *(my call)*.
- **Confirm endpoint** (POST only): verify token, status Unconfirmed and not expired; re-run the
  existing-member check (someone may have applied through another route meanwhile; route a
  reapplication to the update path above); then, in one
  transaction, `create_address_from_application` + `create_member_from_application` with the
  payload mapped to the keys they expect (`selected_membership_type`, `selected_dues_schedule`,
  `custom_contribution_fee`, `payment_method`, `iban`, …), set the new Member fields, run chapter
  suggestion by postcode as the old flow does, set `status=Confirmed`, `member=…`. Confirming
  twice is idempotent: show "already confirmed", create nothing.
- **Refusals look identical** for unknown id, wrong token, expired and already-confirmed where
  they would otherwise leak whether an email applied (compare message, status code, response
  shape, `_server_messages`).
- **Daily job:** delete Unconfirmed/Expired submissions older than 30 days (PII minimisation)
  *(my call)*.
- After confirming, the page says the application is received and will be reviewed. Whether an
  "application received" email also goes out: mirror what the old flow does today *(builder
  checks)*.

## Reuse map

| Need | Existing code |
|---|---|
| Create Address / Member | `services/member/approval/application_helpers.py` (`create_address_from_application`, `create_member_from_application` :609) |
| Custom amount validation | `validate_custom_amount_util`, `_apply_custom_contribution_fee` (:520) |
| Payment method mapping | `map_payment_method` |
| IBAN validation | `services/payment/validation_service.py` `validate_iban_api` |
| Signed guest link | `utils/security/guest_return_tokens.py` |
| Approval (unchanged) | `MembershipCreationService.create_membership_on_approval`, honours `application_dues_schedule` |
| Branding | Brand Settings (logo, colours) as `/apply_for_membership` uses them |

## Tests (red before green, per CLAUDE.md)

- Landing lists enabled doors in `sort_order`; disabled/unknown slug → 404.
- Submit: each server rule above rejected when violated (monthly without IBAN, amount under
  template minimum, under postal minimum with Papier, Papier with non-NL address, wrong template
  for door, missing required field, missing consent, housemate without payer name/checkbox);
  hidden question values ignored; honeypot filled → refused without a submission row.
- Submit creates **no** Member/Address/Customer; only a submission + one email.
- Submit with an email that belongs to an active Member returns the **same response** as a new
  email (compare status, message, response shape and `_server_messages`), and sends the
  no-link email. A reapplication-eligible Member confirms into an update of that Member, not a
  second Member.
- A tier amount and an own amount both arrive as the dues schedule's rate after approval.
- The consent timestamp and version are on the Member after confirmation.
- Confirm: wrong token / unknown id / expired / already confirmed refused **identically**;
  GET does nothing; valid POST creates exactly one Member (Pending) + Address with the new fields
  and `application_dues_schedule` set; second POST creates nothing.
- Approval of a confirmed Regulier application with the monthly template yields a Monthly dues
  schedule at the chosen amount (end-to-end through the unchanged approval service).
- Door validation: template of another type refused; required field cannot be hidden.
- Old `/apply_for_membership` test modules unchanged and green.

## Left to the builder

Page markup and styling (Tailwind, like the current page); exact email text (Dutch, `_()`
wrapped); module placement; the fixed list of hideable questions; seeding the two masters
(fixtures vs. patch); whether the form posts via `frappe.call` or a plain fetch; where the
`website_route_rules` entry goes so that the `verenigingen/hooks/` package actually loads it
(check how `hooks/__init__.py` assembles the hook dict).

## Follow-ups to file

- Student periodic re-approval.
- Welcome email + 2-day follow-up email (moves the extra questions out of the form).
- Postcode autofill.
