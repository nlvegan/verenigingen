"""Staff Alert Event: one row per staff alert problem, and whether it reached anyone (#1979).

MyISAM on purpose (``"engine": "MyISAM"``): the row must survive the caller's rollback, because
the interesting case is an alert raised inside a transaction that then fails. Rows are written
only by ``verenigingen.utils.staff_alert_events``.
"""

from frappe.model.document import Document


class StaffAlertEvent(Document):
    pass
