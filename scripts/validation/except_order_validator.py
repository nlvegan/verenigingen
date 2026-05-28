#!/usr/bin/env python3
"""
Except-Clause Order Validator
=============================

Catches the bug pattern PR #107 navigated: in a single ``try`` block,
``except frappe.ValidationError`` listed BEFORE ``except frappe.PermissionError``
will swallow our local ``verenigingen.utils.error_handling.PermissionError``
exception, because post-#107 our class multi-inherits from both. Source-order
matching means whichever handler appears first wins — so the
PermissionError-specific branch never fires, losing the dedicated error_code
and routing logic.

The rule is intentionally narrow for v1:

    In any single ``try`` block whose ``except`` handlers reference BOTH
    ``frappe.ValidationError`` (or just ``ValidationError`` when imported
    from frappe) AND ``frappe.PermissionError`` (or ``PermissionError``),
    the PermissionError handler MUST appear before the ValidationError
    handler.

Standard Python built-in cases (``except OSError`` before
``except FileNotFoundError``, etc.) are out of scope for v1 because they're
typically caught in code review and pylint can be re-enabled for those.
This validator targets the project-specific pattern that motivated the lint.

Usage
-----
    python scripts/validation/except_order_validator.py path/to/file.py [...]

Returns non-zero exit code if violations are found.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Violation:
    file_path: str
    line_number: int
    try_line: int
    message: str


def _qualified_exception_name(node: ast.expr) -> str | None:
    """Return a normalised name for an exception type expression.

    Handles:
    - ``ValidationError`` (Name) → ``ValidationError``
    - ``frappe.ValidationError`` (Attribute) → ``frappe.ValidationError``
    - Anything else (subscripts, calls, parens) → None (skip)
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        # Walk the attribute chain
        parts = [node.attr]
        cursor = node.value
        while isinstance(cursor, ast.Attribute):
            parts.append(cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name):
            parts.append(cursor.id)
            return ".".join(reversed(parts))
    return None


def _handler_exception_names(handler: ast.ExceptHandler) -> list[str]:
    """Return all exception type names referenced by an except handler.

    ``except A:`` → ["A"]
    ``except (A, B):`` → ["A", "B"]
    ``except:`` (bare) → []
    """
    if handler.type is None:
        return []
    if isinstance(handler.type, ast.Tuple):
        return [
            name
            for elt in handler.type.elts
            for name in [_qualified_exception_name(elt)]
            if name is not None
        ]
    name = _qualified_exception_name(handler.type)
    return [name] if name is not None else []


def _imports_from_frappe(tree: ast.Module) -> set[str]:
    """Return the set of ORIGINAL exception names imported from ``frappe``.

    For ``from frappe import ValidationError`` we add ``"ValidationError"``
    to the set so a bare ``except ValidationError:`` later in the file is
    recognised as ``frappe.ValidationError``.

    Aliased imports (``from frappe import ValidationError as VE``) are
    intentionally NOT resolved: we add the original name only, ignoring
    the alias. This is a documented v1 gap — see
    ``test_aliased_import_is_v1_gap`` in the regression suite. Aliased
    exception imports are rare in this codebase; resolving them would
    require tracking the alias as a synonym for the original name, which
    isn't worth the complexity for v1.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "frappe":
            for alias in node.names:
                if alias.asname is None:
                    names.add(alias.name)
    return names


def _is_frappe_validation_error(name: str, frappe_imports: set[str]) -> bool:
    if name == "frappe.ValidationError":
        return True
    return name == "ValidationError" and "ValidationError" in frappe_imports


def _is_frappe_permission_error(name: str, frappe_imports: set[str]) -> bool:
    if name == "frappe.PermissionError":
        return True
    return name == "PermissionError" and "PermissionError" in frappe_imports


def check_file(file_path: Path) -> list[Violation]:
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        # Don't fail the lint on unparseable files — that's another tool's job.
        return []

    frappe_imports = _imports_from_frappe(tree)
    violations: list[Violation] = []

    # PEP 654 ``try/except*`` (exception groups, Python 3.11+) is a
    # separate AST node from ``ast.Try``. Both are inspected so the
    # ordering rule applies uniformly to exception-group blocks too.
    try_node_types: tuple[type, ...] = (ast.Try,)
    if hasattr(ast, "TryStar"):
        try_node_types = (ast.Try, ast.TryStar)

    for node in ast.walk(tree):
        if not isinstance(node, try_node_types):
            continue

        seen_validation_line: int | None = None
        for handler in node.handlers:
            names = _handler_exception_names(handler)
            catches_validation = any(
                _is_frappe_validation_error(n, frappe_imports) for n in names
            )
            catches_permission = any(
                _is_frappe_permission_error(n, frappe_imports) for n in names
            )

            if catches_permission and seen_validation_line is not None:
                # A previous handler already caught frappe.ValidationError;
                # this PermissionError handler is unreachable for our
                # multi-inherited ``verenigingen.utils.error_handling.PermissionError``.
                violations.append(
                    Violation(
                        file_path=str(file_path),
                        line_number=handler.lineno,
                        try_line=node.lineno,
                        message=(
                            f"`except frappe.PermissionError` at line {handler.lineno} is "
                            f"shadowed by `except frappe.ValidationError` at line "
                            f"{seen_validation_line}. Post-PR #107 our local "
                            f"`verenigingen.utils.error_handling.PermissionError` "
                            f"multi-inherits from both, so the ValidationError handler "
                            f"matches first and the PermissionError branch never fires. "
                            f"Reorder: PermissionError handler must come before "
                            f"ValidationError handler in the same try block."
                        ),
                    )
                )

            if catches_validation and seen_validation_line is None:
                seen_validation_line = handler.lineno

    return violations


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv[1:]]
    if not paths:
        print("usage: except_order_validator.py FILE [FILE ...]", file=sys.stderr)
        return 2

    total_violations = 0
    for path in paths:
        if not path.is_file() or path.suffix != ".py":
            continue
        for v in check_file(path):
            total_violations += 1
            print(f"{v.file_path}:{v.line_number}: {v.message}")

    if total_violations:
        print(
            f"\n{total_violations} except-clause ordering violation(s) found. "
            f"See PR #107 for context.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
