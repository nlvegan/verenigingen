"""Shared test fixtures for the event_application service test suite.

_FakeOrchestrator: stand-in for MijnRoodEventApplicationService.
    Records calls to cross-cutting helpers that have not yet been
    extracted from the god-class. Each PR in the Phase 1 sequence
    extends this stub as new orchestrator methods are needed.

StatusMappingSetupMixin: mixin that handles the MijnRood Sync Settings
    status_mapping append/restore boilerplate. Subclass must call
    super().setUp() and define cls.STATUS_ID + cls.MEMBERSHIP_TYPE_LABEL.
"""

from unittest.mock import MagicMock

import frappe


class _FakeOrchestrator:
    """Stand-in for MijnRoodEventApplicationService.

    Each attribute is a MagicMock with a sane default return value. Tests
    override per-instance attributes when they need specific behaviour.
    """

    def __init__(self):
        # PR #2 surface — member sync orchestrator deps
        self._create_related_records = MagicMock(return_value=[])
        self._process_member_roles = MagicMock(return_value=[])
        self._try_promote_application = MagicMock(return_value=None)
        self._check_and_handle_termination = MagicMock(return_value=None)
        self._handle_division_field_change = MagicMock(return_value=None)
        # PR #3 additions
        self._find_existing_member_or_conflict = MagicMock(return_value=(None, None))
        self._assign_chapter_from_division = MagicMock(return_value=None)
        self._apply_new_member = MagicMock(
            return_value={"success": True, "message": "fallback from stub"}
        )
        # PR #4 additions
        self._ensure_user_account_for_volunteer = MagicMock(return_value=None)


class StatusMappingSetupMixin:
    """Mixin for tests that need a MijnRood status_mapping row.

    Subclass must define:
        STATUS_ID: int — the mijnrood_status_id to inject
        MEMBERSHIP_TYPE_LABEL: str — the name of the Membership Type to ensure

    Call super().setUp() / super().tearDown() if subclass overrides them.
    """

    STATUS_ID: int = 9000
    MEMBERSHIP_TYPE_LABEL: str = "Default Mapping Test Type"

    def setUp(self):
        super().setUp()
        settings = frappe.get_single("MijnRood Sync Settings")
        self._original_status_mapping = list(settings.status_mapping or [])
        membership_type = self.factory.ensure_membership_type(self.MEMBERSHIP_TYPE_LABEL)
        settings.append(
            "status_mapping",
            {
                "mijnrood_status_id": self.STATUS_ID,
                "label": f"{self.MEMBERSHIP_TYPE_LABEL} (status_id={self.STATUS_ID})",
                "membership_type_string": "test",
                "is_active": 1,
                "verenigingen_membership_type": membership_type.name,
            },
        )
        settings.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")
        self.addCleanup(self._cleanup_status_mapping)

    def _cleanup_status_mapping(self):
        s = frappe.get_single("MijnRood Sync Settings")
        s.status_mapping = self._original_status_mapping
        s.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.cache().delete_value("mijnrood_status_mapping")
