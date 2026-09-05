#!/usr/bin/env python3
"""Blocks a test-local method whose name and arity cannot coexist with a harness
method the harness itself calls on `self`.

The defect (#496): a test class defines a method with the same name as one that
`EnhancedTestCase` (or `VereningingenTestCase`, the app's other harness base) calls
internally as `self.<name>(...)`. Python's MRO dispatch resolves that call to the
LOCAL override instead of the harness method, so the harness behaviour everyone
assumes is running simply is not.

One instance of this shape was FATAL: `MollieBase._ensure_company_cost_center(self)`
overrode `EnhancedTestCase._ensure_company_cost_center(self, company_name)`, which the
harness calls from every `setUp()`. Every test in that module errored for 12 days
(`e16523d6`, 2026-08-11 -> the #194 PR, 2026-08-22) before anyone noticed -- the
failure read as a master-data problem, not a signature mismatch. #496's census found
28 further instances: some already fatal-if-triggered (an incompatible arity), all of
them silent regardless, because nothing about a passing test run announces "a shadow
exists but its trigger was never pulled."

WHAT THIS GUARD CHECKS (and why it stops here)
-----------------------------------------------
A subclass method whose SIGNATURE cannot bind the arguments the harness passes at its
own internal call site: `self.<name>(<args the harness itself supplies>)`. That is a
certain TypeError the moment the harness reaches that call site -- exactly what made
#194 fatal, and what #884/#496's arity-mismatched instances would raise once triggered.

It deliberately does NOT flag a shadow whose signature happens to match (same arity)
-- a local `_get_test_company(self)` that returns a different company than the
harness's `_get_test_company(self)`, say. That is a real, silent behaviour swap (#496
found several), but it never raises, so a shape-only static check cannot tell it apart
from an intentional, compatible, cooperative override (a subclass `create_test_donor`
that calls `super().create_test_donor(...)` and adds a default -- #496 found several of
these too, and they are correct code, not defects). Distinguishing "replaces silently"
from "delegates cooperatively" needs reading intent, not signatures; the #496 issue's
own review thread reached the same conclusion and scoped a guard to arity for exactly
this reason. NO ALLOWLIST: unlike some ratchets in this repo, this one starts at zero
known violations (the #496 PR fixed every one that existed) and any new occurrence
fails immediately -- nothing to rot.

Usage:
    python scripts/validation/harness_method_shadow_validator.py              # check
    python scripts/validation/harness_method_shadow_validator.py --report     # verbose
"""

import argparse
import inspect
import os
import sys
import typing
from ast import (
    AsyncFunctionDef,
    Attribute,
    ClassDef,
    FunctionDef,
    ImportFrom,
    Name,
    NodeVisitor,
    Starred,
    parse,
    walk,
)
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOT = "verenigingen"

# (harness file relative to SCAN_ROOT's parent, harness class name)
HARNESS_SPECS = [
    ("verenigingen/tests/fixtures/enhanced_test_factory.py", "EnhancedTestCase"),
    ("verenigingen/tests/utils/base.py", "VereningingenTestCase"),
]

EXCLUDE_DIR_PARTS = {
    "archived_unused",
    "archived_deleted",
    "archived_removal",
    "node_modules",
    ".git",
}


@dataclass
class CallSite:
    lineno: int
    n_pos: int
    kw_names: list
    has_star_kwargs: bool


@dataclass
class HarnessInfo:
    class_name: str
    file_path: Path
    # method name -> its ast.FunctionDef/AsyncFunctionDef node
    methods: dict = field(default_factory=dict)
    # method name -> list of CallSite, for self.<name>(...) calls made FROM WITHIN
    # the harness class body itself
    self_calls: dict = field(default_factory=dict)


@dataclass
class ClassInfo:
    file_path: Path
    lineno: int
    name: str
    bases: list
    methods: dict  # name -> FunctionDef/AsyncFunctionDef node


@dataclass
class Violation:
    file_path: Path
    class_name: str
    method_name: str
    method_lineno: int
    harness_class: str
    harness_file: Path
    call_lineno: int
    error: str


def _iter_python_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_PARTS and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def _base_name(node):
    if isinstance(node, Name):
        return node.id
    if isinstance(node, Attribute):
        return node.attr
    return None


def _parse(path: Path):
    try:
        return parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


