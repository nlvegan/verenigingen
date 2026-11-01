"""Backfill Member.import_source_type / import_source for members already imported (#1777).

Only the Mijnrood CSV importer left a trace tying a member to a specific import record: a line
"Imported from Mijnrood CSV (Import: <name>)" appended to review_notes. Member Import
(Procurios) and VIP Import left none (a procurios_id / member_id says it came from Procurios,
not which import record), so those members stay unfilled rather than guessed.
"""

import re

import frappe

IMPORT_DOCTYPE = "Mijnrood CSV Import"
NOTE_PATTERN = re.compile(r"Imported from Mijnrood CSV \(Import: ([^)\n]+)\)")


def execute():
    counts = backfill_member_import_source()
    print(
        f"backfill_member_import_source: set {counts['set']}, "
        f"skipped (named import record missing) {counts['missing_import']}, "
        f"skipped (already set) {counts['already_set']}"
    )


def backfill_member_import_source():
    """Set the pair from the LAST note line, only if that import record exists and the field is empty."""
    counts = {"set": 0, "missing_import": 0, "already_set": 0}
    members = frappe.get_all(
        "Member",
        filters={"review_notes": ["like", "%Imported from Mijnrood CSV (Import:%"]},
        fields=["name", "review_notes", "import_source"],
    )
    for member in members:
        if member.import_source:
            counts["already_set"] += 1
            continue
        matches = NOTE_PATTERN.findall(member.review_notes or "")
        if not matches:
            continue
        import_name = matches[-1].strip()
        if not frappe.db.exists(IMPORT_DOCTYPE, import_name):
            counts["missing_import"] += 1
            continue
        frappe.db.set_value(
            "Member",
            member.name,
            {"import_source_type": IMPORT_DOCTYPE, "import_source": import_name},
            update_modified=False,
        )
        counts["set"] += 1
    return counts
