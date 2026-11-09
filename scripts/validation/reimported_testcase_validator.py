#!/usr/bin/env python3
"""Blocks a test module that binds ANOTHER module's runnable TestCase at module level (#1939).

unittest's loader (and Frappe's runner, which uses it) collects every `TestCase`
subclass found in a module's namespace, whatever module defined it. So

    from verenigingen.x.test_foo import TestFoo       # unused or used only to run it

makes `TestFoo`'s tests run a SECOND time under the importing module. Measured on
develop (2026-11-06): `tests/utils/test_helpers.py` collected 21 tests and ran none of
its own; `tests/sepa/test_iban_validator.py` (a `from ... import *` "bridge") collected
23; `test_sepa_mandate_runner.py` re-ran 16 and `test_comprehensive_suite_demo.py` 3.

Flagged, in any file named `test_*.py`, at module level (including inside module-level
`if`/`try`/`with`):
  * `from m import Cls` / `from m import Cls as X`
  * `from m import *`
  * `X = Cls` / `X = mod.Cls`
where the target resolves to a class that is a TestCase (a base named `*TestCase`)
AND has at least one `test*` method, own or inherited through bases defined in this
repo. A TestCase with no test methods (EnhancedTestCase, mixins, ...) collects nothing
and is fine to import. Imports inside a function body are fine (nothing binds the
class at module level). To reach a donor's class without re-collecting it, import the
MODULE and use `module.Cls`.

NO ALLOWLIST: the tree is clean, so any hit fails. Files not named `test_*.py` are not
collected by the loader and are out of scope.

Usage:
    python scripts/validation/reimported_testcase_validator.py
"""

import ast
import os
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "env", "__pycache__", ".venv"}


class Index:
    """Lazily parses repo modules; resolves dotted module names to files under root."""

    def __init__(self, root: Path):
        self.root = root
        self._parsed = {}

    def path_for(self, dotted: str):
        base = self.root.joinpath(*dotted.split("."))
        for cand in (base.with_suffix(".py"), base / "__init__.py"):
            if cand.is_file():
                return cand
        return None

    def parse(self, path: Path, importer=False):
        if path not in self._parsed:
            try:
                text = path.read_text(encoding="utf-8")
                # Cheap prefilter (parsing every production module costs ~25s tree-wide): a file
                # that names neither TestCase nor a test method cannot define a runnable TestCase,
                # except a subclass of a TestCase-bearing base that adds nothing itself.
                self._parsed[path] = ast.parse(text) if (importer or "TestCase" in text or "def test" in text) else None
            except (SyntaxError, UnicodeDecodeError, OSError):
                self._parsed[path] = None
        return self._parsed[path]

    def classes(self, path: Path):
        tree = self.parse(path)
        if tree is None:
            return {}
        return {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}


def _module_level(body):
    for node in body:
        yield node
        if isinstance(node, (ast.If, ast.Try, ast.With)):
            groups = [node.body, getattr(node, "orelse", []), getattr(node, "finalbody", [])]
            if isinstance(node, ast.If) and ast.unparse(node.test).endswith("TYPE_CHECKING"):
                groups = groups[1:]  # never executed at runtime, so nothing is bound
            groups += [h.body for h in getattr(node, "handlers", [])]
            for group in groups:
                yield from _module_level(group)