def _extract_harness_info(harness_file: Path, class_name: str) -> HarnessInfo:
    info = HarnessInfo(class_name=class_name, file_path=harness_file)
    tree = _parse(harness_file)
    if tree is None:
        return info

    class _Visitor(NodeVisitor):
        def __init__(self):
            self.class_stack = []

        def visit_ClassDef(self, node):
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def visit_FunctionDef(self, node):
            if self.class_stack and self.class_stack[-1] == class_name:
                info.methods[node.name] = node
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            if (
                self.class_stack
                and self.class_stack[-1] == class_name
                and isinstance(node.func, Attribute)
                and isinstance(node.func.value, Name)
                and node.func.value.id == "self"
            ):
                name = node.func.attr
                n_pos = sum(1 for a in node.args if not isinstance(a, Starred))
                kw_names = [k.arg for k in node.keywords if k.arg is not None]
                has_star_kwargs = any(k.arg is None for k in node.keywords)
                info.self_calls.setdefault(name, []).append(
                    CallSite(node.lineno, n_pos, kw_names, has_star_kwargs)
                )
            self.generic_visit(node)

    _Visitor().visit(tree)
    return info


def _module_dotted_to_path(repo_root: Path, dotted: str) -> Path:
    return repo_root / (dotted.replace(".", "/") + ".py")


def _collect_classes_and_imports(root: Path, repo_root: Path):
    """Return (classes_by_file, imports_by_file).

    classes_by_file[file][class_name] -> ClassInfo, for every class DEFINED in
    that file. imports_by_file[file][local_name] -> (target_file, target_name),
    resolved from `from <dotted> import <name> [as <local_name>]` statements
    whose module starts with the app package -- the only imports we can chase to
    another file. Anything else (frappe.*, unittest.TestCase, a relative import)
    is left unresolved: a base name that isn't a local class and isn't in this
    map is a dead end, which is the correct, conservative answer -- we only need
    to prove "yes, this IS the harness", never disprove it.
    """
    classes_by_file: dict = {}
    imports_by_file: dict = {}

    for path in _iter_python_files(root):
        tree = _parse(path)
        if tree is None:
            continue

        file_classes = {}
        for node in walk(tree):
            if isinstance(node, ClassDef):
                methods = {
                    item.name: item
                    for item in node.body
                    if isinstance(item, (FunctionDef, AsyncFunctionDef))
                }
                file_classes[node.name] = ClassInfo(
                    file_path=path,
                    lineno=node.lineno,
                    name=node.name,
                    bases=[_base_name(b) for b in node.bases],
                    methods=methods,
                )
        classes_by_file[path] = file_classes

        file_imports = {}
        for node in tree.body:
            if isinstance(node, ImportFrom) and node.level == 0 and node.module:
                if not (node.module == "verenigingen" or node.module.startswith("verenigingen.")):
                    continue
                target_file = _module_dotted_to_path(repo_root, node.module)
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    file_imports[local_name] = (target_file, alias.name)
        imports_by_file[path] = file_imports

    return classes_by_file, imports_by_file


def _harness_subclasses(classes_by_file, imports_by_file, harness_class_name, harness_file):
    def is_harness_subclass(file_path, name, seen=None):
        if file_path == harness_file and name == harness_class_name:
            return True
        if seen is None:
            seen = set()
        key = (file_path, name)
        if key in seen:
            return False
        seen.add(key)

        # An imported name is resolved to its OWN defining file first -- this is
        # what tells apart two same-named classes in different modules (the
        # `BaseTestCase` collision #496's own review caught: one file's
        # `BaseTestCase` is `EnhancedTestCase` itself; a different file's
        # `BaseTestCase` is an unrelated class that merely shares the name).
        imported = imports_by_file.get(file_path, {}).get(name)
        if imported is not None:
            target_file, target_name = imported
            return is_harness_subclass(target_file, target_name, seen)

        local = classes_by_file.get(file_path, {}).get(name)
        if local is None:
            return False
        for b in local.bases:
            if b and is_harness_subclass(file_path, b, seen):
                return True
        return False

    result = []
    for file_path, file_classes in classes_by_file.items():
        for c in file_classes.values():
            if file_path == harness_file and c.name == harness_class_name:
                continue
            if any(b and is_harness_subclass(file_path, b) for b in c.bases):
                result.append(c)
    return result


