# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen Contributors
# See license.txt

"""Shared helper for tests that simulate a concurrent-creator duplicate-key
race through ``secure_document_operation()``.

``secure_document_operation()`` swallows the ``DuplicateEntryError`` /
``UniqueValidationError`` a real create-time race raises and reports
``success=False`` instead of re-raising (see
``verenigingen.utils.secure_operations.is_duplicate_key_error``'s docstring
for the full mechanism and why only the literal text "Duplicate entry"
survives into ``SecureOperationResult.errors``). A test that wants to
exercise a caller's duplicate-key recovery therefore needs a fake
``SecureOperationResult`` shaped like that swallowed exception, not a raised
one.

This was independently duplicated three times (``test_setup_workflow_
definitions.py``, ``test_tegenrekening_mapper_coverage.py``, ``test_cost_
center_fix.py`` -- all written for the same #1336 finding) before
``scripts/validation/duplicate_helper_validator.py`` flagged the third copy.
Import this instead of writing another one.
"""

from verenigingen.utils.secure_operations import SecureOperationResult


def duplicate_key_result(
    doctype: str, name: str, operation_id: str = "test_duplicate_key_race"
) -> SecureOperationResult:
    """A failed ``SecureOperationResult`` shaped exactly like a real MariaDB
    1062 duplicate-key violation that ``secure_document_operation()`` caught
    and reported as ``success=False``."""
    result = SecureOperationResult(False, operation_id)
    result.add_error(
        f"Operation failed: ('{doctype}', '{name}', "
        f"IntegrityError(1062, \"Duplicate entry '{name}' for key 'PRIMARY'\"))"
    )
    return result
