"""
MijnRood Database → Verenigingen Field Mapping Constants

Maps MijnRood MariaDB column names (camelCase) to Verenigingen Member DocType fields.
Reuses the same target field names as the CSV import (csv_data_validator.py FIELD_MAPPING)
so the MemberImportService.update_member_fields() method works for both sources.

MijnRood status IDs are mapped via MIJNROOD_STATUS_MAP to the same status strings
that MemberImportService.STATUS_MAP expects (e.g. "lid", "opgezegd").
"""

# Columns to include in MD5 checksum for each MijnRood table.
# Order matters for checksum consistency — do not reorder.
MEMBER_COLUMNS = [
    "id",
    "firstName",
    "middleName",
    "lastName",
    "email",
    "phone",
    "iban",
    "address",
    "city",
    "postCode",
    "country",
    "dateOfBirth",
    "division_id",
    "registrationTime",
    "currentMembershipStatus_id",
    "contributionPeriod",
    "contributionPerPeriodInCents",
    "mollieCustomerId",
    "mollieSubscriptionId",
    "comments",
]

SUPPORT_MEMBER_COLUMNS = [
    "id",
    "firstName",
    "middleName",
    "lastName",
    "email",
    "phone",
    "iban",
    "address",
    "city",
    "postCode",
    "country",
    "dateOfBirth",
    "contributionPeriod",
    "contributionPerPeriodInCents",
    "mollieCustomerId",
    "mollieSubscriptionId",
]

# Mapping of MijnRood table name → column list for checksum computation
TABLE_COLUMNS = {
    "admin_member": MEMBER_COLUMNS,
    "admin_support_member": SUPPORT_MEMBER_COLUMNS,
    # Additional tables use SELECT * (all columns) when not listed here
}

# Primary key column name per table (MijnRood uses 'id' for all known tables)
TABLE_PRIMARY_KEY = {
    "admin_member": "id",
    "admin_support_member": "id",
    "admin_membership_application": "id",
    "admin_contribution_payment": "id",
    "admin_division": "id",
    "admin_membershipstatus": "id",
}

# Whitelist of allowed table names — used by client.py to prevent SQL injection.
# Built from TABLE_PRIMARY_KEY keys so any new table must be registered there first.
ALLOWED_TABLES = frozenset(TABLE_PRIMARY_KEY.keys())

# ─────────────────────────────────────────────────────────────────────
# MijnRood DB column → Verenigingen intermediate field name
# These intermediate names match csv_data_validator.py FIELD_MAPPING values
# so that MemberImportService.update_member_fields() can consume them.
# ─────────────────────────────────────────────────────────────────────
MIJNROOD_TO_MEMBER_FIELD_MAP = {
    "id": "member_id",
    "firstName": "first_name",
    "middleName": "tussenvoegsel",
    "lastName": "last_name",
    "email": "email",
    "phone": "contact_number",
    "iban": "iban",
    "dateOfBirth": "birth_date",
    "registrationTime": "member_since",
    "address": "address_line1",
    "city": "city",
    "postCode": "postal_code",
    "country": "country",
    "division_id": "chapter",
    "currentMembershipStatus_id": "membership_type",
    "contributionPeriod": "payment_period",
    "contributionPerPeriodInCents": "dues_rate",
    "mollieCustomerId": "custom_mollie_customer_id",
    "mollieSubscriptionId": "custom_mollie_subscription_id",
}

# ─────────────────────────────────────────────────────────────────────
# MijnRood currentMembershipStatus_id → membership type string
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
# MijnRood contributionPeriod → billing frequency
# Matches data_transformers.map_payment_period_to_billing_frequency()
# ─────────────────────────────────────────────────────────────────────
CONTRIBUTION_PERIOD_MAP = {
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "yearly": "Yearly",
    "annually": "Yearly",
}
