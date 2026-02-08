"""
MijnRood Database → Verenigingen Field Mapping Constants

Maps MijnRood MariaDB column names (snake_case) to Verenigingen Member DocType fields.
Reuses the same target field names as the CSV import (csv_data_validator.py FIELD_MAPPING)
so the MemberImportService.update_member_fields() method works for both sources.

MijnRood status IDs are mapped via MIJNROOD_STATUS_MAP to the same status strings
that MemberImportService.STATUS_MAP expects (e.g. "lid", "opgezegd").
"""

# Columns to include in MD5 checksum for each MijnRood table.
# Order matters for checksum consistency — do not reorder.
# NOTE: Sensitive columns (password_hash, new_password_token, etc.) are
# deliberately excluded — they add noise (checksum changes on password resets)
# and should never be synced.
MEMBER_COLUMNS = [
    "id",
    "first_name",
    "middle_name",
    "last_name",
    "email",
    "phone",
    "iban",
    "address",
    "city",
    "post_code",
    "country",
    "date_of_birth",
    "division_id",
    "registration_time",
    "current_membership_status_id",
    "contribution_per_period_in_cents",
    "mollie_customer_id",
    "mollie_subscription_id",
    "roles",
    "accept_use_personal_information",
    "comments",
]

SUPPORT_MEMBER_COLUMNS = [
    "id",
    "first_name",
    "last_name",
    "email",
    "phone",
    "iban",
    "address",
    "city",
    "post_code",
    "country",
    "date_of_birth",
    "registration_time",
    "mollie_customer_id",
    "mollie_subscription_id",
    "contribution_per_period_in_cents",
    "original_id",
    "original_registration_time",
]

DIVISION_COLUMNS = [
    "id",
    "name",
    "email_id",
    "phone",
    "city",
    "address",
    "post_code",
    "facebook",
    "instagram",
    "twitter",
    "can_be_selected_on_application",
]

MEMBERSHIP_APPLICATION_COLUMNS = [
    "id",
    "preferred_division_id",
    "first_name",
    "middle_name",
    "last_name",
    "email",
    "phone",
    "iban",
    "address",
    "city",
    "post_code",
    "country",
    "date_of_birth",
    "registration_time",
    "contribution_per_period_in_cents",
    "mollie_customer_id",
    "paid",
    "has_sent_initial_email",
]

# Mapping of MijnRood table name → column list for checksum computation
TABLE_COLUMNS = {
    "admin_member": MEMBER_COLUMNS,
    "admin_support_member": SUPPORT_MEMBER_COLUMNS,
    "admin_division": DIVISION_COLUMNS,
    "admin_membership_application": MEMBERSHIP_APPLICATION_COLUMNS,
}

# Primary key column name per table (MijnRood uses 'id' for all known tables)
TABLE_PRIMARY_KEY = {
    "admin_member": "id",
    "admin_support_member": "id",
    "admin_membership_application": "id",
    "admin_division": "id",
}

# Whitelist of allowed table names — used by client.py to prevent SQL injection.
# Built from TABLE_PRIMARY_KEY keys so any new table must be registered there first.
# NOTE: admin_contribution_payment and admin_membershipstatus are excluded:
# - admin_membershipstatus is a static lookup (6 rows), hardcoded in MIJNROOD_STATUS_ID_MAP
# - admin_contribution_payment has no event handler and generates excessive noise (2400+ rows)
# These can be re-added once proper event handlers exist for them.
ALLOWED_TABLES = frozenset(TABLE_PRIMARY_KEY.keys())

