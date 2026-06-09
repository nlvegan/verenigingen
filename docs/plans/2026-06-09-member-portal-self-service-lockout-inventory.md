# Member-portal self-service lockout — inventory (2026-06-09)

## The problem

Real members carry exactly one role profile: **"Verenigingen Member"**, which the
authorization policy grants only `SecurityLevel.LOW`
(`utils/security/authorization_policy.py:91`). Assigned in production at
`services/member/account/member_role_service.py:73`,
`member_user_account_service.py:773`, `account_creation_api.py`.

The framework's `@self_service_api` decorator (`utils/security/api_security_framework.py:1157`)
is the intended decorator for "endpoints a user can only invoke on their OWN data" —
it runs at **LOW** and enforces ownership via `SelfServiceAccessController`, so plain
members pass. The donation/fee portal already uses it correctly
(`manage_donations.py`, `membership_adjustment.py` submit_* endpoints).

Many other member self-service endpoints were instead decorated `@standard_api`
(MEDIUM), `@high_security_api` (HIGH), or `@critical_api` (CRITICAL). A plain member
**cannot pass** those, so the feature throws
`PermissionError: Access denied. Required: medium/high/critical. Your profiles:
['Verenigingen Member']` and the portal action silently fails.

**Fix pattern (per endpoint):** swap the elevated decorator for
`@self_service_api(operation_type=OperationType.<MEMBER_DATA|FINANCIAL>, implicit_allowed=True)`
(keep `@frappe.whitelist()` outermost). `implicit_allowed=True` is required for the
portal endpoints that derive the member from `frappe.session.user` with no explicit
`member=` argument. Each one already does its own ownership check internally, so this
is a tightening-consistent change, not a loosening.

---

## A. BROKEN for plain members — needs `@self_service_api` (the work)

All confirmed to derive the member from the session.

### Portal pages (`verenigingen/templates/pages/`)

| File | Endpoint | Current decorator | Feature |
|------|----------|-------------------|---------|
| `address_change.py` | `update_member_address` | `@standard_api(MEMBER_DATA)` | Change own address |
| `address_change.py` | `get_current_address` | `@standard_api(MEMBER_DATA)` | Read own address |
| `my_dues_schedule.py` | `export_schedule` | `@standard_api(MEMBER_DATA)` | Export own dues CSV |
| `my_dues_schedule.py` | `get_payment_details` | `@standard_api(MEMBER_DATA)` | Own payment detail |
| `my_dues_schedule.py` | `update_notification_settings` | `@standard_api(MEMBER_DATA)` | Own notification prefs |
| `membership_adjustment.py` | `get_fee_calculation_info` | `@standard_api(MEMBER_DATA)` | Fee calc for own change |
| `membership_adjustment.py` | `get_available_membership_types` | `@standard_api(MEMBER_DATA)` | Options for own change |
| `contact_request.py` | `submit_contact_request` | `@standard_api(MEMBER_DATA)` | Member contact form |

### Member API (`verenigingen/api/`)

