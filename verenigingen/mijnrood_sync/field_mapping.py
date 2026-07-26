"""
MijnRood Database → Verenigingen Field Mapping Constants

Maps MijnRood MariaDB column names (snake_case) to Verenigingen Member DocType fields.
Reuses the same target field names as the CSV import (csv_data_validator.py FIELD_MAPPING)
so the MemberImportService.update_member_fields() method works for both sources.

MijnRood status IDs are mapped via MIJNROOD_STATUS_MAP to the same status strings
that MemberImportService.STATUS_MAP expects (e.g. "lid", "opgezegd").
"""

from verenigingen.utils.constants import Roles

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
    "contribution_period",
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
    "contribution_period",
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
    "contribution_period",
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
    # contribution_per_period_in_cents is NOT mapped here — it needs a cents→euros
    # conversion, done in mapping_service.map_member_fields(). Mapping it raw as
    # well meant the unconverted value won whenever the conversion was skipped,
    # i.e. exactly when cents == 0, which turned MijnRood's "no custom amount"
    # into a literal €0 dues rate (observed on MR-SYNC-2026-00087: €9.00 → €0.00).
    # contribution_period is NOT mapped here — it requires integer→string
    # conversion handled by _map_mijnrood_to_member_fields() custom logic.
    "mollie_customer_id": "custom_mollie_customer_id",
    "mollie_subscription_id": "custom_mollie_subscription_id",
    "accept_use_personal_information": "accepts_optional_communications",
    "comments": "mijnrood_comments",
}

# ─────────────────────────────────────────────────────────────────────
# Default status mappings — used as fallback when MijnRood Sync Settings
# child table is empty (e.g. during migration or fresh install).
# Consumers should use the get_* functions below instead of these dicts.
# ─────────────────────────────────────────────────────────────────────
_DEFAULT_STATUS_ID_MAP = {
    1: "lid",  # Active member
    2: "aspirant",  # Aspirant member
    3: "opgezegd",  # Resigned / terminated
    4: "geroyeerd",  # Expelled
    5: "overleden",  # Deceased
    6: "geschorst",  # Suspended
}

_DEFAULT_TERMINATED_STATUS_IDS = frozenset([3, 4, 5, 6])

_DEFAULT_ACTIVE_STATUS_IDS = frozenset([1, 2])

_DEFAULT_STATUS_ID_TO_TERMINATION_TYPE = {
    3: "Voluntary",  # opgezegd → Voluntary resignation
    4: "Disciplinary Action",  # geroyeerd → Expelled
    5: "Deceased",  # overleden
    6: "Policy Violation",  # geschorst → Suspended
}

_DEFAULT_STATUS_ID_LABELS = {
    1: "Active (lid)",
    2: "Aspirant",
    3: "Resigned (opgezegd)",
    4: "Expelled (geroyeerd)",
    5: "Deceased (overleden)",
    6: "Suspended (geschorst)",
}


# ─────────────────────────────────────────────────────────────────────
# Cached reader functions — load from MijnRood Sync Settings child
# table, falling back to the defaults above when the table is empty.
# ─────────────────────────────────────────────────────────────────────
def _load_status_mapping() -> dict:
    """Load status mapping from MijnRood Sync Settings child table.

    Returns dict keyed by mijnrood_status_id with sub-dict:
    {type_string, label, is_active, termination_type}
    """
    import frappe

    try:
        settings = frappe.get_cached_doc("MijnRood Sync Settings")
    except Exception:
        return {}

    if not settings.status_mapping:
        return {}

    mapping = {}
    for row in settings.status_mapping:
        mapping[row.mijnrood_status_id] = {
            "type_string": row.membership_type_string,
            "label": row.label,
            "is_active": bool(row.is_active),
            "termination_type": row.termination_type or "",
            "verenigingen_membership_type": row.verenigingen_membership_type or "",
            "allows_login": bool(row.allows_login),
        }
    return mapping


def _get_cached_mapping() -> dict:
    """Get status mapping with Redis caching."""
    import frappe

    return frappe.cache.get_value("mijnrood_status_mapping", generator=_load_status_mapping)


