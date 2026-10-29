"""Answer masters (join reasons, referral sources) and the new Member application fields."""

import frappe

from verenigingen.patches.v2_2 import seed_application_answer_masters
from verenigingen.tests.utils.base import VereningingenUnitTestCase

REASONS = [
    "Promotie van veganisme/vegan levenswijze",
    "Promotie van vegan eten/plantaardige voeding",
    "Ondersteunen van de NVV",
    "Voor de dieren",
    "Informatie krijgen over veganisme",
    "Zelf vegan (geworden)",
    "Hulp bij vegan zijn/worden",
    "Duurzaamheid/het milieu/de wereld",
    "Verbondenheid met andere vegans",
    "Gezondheid",
    "VEGAN Magazine",
    "Ledenpasvoordeel",
]
SOURCES = [
    "Via onze website (veganisme.org)",
    "Via online zoeken (bijv. Google)",
    "Via vriend/kennis/collega/familie",
    "Via VEGAN Magazine",
    "Via een NVV-stand op een event",
    "Via de VeganChallenge (NVV)",
    "Via de Veggie Challenge (ProVeg)",
]


class TestApplicationAnswerMasters(VereningingenUnitTestCase):
    def test_seed_creates_12_reasons_and_7_sources(self):
        seed_application_answer_masters.execute()
        seed_application_answer_masters.execute()

        self.assertGreaterEqual(frappe.db.count("Membership Join Reason"), 12)
        self.assertGreaterEqual(frappe.db.count("Membership Referral Source"), 7)
        for reason in REASONS:
            self.assertEqual(frappe.db.count("Membership Join Reason", {"reason": reason}), 1, reason)
        for source in SOURCES:
            self.assertEqual(frappe.db.count("Membership Referral Source", {"source": source}), 1, source)

    def test_member_accepts_application_answer_fields(self):
        seed_application_answer_masters.execute()
        suffix = frappe.generate_hash(length=8)
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Antwoord",
                "last_name": f"Velden {suffix}",
                "email": f"antwoord.{suffix}@example.com",
                "status": "Pending",
                "application_status": "Pending",
                "magazine_delivery": "Papier",
                "birth_year": 1990,
                "join_reasons": [{"join_reason": "Voor de dieren"}],
                "referral_source": "Via VEGAN Magazine",
            }
        ).insert()
        self.track_doc("Member", member.name)

        member.reload()
        self.assertEqual(member.magazine_delivery, "Papier")
        self.assertEqual(member.birth_year, 1990)
        self.assertEqual([r.join_reason for r in member.join_reasons], ["Voor de dieren"])
        self.assertEqual(member.referral_source, "Via VEGAN Magazine")
