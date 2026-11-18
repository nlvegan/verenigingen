"""Load every module that binds ``get_email_service`` at import time, before any test patches it (#2438).

``from ...email_service import get_email_service`` copies the factory into the importing module. A
test that does ``patch("verenigingen.services.communication.email_service.get_email_service")`` (about
30 sites do) and so FIRST imports one of those modules while the patch is active makes the module
bind the MagicMock. ``patch`` of the module's own attribute then saves the mock as the "original" and
restores it, so the mock outlives the test and silences every later test of that module: a
shard-only red (#2437, merge-queue build 42926880094).

Importing the binders once, when the ``verenigingen.tests`` package loads, makes that impossible for
every test at once: a module already in ``sys.modules`` is never re-executed under a later patch. The
list is discovered from the source tree (AST), so a new binder is covered without editing anything.
"""

import ast
import importlib
from pathlib import Path

import verenigingen

FACTORY_MODULE = "verenigingen.services.communication.email_service"
FACTORY_NAME = "get_email_service"
_SKIPPED_PARTS = {"tests", "node_modules", "__pycache__"}


def preload_email_factory_binders():
    """Import every module-level binder of the factory; returns their dotted names."""
    names = find_email_factory_binders()
    for name in names:
        importlib.import_module(name)
    return names


def find_email_factory_binders():
    """Dotted names of non-test modules that bind the factory at import time (sorted)."""
    root = Path(verenigingen.__file__).resolve().parent
    found = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if _SKIPPED_PARTS & set(rel.parts) or path.name.startswith("test_"):
            continue
        module = ".".join(("verenigingen", *rel.with_suffix("").parts))
        if module.endswith(".__init__"):
            module = module[: -len(".__init__")]
        if _binds_factory_at_import(path, module, is_package=path.name == "__init__.py"):
            found.append(module)
    return found


def _binds_factory_at_import(path, module, is_package):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return False
    return any(
        _imports_factory(node, module, is_package) for node in _module_level_statements(tree.body)
    )


def _module_level_statements(body):
    """Statements that run at import: the body, plus the arms of top-level if/try (not functions)."""
    for node in body:
        yield node
        if isinstance(node, ast.If):
            yield from _module_level_statements(node.body + node.orelse)
        elif isinstance(node, ast.Try):
            handlers = [stmt for h in node.handlers for stmt in h.body]
            yield from _module_level_statements(node.body + handlers + node.orelse + node.finalbody)


def _imports_factory(node, module, is_package):
    if not isinstance(node, ast.ImportFrom) or not any(a.name == FACTORY_NAME for a in node.names):
        return False
    if node.level:
        package = module.split(".") if is_package else module.split(".")[:-1]
        package = package[: len(package) - (node.level - 1)]
        source = ".".join(package + ([node.module] if node.module else []))
    else:
        source = node.module
    return source == FACTORY_MODULE
