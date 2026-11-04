#!/usr/bin/env python3
"""Advisory check: flag test changes that make the suite easier to pass (#2061).

Compares the test files a branch changes against the merge base and lists:

1. tests removed (counted across ALL changed test files, so a moved test is not
   a finding; a test removed together with the production code it exercised is
   listed separately as "cleanup");
2. assertions removed: >= 2 assertion calls gone from a test that still exists;
3. constant asserts added (``assertTrue(True)``, ``assert True``, ``assertEqual(1, 1)``);
4. new skips (``skipTest``, skip decorators, ``raise SkipTest``, an early
   ``return`` before the first assertion).

An "assertion" is any call whose name starts with ``assert`` plus bare ``assert``
statements, counted from the AST (never from comments or strings). The check is
diff-only: it needs no baseline and never reports pre-existing constant asserts.

Matching base tests to head tests (so moves/renames are not removals):
  1. same (class, method) name; 2. same method name in any class/file;
  3. a rename: the remaining base/head tests whose non-assert identifiers overlap
     (containment >= 0.6 of the smaller set, >= 1 shared). A paired rename is
     still subject to the assertion-removal and skip checks.

Assertions-removed suppression: if the head test gained a call to a NEW
``assert*/verify*/check*/expect*`` helper that the base test did not call, the
assertions are assumed delegated to it (e.g. ``self.assertDocExists``), so the
drop is not reported. Helper bodies are not inspected.

ADVISORY: always exits 0. Overlap check: ``harness_super_skip_validator.py``
guards setUp/tearDown ``super()`` calls, not skips, so nothing is reused from it.

Usage:
    python scripts/validation/weakened_test_validator.py                  # vs merge-base(origin/develop, HEAD)
    python scripts/validation/weakened_test_validator.py --base <ref> --head <ref>
"""

import argparse
import ast
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_BASE = "origin/develop"
MIN_ASSERTIONS_REMOVED = 2
SKIP_DECORATORS = {"skip", "skipIf", "skipUnless", "skipif", "expectedFailure", "xfail"}
HELPER_PREFIXES = ("assert", "_assert", "verify", "_verify", "check", "_check", "expect", "_expect")
MIN_SYMBOL_LEN = 5


@dataclass
class Finding:
    test: str  # "Class.method" (or "Class" for class-level skips)
    path: str
    line: int = 0
    detail: str = ""
    before: int = 0
    after: int = 0
    commented_out: bool = False


@dataclass
class Report:
    removed: list = field(default_factory=list)
    removed_cleanup: list = field(default_factory=list)
    assertions_removed: list = field(default_factory=list)
    assertions_cleanup: list = field(default_factory=list)
    constant_asserts: list = field(default_factory=list)
    new_skips: list = field(default_factory=list)
    notes: list = field(default_factory=list)


@dataclass
class FuncInfo:
    cls: str
    name: str
    path: str
    line: int
    node: ast.AST
    assertions: int = 0
    idents: frozenset = frozenset()
    delegates: frozenset = frozenset()
    constants: list = field(default_factory=list)  # [(text, line)]
    skips: list = field(default_factory=list)  # [(kind, line)]

    @property
    def qual(self):
        return f"{self.cls}.{self.name}" if self.cls else self.name

    @property
    def is_test(self):
        return self.name.startswith("test")


# --------------------------------------------------------------------------- AST


def _call_name(call):
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def _walk_own(node):
    """Walk a function body without descending into nested defs/classes/lambdas."""
    stack = list(ast.iter_child_nodes(node))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(n))


def _is_assertion(n):
    if isinstance(n, ast.Assert):
        return True
    return isinstance(n, ast.Call) and (_call_name(n) or "").startswith("assert")


def _truthy_const(n):
    return isinstance(n, ast.Constant) and n.value is not Ellipsis and bool(n.value)


def _falsy_const(n):
    return isinstance(n, ast.Constant) and n.value is not Ellipsis and not n.value


