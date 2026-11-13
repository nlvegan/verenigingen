"""A stub Procurios import doc, shared by the mandate- and membership-import suites.

Both `test_procurios_mandate_import.py` and
`test_procurios_membership_import_row_atomicity.py` need an inserted import doc
with a placeholder CSV file (its content is never read by the per-row unit
tests, which build their mapped rows by hand) -- only the doctype name
differs. Consolidated here after the duplicate-helper ratchet flagged the two
copies as near-identical (#698 review).
"""

from unittest.mock import patch

import frappe


def _create_stub_import_doc(doctype: str):
    """Insert `doctype` with a placeholder private CSV file attached."""
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": "stub.csv",
            "is_private": 1,
            "content": b"stub",
        }
    )
    file_doc.flags.ignore_permissions = True
    file_doc.insert()

    doc = frappe.get_doc(
        {
            "doctype": doctype,
            "csv_file": file_doc.file_url,
        }
    )
    doc.flags.ignore_permissions = True
    doc.insert()
    return doc


def _submit_import_doc_without_worker_2491(doc):
    """Submit an import doc WITHOUT handing its job to a live RQ worker (#2491).

    `BaseCSVImport.on_submit` enqueues `process_import_background` with
    `now=False`, so on any bench with a running worker the worker processes the
    same import concurrently with the test's own synchronous call: a duplicate
    `mandate_id` IntegrityError and "modified after you have opened it" errors,
    and whole 50-row batches lost to `skipped_summary.error` -- the 0/50/100/150
    created counts of #2491. CI has no worker, which is why it never showed there.

    Mock justified: the enqueue is infrastructure, not business logic. The call is
    asserted, so `on_submit`'s contract (it queues this doc) is still exercised.
    """
    with patch.object(frappe, "enqueue") as enqueue_mock:
        doc.submit()
    if enqueue_mock.call_count != 1 or enqueue_mock.call_args.kwargs.get("import_doc_name") != doc.name:
        raise AssertionError(
            f"on_submit should enqueue exactly one job for {doc.name}, got {enqueue_mock.call_args_list}"
        )
    return enqueue_mock
