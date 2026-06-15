"""Split the overloaded Direct Debit Batch.batch_type into scheme + sequence.

Historically ``batch_type`` was overloaded: some code stored a SEPA SCHEME
(CORE/B2B/COR1 -> pain.008 LclInstrm) while other code stored a SEQUENCE type
(FRST/RCUR/FNAL/OOFF -> pain.008 SeqTp). A dedicated ``sequence_type`` field was
added to the parent Direct Debit Batch; ``batch_type`` now holds only the scheme.

Backfill existing rows:
  * If batch_type holds a SEQUENCE value, move it to sequence_type and reset
    batch_type to the CORE scheme.
  * If batch_type holds a SCHEME value (CORE/B2B/COR1), keep it and default an
    empty sequence_type to RCUR.
  * Anything else / empty -> CORE scheme + RCUR sequence.
"""

import frappe

_SEQUENCE_VALUES = ("FRST", "RCUR", "FNAL", "OOFF")


def execute():
    if not frappe.db.has_column("Direct Debit Batch", "sequence_type"):
        # Schema sync hasn't created the column yet; new batches set both fields
        # in code. Skip silently rather than fail the migration.
        return

    # 1. Rows whose batch_type actually holds a sequence value: move it across.
    frappe.db.sql(
        """
        UPDATE `tabDirect Debit Batch`
        SET sequence_type = batch_type,
            batch_type = 'CORE'
        WHERE batch_type IN %(seqs)s
        """,
        {"seqs": _SEQUENCE_VALUES},
    )

    # 2. Any remaining row without a sequence_type defaults to RCUR (recurring).
    frappe.db.sql(
        """
        UPDATE `tabDirect Debit Batch`
        SET sequence_type = 'RCUR'
        WHERE sequence_type IS NULL OR sequence_type = ''
        """
    )

    # 3. Normalise any batch_type that is still not a valid scheme to CORE.
    frappe.db.sql(
        """
        UPDATE `tabDirect Debit Batch`
        SET batch_type = 'CORE'
        WHERE batch_type IS NULL OR batch_type NOT IN ('CORE', 'B2B', 'COR1')
        """
    )