def _abs_module(current: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    parts = current.split(".")[: -node.level]
    return ".".join(parts + ([node.module] if node.module else []))


def _from_imports(index: Index, tree, current: str):
    """{bound name: (dotted module, original name)} for module-level `from` imports."""
    out = {}
    for node in _module_level(tree.body):
        if isinstance(node, ast.ImportFrom):
            mod = _abs_module(current, node)
            for a in node.names:
                if a.name != "*":
                    out[a.asname or a.name] = (mod, a.name)
    return out


def is_runnable_testcase(index: Index, dotted: str, name: str, _seen=None) -> bool:
    """True if `name` in module `dotted` is a TestCase with a test* method (own or inherited)."""
    _seen = _seen if _seen is not None else set()
    path = index.path_for(dotted)
    cls = index.classes(path).get(name) if path else None
    if cls is None:
        return False
    return _testcase_state(index, dotted, path, cls, _seen)[0]


def _testcase_state(index, dotted, path, cls, seen):
    """(is runnable TestCase, has test method) folded over the MRO we can see."""
    if (dotted, cls.name) in seen:  # cycle / diamond already visited
        return False, False
    seen.add((dotted, cls.name))
    is_tc = has_tests = False
    if any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")
        for n in cls.body
    ):
        has_tests = True
    imports = _from_imports(index, index.parse(path), dotted)
    local = index.classes(path)
    for base in cls.bases:
        bname = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if bname.endswith("TestCase"):
            is_tc = True
        if bname in local:
            sub_tc, sub_tests = _testcase_state(index, dotted, path, local[bname], seen)
        elif bname in imports:
            tmod, tname = imports[bname]
            tpath = index.path_for(tmod)
            tcls = index.classes(tpath).get(tname) if tpath else None
            sub_tc, sub_tests = (
                _testcase_state(index, tmod, tpath, tcls, seen) if tcls else (False, False)
            )
        else:
            continue
        is_tc, has_tests = is_tc or sub_tc, has_tests or sub_tests
    return (is_tc and has_tests), has_tests


def scan_file(index: Index, path: Path, dotted: str):
    """Return [(lineno, bound name, 'module.Class')] for re-collected TestCases in one file."""
    index._parsed.pop(path, None)  # an importer is parsed unconditionally, never prefiltered
    tree = index.parse(path, importer=True)
    if tree is None:
        return []
    hits = []
    module_alias = {}
    for node in _module_level(tree.body):
        if isinstance(node, ast.Import):
            for a in node.names:
                module_alias[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            mod = _abs_module(dotted, node)
            for a in node.names:
                if a.name == "*":
                    mpath = index.path_for(mod)
                    for cname in index.classes(mpath) if mpath else []:
                        if is_runnable_testcase(index, mod, cname):
                            hits.append((node.lineno, "*", f"{mod}.{cname}"))
                elif is_runnable_testcase(index, mod, a.name):
                    hits.append((node.lineno, a.asname or a.name, f"{mod}.{a.name}"))
                elif index.path_for(f"{mod}.{a.name}"):
                    module_alias[a.asname or a.name] = f"{mod}.{a.name}"
        elif isinstance(node, ast.Assign) and not isinstance(node.value, ast.Call):
            hit = _alias_hit(index, node, dotted, path, module_alias)
            if hit:
                hits.append(hit)
    return hits


def _alias_hit(index, node, dotted, path, module_alias):
    value = node.value
    if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
        mod = module_alias.get(value.value.id)
        if mod and is_runnable_testcase(index, mod, value.attr):
            return (node.lineno, ast.unparse(node.targets[0]), f"{mod}.{value.attr}")
    elif isinstance(value, ast.Name):
        imports = _from_imports(index, index.parse(path), dotted)
        mod, name = imports.get(value.id, (dotted, value.id))
        if is_runnable_testcase(index, mod, name):
            return (node.lineno, ast.unparse(node.targets[0]), f"{mod}.{name}")
    return None


def scan(root: Path):
    index = Index(root)
    violations = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if not (fname.startswith("test_") and fname.endswith(".py")):
                continue
            path = Path(dirpath) / fname
            dotted = ".".join(path.relative_to(root).with_suffix("").parts)
            for lineno, bound, target in scan_file(index, path, dotted):
                violations.append((path.relative_to(root), lineno, bound, target))
    return sorted(violations)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    violations = scan(root)
    for rel, lineno, bound, target in violations:
        print(
            f"{rel}:{lineno}: module-level `{bound}` binds {target}, a TestCase with tests; the loader "
            "runs its tests again under this module (#1939). Import the module and use "
            "`module.Class`, or import inside the function that needs it."
        )
    if violations:
        print(f"{len(violations)} re-collected TestCase binding(s).")
        return 1
    print("No test module re-collects another module's TestCase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