| File | Endpoint | Current decorator | Feature |
|------|----------|-------------------|---------|
| `member/sepa_api.py` | `get_active_sepa_mandate` | `@high_security_api(FINANCIAL)` | View own SEPA mandate (also @deprecated) |
| `member/sepa_api.py` | `refresh_sepa_mandates` | `@high_security_api(FINANCIAL)` | Refresh own mandate table |
| `member/sepa_api.py` | `setup_sepa_direct_debit` | `@critical_api(FINANCIAL)` | Set up own direct debit |
| `member/sepa_api.py` | `create_and_link_mandate_enhanced` | `@critical_api(FINANCIAL)` | Create own mandate |
| `member/sepa_api.py` | `validate_mandate_creation` | `@critical_api(FINANCIAL)` | Validate own mandate |
| `member/sepa_api.py` | `deactivate_old_sepa_mandates` | `@critical_api(FINANCIAL)` | Replace own mandate |
| `member/sepa_api.py` | `derive_bic_from_iban` | `@high_security_api(FINANCIAL)` | IBAN→BIC helper |
| `payment_plan_management.py` | `request_payment_plan` | `@critical_api(FINANCIAL)` | Request own payment plan |
| `payment_plan_management.py` | `get_member_payment_plans` | `@standard_api(FINANCIAL)` | View own payment plans |
| `payment_plan_management.py` | `calculate_payment_plan_preview` | `@standard_api(FINANCIAL)` | Preview own plan |
| `chapter_join.py` | `get_chapter_join_context` | `@standard_api(MEMBER_DATA)` | Join-chapter page data |
| `chapter_join.py` | `join_chapter` | `@standard_api(MEMBER_DATA)` | Join a chapter |
| `chapter_join.py` | `get_user_chapter_requests` | `@standard_api(MEMBER_DATA)` | Own chapter requests |
| `mollie_payment.py` | `get_subscription_details` | `@high_security_api(MEMBER_DATA)` | View own Mollie subscription |
| `mollie_payment.py` | `cancel_specific_subscription` | `@high_security_api(FINANCIAL)` | Cancel own subscription |
| `mollie_payment.py` | `update_mollie_bank_account` | `@critical_api(FINANCIAL)` | Update own bank account |

**VERIFY before changing** (member-facing intent likely, but sensitive — confirm the
caller is the member and not a payment-callback/admin path):
`mollie_payment.py:create_payment`, `mollie_payment.py:get_payment_status`
(both `@critical_api(FINANCIAL)` — may be payment-initiation flow rather than portal).

---

## B. Already correct (works for members) — reference for the fix

- `manage_donations.py`: `cancel_recurring_donation`, `update_recurring_donation`,
  `get_donation_stats` → `@self_service_api(FINANCIAL, implicit_allowed=True)`.
- `membership_adjustment.py`: `submit_fee_adjustment_request`,
  `submit_membership_type_change_request` → `@self_service_api(FINANCIAL, implicit_allowed=True)`.
- `auth_hooks.py:257` → `@self_service_api(MEMBER_DATA, implicit_allowed=True)`.
- `personal_details.py:update_personal_details` → `@frappe.whitelist(allow_guest=False)`
  with a manual ownership check (works, but inconsistent — could move to `@self_service_api`).
- `member_portal.py:get_context` and the page `get_context`/`setup_portal_context`
  handlers — no framework level gate, render fine.

## C. Correctly elevated — NOT member portal, leave as-is

Admin/staff/treasurer tools that should require MEDIUM+: `admin_tools.py`,
`dues_schedule_admin.py`, `chapter_dashboard.py` (board), all `mollie_*`/`ponto_api_debug`
debug pages, `workflow_demo.py`.

## D. Public — leave as-is

`donate.py:submit_donation`/`retry_payment`, `membership_application.py:*`,
`payment_success.py:refresh_payment_status` → `@public_api`.

> Side note (not member-lockout): `donate.py` contains ~13 undecorated `test_*`/`debug_*`
> whitelisted functions in a production page file — a separate cleanup.

---

## Suggested remediation order

1. **Profile/address basics** (highest member impact, lowest risk): `address_change.py` ×2,
   `my_dues_schedule.py` ×3, `membership_adjustment.py` ×2 read helpers, `contact_request.py`.
2. **SEPA / bank details** (`api/member/sepa_api.py`): the whole own-mandate lifecycle —
   members currently cannot set up or view their own direct debit via the portal.
3. **Payment plans & chapter join** (`payment_plan_management.py`, `chapter_join.py`).
4. **Mollie subscription self-management** (`mollie_payment.py`) — after verifying intent.

Each change is a one-line decorator swap + import; add a member-as-self integration
test per endpoint (pattern: `tests/workflows/test_portal_functionality_integration.py`,
which assigns the "Verenigingen Member" role profile and calls as that user).
