"""Second half of the delete auditor: ask the site which recorded deletes survived.

Run AFTER the test run, in its own process, so what it sees is committed state.
"""

import collections
import json
import sys

import frappe


def main(site, log_path):
    frappe.init(site=site)
    frappe.connect()

    # Deduped on (doctype, name): `delete_doc` calls `db.delete` internally, so one
    # delete is recorded twice and an undeduped count double-reports every survivor.
    # The FIRST record wins, which keeps the outer call's `kind` and its test id.
    deduped = {}
    with open(log_path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            deduped.setdefault((row["doctype"], row["name"]), row)
    seen = list(deduped.values())

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
        if row.get("creation") is None:
            recreated.append(dict(row, verdict="UNVERIFIABLE", now=str(now)))
        elif str(now) == row["creation"]:
            survived.append(row)
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
        )
        by_test[row["test"]] += 1
    for row in recreated:
        print(
            f"DELETE-AUDIT {row['verdict']} {row['doctype']}::{row['name']} "
            f"test={row['test']} was={row['creation']} now={row['now']}"
        )
    for row in unknown:
        print(f"DELETE-AUDIT UNKNOWN-DOCTYPE {row['doctype']}::{row['name']} test={row['test']}")
    for test, count in by_test.most_common():
        print(f"DELETE-AUDIT PER-TEST {count} {test}")
    frappe.destroy()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