# ─────────────────────────────────────────────────────────────────────
# MijnRood DB column → Verenigingen intermediate field name
# These intermediate names match csv_data_validator.py FIELD_MAPPING values
# so that MemberImportService.update_member_fields() can consume them.
# ─────────────────────────────────────────────────────────────────────
MIJNROOD_TO_MEMBER_FIELD_MAP = {
    "id": "member_id",
    "first_name": "first_name",
    "middle_name": "tussenvoegsel",
    "last_name": "last_name",
    "email": "email",
    "phone": "contact_number",
    "iban": "iban",
    "date_of_birth": "birth_date",
    "registration_time": "member_since",
    "address": "address_line1",
    "city": "city",
    "post_code": "postal_code",
    "country": "country",
    "division_id": "chapter",
    "current_membership_status_id": "membership_type",
    "contribution_per_period_in_cents": "dues_rate",
    "mollie_customer_id": "custom_mollie_customer_id",
    "mollie_subscription_id": "custom_mollie_subscription_id",
}

# ─────────────────────────────────────────────────────────────────────
# MijnRood current_membership_status_id → membership type string
# These strings must match MemberImportService.STATUS_MAP keys
# so that determine_member_status() returns the correct status.
# ─────────────────────────────────────────────────────────────────────
MIJNROOD_STATUS_ID_MAP = {
    1: "lid",  # Active member
    2: "aspirant",  # Aspirant member
    3: "opgezegd",  # Resigned / terminated
    4: "geroyeerd",  # Expelled
    5: "overleden",  # Deceased
    6: "geschorst",  # Suspended
}

# Status IDs that indicate the member is no longer active.
# When a status change TO one of these is detected, the event application
# service creates a Membership Termination Request instead of directly
# setting the member status.
TERMINATED_STATUS_IDS = frozenset([3, 4, 5, 6])

# Status IDs that are considered active (no termination needed)
ACTIVE_STATUS_IDS = frozenset([1, 2])

# ─────────────────────────────────────────────────────────────────────
# MijnRood status ID → termination type for Membership Termination Request
# ─────────────────────────────────────────────────────────────────────
STATUS_ID_TO_TERMINATION_TYPE = {
    3: "Voluntary",  # opgezegd → Voluntary resignation
    4: "Disciplinary Action",  # geroyeerd → Expelled
    5: "Deceased",  # overleden
    6: "Policy Violation",  # geschorst → Suspended
}

# Human-readable label for MijnRood status IDs (for change summaries)
STATUS_ID_LABELS = {
    1: "Active (lid)",
    2: "Aspirant",
    3: "Resigned (opgezegd)",
    4: "Expelled (geroyeerd)",
    5: "Deceased (overleden)",
    6: "Suspended (geschorst)",
}

# ─────────────────────────────────────────────────────────────────────
# Human-readable display labels for MijnRood column names
# Used by the client-side diff table to show friendly field names
# instead of raw database column names.
# ─────────────────────────────────────────────────────────────────────
MIJNROOD_FIELD_LABELS = {
    # admin_member columns
    "id": "MijnRood ID",
    "first_name": "First Name",
    "middle_name": "Middle Name",
    "last_name": "Last Name",
    "email": "Email",
    "phone": "Phone",
    "iban": "IBAN",
    "address": "Address",
    "city": "City",
    "post_code": "Postal Code",
    "country": "Country",
    "date_of_birth": "Date of Birth",
    "division_id": "Chapter",
    "registration_time": "Registration Date",
    "current_membership_status_id": "Membership Status",
    "contribution_per_period_in_cents": "Contribution (cents/period)",
    "mollie_customer_id": "Mollie Customer ID",
    "mollie_subscription_id": "Mollie Subscription ID",
    "roles": "Roles",
    "accept_use_personal_information": "Privacy Consent",
    "comments": "Comments",
    # admin_support_member extra columns
    "original_id": "Original Member ID",
    "original_registration_time": "Original Registration Date",
    # admin_division columns
    "name": "Division Name",
    "email_id": "Division Email",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "twitter": "Twitter",
    "can_be_selected_on_application": "Selectable on Application",
    # admin_membership_application extra columns
    "preferred_division_id": "Preferred Chapter",
    "paid": "Paid",
    "has_sent_initial_email": "Initial Email Sent",
}
