"""Second half of the delete auditor: ask the site which recorded deletes survived.

Run AFTER the test run, in its own process, so what it sees is committed state.

Exits 2 when the log carries no `armed` marker, i.e. the recorder never loaded. That
case used to print `recorded=0` and exit 0 -- indistinguishable from a clean run, which
is the instrument failure this whole tool exists to replace.
"""

import collections
import json
import sys

import frappe

_READ_FAILED = "<creation-read-failed>"


def main(site, log_path):
    frappe.init(site=site)
    frappe.connect()

    # Deduped on (doctype, name): `delete_doc` calls `db.delete` internally, so one
    # delete is recorded twice and an undeduped count double-reports every survivor.
    # `delete_doc` WINS, and it is written second -- the outer wrapper records after
    # `real_delete_doc` returns. An earlier version kept the first record and therefore
    # reported `via=db.delete` for every delete_doc in every log, making the field
    # useless for attribution.
    armed = None
    deduped = {}
    with open(log_path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("kind") == "armed":
                armed = row
                continue
            key = (row["doctype"], row["name"])
            existing = deduped.get(key)
            if existing is None or (
                existing.get("kind") != "delete_doc" and row.get("kind") == "delete_doc"
            ):
                deduped[key] = row
    seen = list(deduped.values())

    if armed is None:
        print(
            "DELETE-AUDIT NO ARMED MARKER -- the recorder never loaded, so this says "
            "NOTHING about the run.\n"
            "DELETE-AUDIT check that PYTHONPATH points at an ABSOLUTE path to "
            "scripts/testing/delete_audit and that DELETE_AUDIT_LOG was set.",
            file=sys.stderr,
        )
        frappe.destroy()
        return 2
    run_started = armed.get("run_started")

    survived, recreated, unknown = [], [], []
    for row in seen:
        try:
            now = frappe.db.get_value(row["doctype"], row["name"], "creation")
        except Exception as exc:
            # A missing table is not "gone" -- it means the delete could never have run.
            # Its own category, rather than letting `exists` swallow the 1146 and read
            # as success (#491).
            unknown.append(dict(row, why=str(exc)[:80]))
            continue
        if not now:
            continue
        # SAME row back = a resurrection. A DIFFERENT row wearing the same docname is a
        # fixture recreated on a fixed name, which is not this defect. Recorded
        # `creation` is None only when the pre-delete read failed, in which case the
        # honest verdict is "cannot tell", not "resurrected".
        if row.get("creation") in (None, _READ_FAILED):
            recreated.append(dict(row, verdict="UNVERIFIABLE", now=str(now)))
        elif str(now) == row["creation"]:
            survived.append(row)
        elif run_started and str(now) < run_started:
            # The creation on the site PREDATES this run, so this row cannot have been
            # created during it -- it is the same row, with a `creation` that was
            # rewritten. Four live sites in this app backdate `creation` (a Company to
            # 2000-01-01, a Sales Invoice, two raw `UPDATE tabMember SET creation`), and
            # without this branch every one of them reads RECREATED: the tool going
            # silent on exactly the defect it exists to find.
            survived.append(dict(row, verdict="SURVIVED-CREATION-REWRITTEN", now=str(now)))
        else:
            recreated.append(dict(row, verdict="RECREATED", now=str(now)))

    print(
        f"DELETE-AUDIT recorded={len(seen)} survived={len(survived)} "
        f"recreated_or_unverifiable={len(recreated)} unknown_doctype={len(unknown)}"
    )
    by_test = collections.Counter()
    for row in survived:
        print(
            f"DELETE-AUDIT SURVIVED {row['doctype']}::{row['name']} "
            f"test={row['test']} via={row['kind']} creation={row['creation']}"
            + (f" now={row['now']} ({row['verdict']})" if row.get("verdict") else "")
        )
        by_test[row["test"]] += 1
    # UNVERIFIABLE is NEVER capped: "cannot tell" is the verdict a reader most needs to
    # see, and there are normally none. RECREATED is capped and the cap is announced --
    # arming from TestSuite.run also catches the framework's own bootstrap churn
    # (Property Setters recreated during setup), which is ~40 rows on a warm site: real,
    # correctly verdicted as "not this defect", and noise.
    #
    # The first version of this cap took the first 10 of everything and truncated the
    # selftest's own RECREATED and UNVERIFIABLE controls out of the report -- a silent
    # cap hiding the thing being asserted, in the commit that added "no silent caps".
    # Capped PER DOCTYPE rather than over the whole list, so no doctype ever vanishes
    # from the report. A flat "first 10" truncated the selftest's own Territory control
    # out of a run whose 30 Property Setter rows came first -- a silent cap hiding the
    # thing being asserted, in the commit that added "no silent caps". Twice.
    _PER_DOCTYPE_SHOWN = 3
    unverifiable = [r for r in recreated if r["verdict"] == "UNVERIFIABLE"]
    plain = [r for r in recreated if r["verdict"] != "UNVERIFIABLE"]

    def _line(row):
        print(
            f"DELETE-AUDIT {row['verdict']} {row['doctype']}::{row['name']} "
            f"test={row['test']} was={row['creation']} now={row['now']}"
        )

    for row in unverifiable:  # never capped: "cannot tell" is what a reader needs most
        _line(row)
    by_doctype = collections.defaultdict(list)
    for row in plain:
        by_doctype[row["doctype"]].append(row)
    for doctype, rows in sorted(by_doctype.items(), key=lambda kv: -len(kv[1])):
        for row in rows[:_PER_DOCTYPE_SHOWN]:
            _line(row)
        if len(rows) > _PER_DOCTYPE_SHOWN:
            print(
                f"DELETE-AUDIT ... {len(rows) - _PER_DOCTYPE_SHOWN} more RECREATED "
                f"{doctype} rows not listed"
            )
    for row in unknown:
        print(f"DELETE-AUDIT UNKNOWN-DOCTYPE {row['doctype']}::{row['name']} test={row['test']}")
    for test, count in by_test.most_common():
        print(f"DELETE-AUDIT PER-TEST {count} {test}")
    frappe.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
