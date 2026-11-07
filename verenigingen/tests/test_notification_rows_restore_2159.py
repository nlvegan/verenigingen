"""``restore_notification_rows`` puts the rows back byte for byte (#2159).

The per-module copies it replaces restored with ``config.set(...)`` + ``save()``, which keeps the
content and mints new row names and ``modified`` stamps; the harness's drain commit then made that
permanent, so every run of such a module changed the table's hash while all 88+ rows stayed enabled.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.utils.notification_state import (
    restore_notification_rows,
    snapshot_notification_rows,
)

DOCTYPE = "Verenigingen Email Configuration"


def _table_rows_2159():
    return frappe.get_all(
        "Email Notification Type",
        filters={"parent": DOCTYPE, "parenttype": DOCTYPE, "parentfield": "notification_types"},
        fields=["*"],
        order_by="idx asc",
        limit_page_length=0,
    )


class TestRestoreNotificationRows(FrappeTestCase):
    def setUp(self):
        super().setUp()
        config = frappe.get_single(DOCTYPE)
        if len(config.notification_types) < 3:  # a site with no registry rows: give the test some
            for key in ("t2159_a", "t2159_b", "t2159_c"):
                config.append("notification_types", {"notification_key": key, "label": key, "category": "Admin"})
            config.save()
        self.before = snapshot_notification_rows()
        self.assertGreaterEqual(len(self.before), 3, "control: there are rows to lose")

    def _strip_and_edit(self):
        config = frappe.get_single(DOCTYPE)
        config.set("notification_types", config.notification_types[1:])
        config.notification_types[0].cooldown_minutes = 12345
        config.save()
        self.assertNotEqual(_table_rows_2159(), self.before, "control: the table really changed")

    def test_restore_is_byte_identical_names_and_stamps_included(self):
        self._strip_and_edit()
        restore_notification_rows(self.before)
        self.assertEqual(_table_rows_2159(), self.before)

    def test_a_save_based_restore_does_not_have_that_property(self):
        """Control for the test above: the old restore keeps the content and loses the identity."""
        self._strip_and_edit()
        config = frappe.get_single(DOCTYPE)
        config.set("notification_types", [{k: v for k, v in r.items() if k != "name"} for r in self.before])
        config.save()
        self.assertEqual(
            [r["notification_key"] for r in _table_rows_2159()], [r["notification_key"] for r in self.before]
        )
        self.assertNotEqual([r["name"] for r in _table_rows_2159()], [r["name"] for r in self.before])

    def test_restoring_an_empty_snapshot_empties_the_table(self):
        restore_notification_rows([])
        self.assertEqual(_table_rows_2159(), [])
