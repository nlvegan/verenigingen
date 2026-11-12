"""Write the missing ``Ponto Settings.sandbox_mode`` / ``Mollie Settings.test_mode`` rows as 1 (#2509).

A site that saved these Singles before the field existed reads the flag as 0, which selects the
production Ponto client / live Mollie key. Existing rows (0 included) are never touched; idempotent.
"""

from verenigingen.utils.single_check_defaults import seed_missing_check_default

FIELDS = (("Ponto Settings", "sandbox_mode"), ("Mollie Settings", "test_mode"))


def execute():
    for doctype, fieldname in FIELDS:
        seed_missing_check_default(doctype, fieldname)