def get_status_id_map() -> dict:
    """Status ID → membership type string (replaces MIJNROOD_STATUS_ID_MAP)."""
    mapping = _get_cached_mapping()
    if mapping:
        return {k: v["type_string"] for k, v in mapping.items()}
    return dict(_DEFAULT_STATUS_ID_MAP)


def get_active_status_ids() -> frozenset:
    """Frozenset of active status IDs (replaces ACTIVE_STATUS_IDS)."""
    mapping = _get_cached_mapping()
    if mapping:
        return frozenset(k for k, v in mapping.items() if v["is_active"])
    return _DEFAULT_ACTIVE_STATUS_IDS


def get_terminated_status_ids() -> frozenset:
    """Frozenset of terminated status IDs (replaces TERMINATED_STATUS_IDS)."""
    mapping = _get_cached_mapping()
    if mapping:
        return frozenset(k for k, v in mapping.items() if not v["is_active"])
    return _DEFAULT_TERMINATED_STATUS_IDS


def get_termination_type_map() -> dict:
    """Status ID → termination type string (replaces STATUS_ID_TO_TERMINATION_TYPE)."""
    mapping = _get_cached_mapping()
    if mapping:
        return {
            k: v["termination_type"]
            for k, v in mapping.items()
            if not v["is_active"] and v["termination_type"]
        }
    return dict(_DEFAULT_STATUS_ID_TO_TERMINATION_TYPE)


def get_verenigingen_membership_type_for_status_id(status_id: int) -> str | None:
    """Get the explicit Verenigingen Membership Type for a MijnRood status ID.

    Returns the configured Membership Type name, or None if not configured.
    """
    mapping = _get_cached_mapping()
    if mapping and status_id in mapping:
        mt = mapping[status_id].get("verenigingen_membership_type")
        return mt if mt else None
    return None


def get_role_mapping() -> dict[str, dict]:
    """Return role mapping config keyed by mijnrood_role string.

    Returns e.g.:
    {
        "ROLE_ADMIN": {
            "create_volunteer": True,
            "verenigingen_role": Roles.VERENIGINGEN_STAFF,
            "add_to_chapter_board": False,
            "chapter_role": None,
        },
        "ROLE_DIVISION_CONTACT": { ... }
    }

    Cached in Redis; invalidated on settings save via on_update().
    Returns empty dict if no role mapping is configured.
    """
    import frappe

    return frappe.cache.get_value("mijnrood_role_mapping", generator=_load_role_mapping)


def _load_role_mapping() -> dict:
    """Load role mapping from MijnRood Sync Settings child table."""
    import frappe

    try:
        settings = frappe.get_cached_doc("MijnRood Sync Settings")
    except Exception:
        return {}

    if not settings.role_mapping:
        return {}

    mapping = {}
    for row in settings.role_mapping:
        mapping[row.mijnrood_role] = {
            "label": row.label,
            "create_volunteer": bool(row.create_volunteer),
            "verenigingen_role": row.verenigingen_role or None,
            "role_profile": row.role_profile or None,
            "add_to_chapter_board": bool(row.add_to_chapter_board),
            "chapter_role": row.chapter_role or None,
            "add_to_team": bool(row.get("add_to_team")),
            "default_team": row.get("default_team") or None,
        }
    return mapping


def get_status_labels() -> dict:
    """Status ID → display label (replaces STATUS_ID_LABELS)."""
    mapping = _get_cached_mapping()
    if mapping:
        return {k: v["label"] for k, v in mapping.items()}
    return dict(_DEFAULT_STATUS_ID_LABELS)


# Backward-compatible aliases for existing imports that haven't been migrated yet.
# These will be removed once all consumers use the get_* functions.
MIJNROOD_STATUS_ID_MAP = _DEFAULT_STATUS_ID_MAP
ACTIVE_STATUS_IDS = _DEFAULT_ACTIVE_STATUS_IDS
TERMINATED_STATUS_IDS = _DEFAULT_TERMINATED_STATUS_IDS
STATUS_ID_TO_TERMINATION_TYPE = _DEFAULT_STATUS_ID_TO_TERMINATION_TYPE
STATUS_ID_LABELS = _DEFAULT_STATUS_ID_LABELS

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
    "contribution_period": "Payment Period",
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
