"""Write the missing ``require_webhook_signature`` row of Ponto Settings as 1 (#2478).

Frappe applies a Single's declared defaults only while the doctype has no ``tabSingles`` rows at
all. A site that saved Ponto Settings before the field existed has rows for everything else, so the
form showed the box unticked while the webhook (now fail-closed) required the signature. Seeding the
row makes the form say what the webhook does. A real row, 0 included, is the operator's choice and
is never touched. Idempotent. Shares the seed with #2509 (#2565); the webhook has no live-credential
exception, so none is passed.
"""

from verenigingen.utils.single_check_defaults import seed_missing_check_default

DOCTYPE = "Ponto Settings"
FIELD = "require_webhook_signature"


def execute():
    seed_missing_check_default(DOCTYPE, FIELD)