def _pure(n):
    return not any(isinstance(x, (ast.Call, ast.Await, ast.Yield)) for x in ast.walk(n))


def _constant_assertion_text(n):
    """The statement text if `n` asserts on a constant (can never fail), else None."""
    if isinstance(n, ast.Assert):
        return ast.unparse(n) if _truthy_const(n.test) else None
    if not isinstance(n, ast.Call):
        return None
    name, a = _call_name(n), n.args
    if name == "assertTrue" and a and _truthy_const(a[0]):
        return ast.unparse(n)
    if name == "assertFalse" and a and _falsy_const(a[0]):
        return ast.unparse(n)
    if name == "assertIsNotNone" and a and isinstance(a[0], ast.Constant) and a[0].value is not None:
        return ast.unparse(n)
    if name == "assertIsNone" and a and isinstance(a[0], ast.Constant) and a[0].value is None:
        return ast.unparse(n)
    if name in ("assertEqual", "assertEquals", "assertIs") and len(a) >= 2:
        if ast.dump(a[0]) == ast.dump(a[1]) and _pure(a[0]):
            return ast.unparse(n)
    return None


def _decorator_skips(decorators):
    out = []
    for d in decorators:
        target = d.func if isinstance(d, ast.Call) else d
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
        if name in SKIP_DECORATORS:
            out.append(("decorator @" + name, d.lineno))
    return out


def _body_skips(fn, is_test):
    skips, returns, first_assert = [], [], None
    for n in _walk_own(fn):
        if isinstance(n, ast.Call):
            name = _call_name(n)
            if name == "skipTest" or (
                name == "skip" and isinstance(n.func, ast.Attribute) and getattr(n.func.value, "id", "") == "pytest"
            ):
                skips.append((name, n.lineno))
        elif isinstance(n, ast.Raise) and n.exc is not None:
            exc = n.exc.func if isinstance(n.exc, ast.Call) else n.exc
            if (getattr(exc, "attr", None) or getattr(exc, "id", None)) == "SkipTest":
                skips.append(("raise SkipTest", n.lineno))
        elif isinstance(n, ast.Return):
            returns.append(n.lineno)
        if _is_assertion(n) and (first_assert is None or n.lineno < first_assert):
            first_assert = n.lineno
    if is_test and first_assert is not None:
        skips += [("early return", ln) for ln in returns if ln < first_assert]
    return skips


def _func_info(fn, cls, path):
    info = FuncInfo(cls=cls, name=fn.name, path=path, line=fn.lineno, node=fn)
    idents, delegates = set(), set()
    for n in _walk_own(fn):
        if _is_assertion(n):
            info.assertions += 1
            text = _constant_assertion_text(n)
            if text:
                info.constants.append((text, n.lineno))
        if isinstance(n, ast.Name):
            idents.add(n.id)
        elif isinstance(n, ast.Attribute):
            idents.add(n.attr)
        if isinstance(n, ast.Call):
            name = _call_name(n) or ""
            if name.startswith(HELPER_PREFIXES):
                delegates.add(name)
    info.idents = frozenset(i for i in idents if i != "self" and not i.startswith("assert"))
    info.delegates = frozenset(delegates)
    info.skips = _decorator_skips(fn.decorator_list) + _body_skips(fn, fn.name.startswith("test"))
    return info


