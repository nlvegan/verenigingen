"""Member.full_name is validated at the source and stored raw (#3300).

Real flows: ``Member.insert()`` (validate runs) and
``MemberPerformanceOptimizer.create_member_optimized`` (validate skipped).
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.member_performance_optimizer import member_optimizer


class TestMemberFullNameRaw3300(VereningingenTestCase):
    def _new_member_doc_3300(self, **fields):
        data = {
            "doctype": "Member",
            "first_name": "Pa",
            "last_name": "Tt" + frappe.generate_hash(length=5),
            "email": f"t3300-{frappe.generate_hash(length=8)}@test-3300.local",
            "birth_date": "1985-01-01",
        }
        data.update(fields)
        return frappe.get_doc(data)

    def test_markup_in_tussenvoegsel_is_refused_like_other_name_fields(self):
        for field in ("first_name", "middle_name", "last_name"):
            with self.assertRaises(frappe.ValidationError, msg=field):
                self._new_member_doc_3300(**{field: "<i>x</i>"}).insert()
        with self.assertRaisesRegex(frappe.ValidationError, "Tussenvoegsel contains"):
            self._new_member_doc_3300(tussenvoegsel="<i>x</i>").insert()

    def test_legitimate_tussenvoegsel_is_accepted_and_kept_in_full_name(self):
        for particle in ("van der", "'t", "d'", "van den"):
            member = self._new_member_doc_3300(tussenvoegsel=particle)
            member.insert()
            self.track_doc("Member", member.name)
            stored = frappe.db.get_value("Member", member.name, "full_name")
            self.assertIn(particle, stored)
            self.assertNotIn("&", stored)

    def test_create_member_optimized_stores_full_name_raw(self):
        last = "O'Brien" + frappe.generate_hash(length=4)
        name = member_optimizer.create_member_optimized(
            {
                "first_name": "Sean",
                "last_name": last,
                "birth_date": "1985-01-01",
                "email": f"t3300-{frappe.generate_hash(length=8)}@test-3300.local",
            }
        )
        self.track_doc("Member", name)
        self.assertEqual(frappe.db.get_value("Member", name, "full_name"), f"Sean {last}")

    def test_create_member_optimized_stores_particle_raw(self):
        name = member_optimizer.create_member_optimized(
            {
                "first_name": "Sean",
                "tussenvoegsel": "'t",
                "last_name": "Hart" + frappe.generate_hash(length=4),
                "birth_date": "1985-01-01",
                "email": f"t3300-{frappe.generate_hash(length=8)}@test-3300.local",
            }
        )
        self.track_doc("Member", name)
        self.assertIn("'t", frappe.db.get_value("Member", name, "full_name"))

    def test_create_member_optimized_refuses_markup_in_any_name_part(self):
        self.expectErrorLog("Optimized member creation failed")  # the method logs the failure it re-raises
        for field in ("first_name", "tussenvoegsel", "last_name"):
            data = {
                "first_name": "Sean",
                "last_name": "Hart" + frappe.generate_hash(length=4),
                "birth_date": "1985-01-01",
                "email": f"t3300-{frappe.generate_hash(length=8)}@test-3300.local",
            }
            data[field] = "<i>x</i>"
            # The label must name the field: with markup left in, the insert still fails later
            # (Customer creation), so asserting only the exception type would pass either way.
            with self.assertRaisesRegex(frappe.ValidationError, f"{field.replace('_', ' ').title()} contains"):
                member_optimizer.create_member_optimized(data)
            self.assertFalse(frappe.db.exists("Member", {"email": data["email"]}), field)
