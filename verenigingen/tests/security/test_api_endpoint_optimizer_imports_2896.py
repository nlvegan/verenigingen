"""#2896: every decorator the endpoint optimizer inserts must have its name bound in the rewritten file.

`_add_imports` used to return early whenever the file already imported *anything* from
``verenigingen.utils.error_handling``, while `_optimize_endpoints` inserted its decorators
unconditionally, so such a file raised NameError at import. The generated block also never
imported ``Roles``, which ``@require_roles(list(Roles.ADMIN_PAIR))`` needs.

Plain unittest: the optimizer is a source rewriter, so the test drives the real rewrite
(`_optimize_file`, dry_run=False) on a temp file and then executes the rewritten module.
"""

import logging
import tempfile
import unittest
from pathlib import Path

from verenigingen.utils.api_endpoint_optimizer import APIEndpointOptimizer

_ENDPOINTS = (
    "\n\n@frappe.whitelist()\ndef get_item(name):\n    return name\n"
    "\n\n@frappe.whitelist()\ndef bulk_export_items(name):\n    return name\n"
    "\n\n@frappe.whitelist()\ndef approve_item(name):\n    return name\n"
)

_SOURCES = {
    "no_prior_imports_from_error_handling": "import frappe\n" + _ENDPOINTS,
    "already_imports_from_error_handling": (
        "import frappe\nfrom verenigingen.utils.error_handling import get_logger\n" + _ENDPOINTS
    ),
    # Binds ONE of the names the block would import: guards against an "any name bound" shortcut.
    "already_binds_one_of_the_names": (
        "import frappe\nfrom verenigingen.utils.error_handling import log_error\n" + _ENDPOINTS
    ),
}


def _rewrite_on_disk_2896(source):
    optimizer = APIEndpointOptimizer.__new__(APIEndpointOptimizer)
    optimizer.logger = logging.getLogger("test_2896")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample_api.py"
        path.write_text(source, encoding="utf-8")
        optimizer._optimize_file(path, dry_run=False)
        return path.read_text(encoding="utf-8")


class TestOptimizerBindsEveryDecoratorName2896(unittest.TestCase):
    def test_rewritten_module_imports_without_name_error(self):
        for label, source in _SOURCES.items():
            with self.subTest(source=label):
                rewritten = _rewrite_on_disk_2896(source)
                self.assertIn("@handle_api_error", rewritten, "control: decorators must have been inserted")
                self.assertIn("@require_roles", rewritten, "control: the Roles decorator must be exercised")
                exec(compile(rewritten, label, "exec"), {})  # noqa: S102 - our own rewritten fixture

    def test_a_file_that_already_binds_every_name_gets_no_import_block(self):
        optimizer = APIEndpointOptimizer.__new__(APIEndpointOptimizer)
        fully_imported = optimizer._add_imports("import frappe\n")
        self.assertIn("# Import enhanced utilities", fully_imported, "control: the block is added when needed")
        self.assertEqual(optimizer._add_imports(fully_imported), fully_imported)
