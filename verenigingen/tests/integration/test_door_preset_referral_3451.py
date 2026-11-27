"""#3451: a door's preset referral source reaches the Member through the real flow.

Real flow: submit_short_application -> confirm -> approve_application. The preset and the "posted" source
are rows this test makes; no seeded source name is used.
"""

import frappe

from verenigingen.tests.integration.test_application_record_approval import ApprovalCase

SUBMISSION = "Membership Application Submission"


class TestDoorPresetReferral3451(ApprovalCase):
    def _preset3451_source(self):
        doc = frappe.get_doc(
            {"doctype": "Membership Referral Source", "source": f"Bron {frappe.generate_hash(length=8)}", "enabled": 1}
        ).insert()
        self.track_doc("Membership Referral Source", doc.name)
        return doc.name

    def _preset3451_approved_member(self, door_fields, **form):
        name = self._stage_short_and_confirm(door_fields=door_fields, **form)
        self.assertTrue(self._approve_as(name)["success"])
        return frappe.get_doc("Member", frappe.db.get_value(SUBMISSION, name, "member"))

    def test_member_gets_the_preset_and_not_the_posted_source(self):
        preset, posted = self._preset3451_source(), self._preset3451_source()

        member = self._preset3451_approved_member(
            {"preset_referral_source": preset}, referral_source=posted, referral_source_other="via een vriend"
        )

        self.assertEqual(member.referral_source, preset)
        self.assertFalse(member.referral_source_other)

    def test_a_door_without_a_preset_keeps_the_posted_source(self):
        posted = self._preset3451_source()

        member = self._preset3451_approved_member({}, referral_source=posted, referral_source_other="via een vriend")

        self.assertEqual(member.referral_source, posted)
        self.assertEqual(member.referral_source_other, "via een vriend")
