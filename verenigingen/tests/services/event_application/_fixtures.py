"""Shared test fixtures for the event_application service test suite.

StatusMappingSetupMixin: mixin that handles the MijnRood Sync Settings
    status_mapping append/restore boilerplate. Subclass must call
    super().setUp() and define cls.STATUS_ID + cls.MEMBERSHIP_TYPE_LABEL.
"""

import frappe


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
