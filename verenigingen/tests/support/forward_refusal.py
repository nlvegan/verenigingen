"""Shared fixture and assertions for the #2406 refusal of a staff-cancelled forward payment.

Maintainer ruling (2026-11-11): when staff cancelled a Mollie forward (Receive) Payment Entry and
Mollie re-delivers the payment, the writer must NOT book again. It refuses, writes an Error Log row,
raises one staff alert on the registered key and still acknowledges the webhook.

Reads the real tables: Payment Entry, Error Log (MyISAM, so it outlives a rollback and is deleted by
payment id), Staff Alert Event (MyISAM too, same cleanup). The recipient is a real enabled User holding
a role the key's seeded row names, so the alert really reaches someone and the dedup rule is the real one.
"""

import frappe

from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows

ALERT_KEY = "mollie_forward_payment_staff_cancelled"
ERROR_TITLE = "Mollie Forward Payment Refused"


def prepare_refusal_fixture(test_case, payment_id):
    """Seed the key's row, add one reachable staff recipient, and clean the MyISAM rows afterwards."""
    ensure_notification_registry_rows()
    user = frappe.get_doc(
        {
            "doctype": "User",
            "email": f"staff2406-{frappe.generate_hash(length=6)}@example.com",
            "first_name": "Staff2406",
            "enabled": 1,
            "send_welcome_email": 0,
            "roles": [{"role": "Verenigingen Administrator"}],
        }
    ).insert()
    test_case.addCleanup(_purge_refusal_rows, payment_id)
    test_case.expectErrorLog(ERROR_TITLE)
    return user.name


def _purge_refusal_rows(payment_id):
    for event in frappe.get_all("Staff Alert Event", filters={"reference_name": payment_id}, pluck="name"):
        frappe.delete_doc("Staff Alert Event", event, force=True)
    frappe.db.delete("Error Log", {"method": ERROR_TITLE, "error": ["like", f"%{payment_id}%"]})


def refusal_logs(payment_id):
    return frappe.get_all(
        "Error Log", filters={"method": ERROR_TITLE, "error": ["like", f"%{payment_id}%"]}, pluck="error"
    )


def alert_events(payment_id):
    return frappe.get_all(
        "Staff Alert Event",
        filters={"notification_key": ALERT_KEY, "reference_name": payment_id},
        fields=["name", "attempts", "requires_action", "recipient_count"],
    )


def assert_refused_once(test_case, payment_id, amount):
    """Exactly one Error Log row naming the payment and amount, exactly one alert that reached staff."""
    logs = refusal_logs(payment_id)
    test_case.assertEqual(len(logs), 1, f"expected one refusal Error Log row, got {len(logs)}")
    test_case.assertIn(payment_id, logs[0])
    test_case.assertIn(amount, logs[0])
    events = alert_events(payment_id)
    test_case.assertEqual(len(events), 1, "expected exactly one staff alert event for the payment")
    test_case.assertEqual(events[0].attempts, 1)
    test_case.assertEqual(events[0].requires_action, 1)
    test_case.assertGreaterEqual(events[0].recipient_count, 1, "the alert reached nobody")


def assert_no_refusal(test_case, payment_id):
    """Control: a normal delivery raises no refusal and no alert."""
    test_case.assertEqual(refusal_logs(payment_id), [])
    test_case.assertEqual(alert_events(payment_id), [])


def _name(entry):
    return getattr(entry, "name", entry)


def book_then_staff_cancel(test_case, payment_id, book):
    """Book the payment through ``book()`` (returns a Payment Entry or its name), staff-cancel it.

    Controls first: the delivery booked and raised no refusal. Then the cancel, then the recipient.
    Returns whatever ``book`` returned.
    """
    first = book()
    test_case.assertTrue(first, "fixture problem: payment not booked")
    frappe.get_doc("Payment Entry", _name(first)).cancel()
    test_case.assertEqual(
        frappe.get_all(
            "Payment Entry",
            filters={"reference_no": payment_id, "payment_type": "Receive", "docstatus": 1},
            pluck="name",
        ),
        [],
        "fixture problem: cancel left a live row",
    )
    assert_no_refusal(test_case, payment_id)
    prepare_refusal_fixture(test_case, payment_id)
    return first


def assert_not_rebooked(test_case, payment_id, first):
    """Only the staff-cancelled audit row remains for the payment: nothing live, nothing new."""

    def rows(**extra):
        return frappe.get_all(
            "Payment Entry",
            filters={"reference_no": payment_id, "payment_type": "Receive", **extra},
            pluck="name",
        )

    test_case.assertEqual(rows(docstatus=["!=", 2]), [], "a redelivery after a staff cancel re-booked")
    test_case.assertEqual(rows(docstatus=2), [_name(first)], "expected only the audit row")
