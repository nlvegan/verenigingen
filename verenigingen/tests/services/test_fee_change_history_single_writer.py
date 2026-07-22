# Copyright (c) 2026, Veganisme.org and contributors
# For license information, please see license.txt

"""
Single-writer invariant guard for the fee_change_history child table.

Every production writer of Member.fee_change_history must go through
MemberFeeChangeHistoryService.add_fee_change_to_history /
update_fee_change_in_history, which is the one place that applies the row
schema, dedup, billing-frequency validation, old_dues_rate default, and the
50-row cap.

Historically several sites appended rows directly
(`member_doc.append("fee_change_history", {...})`), producing divergent rows
(e.g. missing old_dues_rate, no dedup). Those were routed through the service;
this test fails if a new direct-append bypass is reintroduced in production code.

NOTE: this guards the child-table append path only. The separate, still-unwired
FeeOverrideHookService._update_fee_change_history (which writes malformed data to
a non-existent column via raw SQL) is dead code tracked as its own follow-up and
is intentionally out of this guard's scope.
"""

import re
import unittest
from pathlib import Path

import verenigingen

# Matches member_doc.append("fee_change_history", ...) / .append('fee_change_history', ...)
APPEND_RE = re.compile(r"""\.append\(\s*['"]fee_change_history['"]""")

# The one production module allowed to append directly: the canonical writer.
ALLOWED = {"services/member/history/member_fee_change_history_service.py"}


class TestFeeChangeHistorySingleWriter(unittest.TestCase):
    def test_no_direct_fee_change_history_appends_outside_service(self):
        app_root = Path(verenigingen.__file__).resolve().parent
        offenders = []

        for py in app_root.rglob("*.py"):
            rel = py.relative_to(app_root).as_posix()
            # Skip tests (fixtures legitimately build rows) and caches. Test modules
            # may live under a tests/ dir OR be co-located next to the code they cover
            # (e.g. services/billing/test_*.py), so match the filename too.
            if "/tests/" in f"/{rel}" or rel.startswith("tests/") or py.name.startswith("test_"):
                continue
            if "__pycache__" in rel:
                continue
            if rel in ALLOWED:
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if APPEND_RE.search(text):
                offenders.append(rel)

        self.assertEqual(
            offenders,
            [],
            "Direct fee_change_history append() found outside "
            "MemberFeeChangeHistoryService. Route these through "
            "get_member_fee_change_history_service().add_fee_change_to_history() so "
            f"every row is built consistently. Offending files: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
