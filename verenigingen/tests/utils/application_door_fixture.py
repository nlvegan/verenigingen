"""One shared builder for Membership Application Door fixtures in the short-application tests."""

import frappe

DOOR = "Membership Application Door"


class ApplicationDoorMixin:
    """Gives a test case `_door(**fields)`: an inserted, tracked, enabled Regular door.

    Needs `self.membership_type`. A test that wants every door to carry more (for
    example a dues template) sets `self.door_extra` to a dict of fields.
    """

    def _door(self, **fields):
        data = {
            "doctype": DOOR,
            "title": "Testdeur",
            "slug": f"deur-{frappe.generate_hash(length=8).lower()}",
            "membership_type": self.membership_type.name,
            "form_shape": "Regular",
            "enabled": 1,
        }
        data.update(getattr(self, "door_extra", {}))
        data.update(fields)
        door = frappe.get_doc(data).insert()
        self.track_doc(DOOR, door.name)
        return door
