# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""Shared test fixtures for the two Procurios CSV importers.

`tests/payment/test_procurios_mandate_import.py` and
`tests/member/test_procurios_csv_import.py` both need to write rows to a
temp CSV and register the result as a Frappe File. Both also occasionally
need to register a raw arbitrary CSV blob (for malformed-CSV scenarios).

Two near-identical 20-line helpers used to live in each test file. They
diverged only on file-name prefix and the headers list; that's exactly
the kind of structural duplication that grows surprise inconsistencies
as one importer gets a bug-fix the other doesn't. Keep them here so the
two test files stay in sync by construction.

These helpers are `_create_*` / `create_*` prefixed per the project's
test-quality-enforcer policy (permission bypasses are only allowed in
setup/teardown/factory methods, identified by name).
"""

from __future__ import annotations

import csv
import os
import tempfile
from typing import Iterable, List, Mapping

import frappe


def create_csv_file_attachment(
    rows: Iterable[Mapping[str, str]],
    headers: List[str],
    *,
    prefix: str = "procurios_csv_",
) -> str:
    """Write `rows` (dicts matching `headers`) to a temp CSV and register as a File.

    Args:
        rows: Iterable of dict rows. Each dict's keys must be a subset of
            `headers`; missing values render as empty strings.
        headers: CSV column ordering (also used as DictWriter fieldnames).
        prefix: Filename prefix passed to tempfile.mkstemp. Lets the two
            importers stay distinguishable in the File list during debugging.

    Returns:
        The File document's `file_url`, suitable as the `csv_file` field
        on either Procurios import doctype.
    """
    fd, path = tempfile.mkstemp(suffix=".csv", prefix=prefix)
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, delimiter=";")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    with open(path, "rb") as f:
        content = f.read()
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": os.path.basename(path),
            "is_private": 1,
            "content": content,
        }
    )
    file_doc.flags.ignore_permissions = True
    file_doc.insert()
    return file_doc.file_url


def create_raw_csv_attachment(raw_text: str, name_hint: str = "raw.csv") -> str:
    """Register an arbitrary CSV blob as a File (for malformed-CSV tests).

    Use this when the test needs to exercise the CSV-parsing failure path
    on input that wouldn't survive a DictWriter (e.g. missing required
    columns, broken encoding). For valid structured rows use
    `create_csv_file_attachment` instead.
    """
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": name_hint,
            "is_private": 1,
            "content": raw_text.encode("utf-8"),
        }
    )
    file_doc.flags.ignore_permissions = True
    file_doc.insert()
    return file_doc.file_url