def _build_stub_signature(func_node) -> inspect.Signature:
    """Compile just the `def ...(...): pass` header for func_node and return its
    inspect.Signature, so we can call .bind() against a call site's shape without
    executing the method body."""
    import ast as _ast

    args = func_node.args
    header = _ast.FunctionDef(
        name="_stub",
        args=args,
        body=[_ast.Pass()],
        decorator_list=[],
        returns=None,
        lineno=1,
        col_offset=0,
    )
    module = _ast.Module(body=[header], type_ignores=[])
    _ast.fix_missing_locations(module)
    ns = {k: getattr(typing, k) for k in dir(typing) if not k.startswith("_")}
    try:
        code = compile(module, "<stub>", "exec")
        exec(code, ns)
    except Exception as e:  # noqa: BLE001 - a header we can't compile is not our call to make
        raise ValueError(f"could not build stub signature: {e}") from e
    return inspect.signature(ns["_stub"])


def _call_binds(sig: inspect.Signature, call: CallSite) -> tuple:
    """Return (ok, error) for whether `self.<name>(...)` at `call`'s shape would
    bind against `sig` (the subclass method's signature, self included)."""
    dummy_self = object()
    args = [dummy_self] + ["X"] * call.n_pos
    kwargs = {name: "X" for name in call.kw_names}
    if call.has_star_kwargs:
        kwargs["_dummy_extra_kwarg_496"] = "X"
    try:
        sig.bind(*args, **kwargs)
        return True, None
    except TypeError as e:
        return False, str(e)


def scan(root: Path, harness_specs=HARNESS_SPECS):
    """Return a list of Violations found under `root`.

    `harness_specs` is a list of (path-relative-to-root, class_name) pairs, so tests
    can point this at a small synthetic tree instead of the real harness files.
    `root` doubles as the repo root for resolving `from verenigingen.x.y import Z`
    imports to a file -- true for the real scan, and for a synthetic tree that
    mirrors the app's own package layout under it.
    """
    violations = []
    classes_by_file, imports_by_file = _collect_classes_and_imports(root, root)

    for rel_path, harness_class_name in harness_specs:
        harness_file = root / rel_path
        if not harness_file.exists():
            continue
        info = _extract_harness_info(harness_file, harness_class_name)
        # Only methods the harness invokes on itself are dangerous to shadow --
        # matches #496's finding that most of the census was otherwise inert.
        self_invoked = {name for name in info.methods if name in info.self_calls}

        for sub in _harness_subclasses(classes_by_file, imports_by_file, harness_class_name, harness_file):
            for method_name, func_node in sub.methods.items():
                if method_name not in self_invoked:
                    continue
                try:
                    sub_sig = _build_stub_signature(func_node)
                except ValueError:
                    continue  # can't build a signature for this shape; not our call
                for call in info.self_calls[method_name]:
                    ok, err = _call_binds(sub_sig, call)
                    if not ok:
                        violations.append(
                            Violation(
                                file_path=sub.file_path,
                                class_name=sub.name,
                                method_name=method_name,
                                method_lineno=func_node.lineno,
                                harness_class=harness_class_name,
                                harness_file=harness_file,
                                call_lineno=call.lineno,
                                error=err,
                            )
                        )
    return violations


def _format_violation(v: Violation, repo_root: Path) -> str:
    try:
        rel = v.file_path.relative_to(repo_root)
    except ValueError:
        rel = v.file_path
    return (
        f"{rel}:{v.method_lineno} {v.class_name}.{v.method_name}() shadows "
        f"{v.harness_class}.{v.method_name}(), called internally at "
        f"{v.harness_file.name}:{v.call_lineno} -- {v.error}"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", action="store_true", help="Print every violation found (default: same output)."
    )
    args = parser.parse_args(argv)

    root = REPO_ROOT
    violations = scan(root, HARNESS_SPECS)

    if not violations:
        print("Harness Method Shadow Guard: no shadowed harness methods with an incompatible arity.")
        return 0

    print(f"Harness Method Shadow Guard: {len(violations)} violation(s) found.\n")
    for v in sorted(violations, key=lambda v: (str(v.file_path), v.method_lineno)):
        print("  " + _format_violation(v, root))
    print(
        "\nEach of these defines a method matching a harness (EnhancedTestCase / "
        "VereningingenTestCase) method name that the harness calls on itself, with a "
        "signature that cannot accept the arguments the harness passes -- a certain "
        "TypeError the moment that call site is reached (see #496; one instance of "
        "this shape broke 38/38 tests silently for 12 days). Rename the local method "
        "(the fix in every #496 case) so it no longer shares the harness's name, or "
        "make its signature accept what the harness will pass."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