def parse_funcs(source, path):
    """-> (funcs, class_skips). Unparseable source yields ([], {})."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], {}
    funcs, class_skips = [], {}

    def visit(body, cls):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append(_func_info(n, cls, path))
            elif isinstance(n, ast.ClassDef):
                skips = _decorator_skips(n.decorator_list)
                if skips:
                    class_skips[(path, n.name)] = skips
                visit(n.body, n.name)

    visit(tree.body, "")
    return funcs, class_skips


def _symbol_names(sources):
    names = set()
    for path, text in sources.items():
        if not path.endswith(".py"):
            continue
        try:
            for n in ast.walk(ast.parse(text)):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(n.name)
        except SyntaxError:
            continue
    return names


# ---------------------------------------------------------------------- matching


def _overlap(a, b):
    shared = len(a & b)
    small = min(len(a), len(b))
    return (shared / small if small else 0.0, shared)


def match_tests(base, head):
    """Pair base tests with head tests. -> (pairs, unmatched_base, unmatched_head)."""
    pairs, ub, uh = [], list(base), list(head)

    def phase(key_fn):
        nonlocal ub, uh
        index = {}
        for h in uh:
            index.setdefault(key_fn(h), []).append(h)
        still = []
        for b in ub:
            cands = index.get(key_fn(b))
            if cands:
                h = cands.pop(0)
                pairs.append((b, h))
                uh = [x for x in uh if x is not h]
            else:
                still.append(b)
        ub = still

    phase(lambda f: (f.cls, f.name))
    phase(lambda f: f.name)
    for b in list(ub):
        best, best_score = None, (0.0, 0)
        for h in uh:
            score = _overlap(b.idents, h.idents)
            if score[0] >= 0.6 and score[1] >= 1 and (score, h.cls == b.cls) > (best_score, best and best.cls == b.cls):
                best, best_score = h, score
        if best is not None:
            pairs.append((b, best))
            ub.remove(b)
            uh.remove(best)
    return pairs, ub, uh


# ----------------------------------------------------------------------- compare


def _is_cleanup(func, removed_symbols, deleted_stems, file_deleted):
    if func.idents & removed_symbols:
        return True
    if any(sym.lower() in func.name.lower() for sym in removed_symbols):
        return True
    stem = Path(func.path).stem
    return file_deleted and stem.startswith("test_") and stem[5:] in deleted_stems


def compare(base_tests, head_tests, base_prod=None, head_prod=None):
    base_prod, head_prod = base_prod or {}, head_prod or {}
    rep = Report()
    base_funcs, head_funcs, base_cls, head_cls = [], [], {}, {}
    for p, s in base_tests.items():
        f, c = parse_funcs(s, p)
        base_funcs += f
        base_cls.update(c)
    for p, s in head_tests.items():
        f, c = parse_funcs(s, p)
        head_funcs += f
        head_cls.update(c)

    pairs, ub, uh = match_tests([f for f in base_funcs if f.is_test], [f for f in head_funcs if f.is_test])

    removed_symbols = {
        n for n in _symbol_names(base_prod) - _symbol_names(head_prod) if len(n) >= MIN_SYMBOL_LEN
    }
    deleted_stems = {Path(p).stem for p in base_prod if p not in head_prod}
    head_text = "\n".join(head_tests.values())
    for b in ub:
        commented = bool(re.search(rf"^\s*#\s*(async\s+)?def\s+{re.escape(b.name)}\b", head_text, re.M))
        item = Finding(b.qual, b.path, b.line, commented_out=commented)
        cleanup = _is_cleanup(b, removed_symbols, deleted_stems, b.path not in head_tests) and not commented
        (rep.removed_cleanup if cleanup else rep.removed).append(item)

    for b, h in pairs:
        dropped = b.assertions - h.assertions
        if dropped >= MIN_ASSERTIONS_REMOVED and not (h.delegates - b.delegates):
            item = Finding(h.qual, h.path, h.line, before=b.assertions, after=h.assertions)
            # Asserting on code that was deleted in this diff is cleanup, not weakening.
            gone = (b.idents - h.idents) & removed_symbols
            (rep.assertions_cleanup if gone else rep.assertions_removed).append(item)

    _constant_asserts(rep, base_funcs, head_funcs)
    _new_skips(rep, pairs, uh, base_funcs, head_funcs, base_cls, head_cls)
    return rep


def _constant_asserts(rep, base_funcs, head_funcs):
    """Multiset diff of (method name, statement text) across all changed files."""
    seen = {}
    for f in base_funcs:
        for text, _ in f.constants:
            seen[(f.name, text)] = seen.get((f.name, text), 0) + 1
    for f in head_funcs:
        for text, line in f.constants:
            key = (f.name, text)
            if seen.get(key, 0) > 0:
                seen[key] -= 1
            else:
                rep.constant_asserts.append(Finding(f.qual, f.path, line, detail=text))


def _new_skips(rep, pairs, unmatched_head, base_funcs, head_funcs, base_cls, head_cls):
    base_of = {id(h): b for b, h in pairs}
    base_nontest = {(f.cls, f.name): f for f in base_funcs if not f.is_test}
    for h in head_funcs:
        if h.is_test:
            b = base_of.get(id(h))
        else:
            b = base_nontest.get((h.cls, h.name))
        before = len(b.skips) if b else 0
        if len(h.skips) > before:
            kinds = ", ".join(k for k, _ in h.skips[before:])
            rep.new_skips.append(Finding(h.qual, h.path, h.skips[before][1], detail=kinds))
    base_cls_count = {}
    for (_, name), sk in base_cls.items():
        base_cls_count[name] = base_cls_count.get(name, 0) + len(sk)
    for (path, name), sk in head_cls.items():
        if len(sk) > base_cls_count.get(name, 0):
            rep.new_skips.append(Finding(name, path, sk[0][1], detail=", ".join(k for k, _ in sk)))


# --------------------------------------------------------------------------- git


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def _is_test_path(path):
    p = Path(path)
    return p.suffix == ".py" and (p.name.startswith("test_") or p.name.endswith("_test.py") or "tests" in p.parts)


def _show(repo, ref, path):
    try:
        return _git(repo, "show", f"{ref}:{path}")
    except subprocess.CalledProcessError:
        return None


def collect(repo, base_ref, head_ref):
    merge_base = _git(repo, "merge-base", base_ref, head_ref).strip()
    changed = [
        line.split("\t") for line in _git(repo, "diff", "--name-status", "--no-renames", merge_base, head_ref, "--", "*.py").splitlines()
    ]
    bt, ht, bp, hp = {}, {}, {}, {}
    for status, path in changed:
        is_test = _is_test_path(path)
        if status != "A":
            text = _show(repo, merge_base, path)
            if text is not None:
                (bt if is_test else bp)[path] = text
        if status != "D":
            text = _show(repo, head_ref, path)
            if text is not None:
                (ht if is_test else hp)[path] = text
    return merge_base, bt, ht, bp, hp


SECTIONS = (
    ("removed", "tests removed"),
    ("removed_cleanup", "tests removed together with the code they covered (cleanup)"),
    ("assertions_removed", "assertions removed"),
    ("assertions_cleanup", "assertions removed together with the code they covered (cleanup)"),
    ("constant_asserts", "constant asserts added"),
    ("new_skips", "new skips"),
)


def format_report(rep, label=""):
    lines = [f"Weakened-test check (advisory, never fails){label}"]
    total = 0
    for attr, title in SECTIONS:
        items = getattr(rep, attr)
        total += 0 if attr.endswith("cleanup") else len(items)
        lines.append(f"  [{title}] {len(items)}")
        for i in items:
            extra = {
                "assertions_cleanup": f"  {i.before} -> {i.after} assertions",
                "removed": " (commented out)" if i.commented_out else "",
                "assertions_removed": f"  {i.before} -> {i.after} assertions",
            }.get(attr, f"  {i.detail}" if i.detail else "")
            lines.append(f"    {i.path}:{i.line}  {i.test}{extra}")
    lines += [f"  note: {n}" for n in rep.notes]
    lines.append(
        "  Possible weakening: justify each in the PR (CLAUDE.md, 'Making a red test GREEN by editing the TEST')."
        if total
        else "  No findings."
    )
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]))
    args = ap.parse_args(argv)
    try:
        merge_base, bt, ht, bp, hp = collect(args.repo, args.base, args.head)
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"Weakened-test check skipped: cannot diff {args.base}...{args.head} ({str(e)[:120]})")
        return 0
    rep = compare(bt, ht, bp, hp)
    print(format_report(rep, f" vs {merge_base[:9]}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
