"""Seed the answer lists of the short membership application (Procurios wording, verbatim).

Idempotent: a value that already exists is left alone, so an association's own edits
(for instance disabling a reason) survive a re-run.
"""

import frappe

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


def execute():
    _seed_masters("Membership Join Reason", "reason", REASONS)
    _seed_masters("Membership Referral Source", "source", SOURCES)


def _seed_masters(doctype, fieldname, values):
    for value in values:
        if not frappe.db.exists(doctype, value):
            frappe.get_doc({"doctype": doctype, fieldname: value, "enabled": 1}).insert(
                ignore_permissions=True
            )
