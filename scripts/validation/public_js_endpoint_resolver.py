#!/usr/bin/env python3
"""Flag a `frappe.call`/`frappe.xcall` in public/js that names no real Python function.

THE BUG CLASS
-------------
A `public/js` file calls `verenigingen.some.module.path.func_name` and nothing at
that path exists -- the module was renamed, moved into a different package, or
the JS was written against a server contract that was never built. The call
still parses and ships; it only 404s the moment a user reaches it, and nothing
in CI exercises a raw `frappe.call` string. #679 found exactly this: six calls
in `dd_batch_management_enhanced.js` targeted `verenigingen.api.dd_batch_api.*`,
a module that has never existed at that path (the real one is
`verenigingen.verenigingen_payments.api.dd_batch_api`) -- and the file itself
turned out to be unreachable from any page, hook, or bundle, so the whole thing
shipped, broken, unused, for however long it sat there.

The same sweep that found #679 also found two genuinely dead spots elsewhere in
`public/js`: `verenigingen.e_boekhouden.api.*` (14 calls, `eboekhouden_migration_config.js`
-- the real module is `verenigingen.e_boekhouden.doctype.e_boekhouden_account_mapping.api`)
and `verenigingen.api.volunteer.expenses.*` (2 calls, `expense_claim_form.vue` --
the real module is `verenigingen.templates.pages.volunteer.expenses`). Neither was
fixed by the PR that introduced this script; they were baselined and tracked as
#772 so that PR's own commit would not fail against a guard it had just added.

#772 (filed as the tracked follow-up) confirmed both files are unreachable --
same finding as #679's file: no `app_include_js`/`web_include_js`, no Page,
Workspace, or www template loads either one, and `expense_claim_form.vue` has
no SFC compiler configured for this app at all (it was the only `.vue` file in
`public/js`) and was superseded by a live inline-Vue3 page
(`templates/pages/volunteer/expense_claim_new.html`) that already calls the
correct paths. #772 also found that repointing `eboekhouden_migration_config.js`
without fixing it would have reproduced #679's own lesson: `stage_eboekhouden_data`
returns both a `success` and a `data` key, so `unwrapOperationResult` strips to
the inner `data` payload and `showStagingResults()` then reads
`transaction_count`/`account_count` off the stripped object -- always zero. Both
files were deleted rather than repointed, matching #679's resolution, and the
baseline below is now empty.

A THIRD candidate the first version of this script flagged --
`get_current_dues_schedule_details` / `refresh_fee_change_history` in
`member/js_modules/payment-utils.js` -- turned out to be a FALSE POSITIVE, caught
by review: `member.py` re-exports them via
`from verenigingen.verenigingen.doctype.member.member_compat import *`, and
`member_compat.py` both imports each name directly and lists it in `__all__`
(a deliberate tech-debt compatibility shim, see member.py's own
"BACKWARD COMPATIBILITY RE-EXPORTS" comment). The first version's resolver only
looked for a literal `def func(` or the bare name on an `import` line in the
directly-addressed file, so it could not see a name arriving through a wildcard
re-export -- exactly the shape this app's compat shims use
(`member_compat.py`, `utils/payment_retry.py`, `utils/account_creation_manager.py`
all do this). `resolve()` below is AST-based and follows `import *` chains
(respecting `__all__` where the source module declares one) specifically so this
does not recur.

SCOPE
-----
Only `verenigingen/public/js/**/*.js` and `**/*.vue` -- the JS-side half of this
bug class. `verenigingen/templates/`, `verenigingen/www/`, and `verenigingen/api/`
are a separate guard's territory (#430, same defect class in the server-rendered
side): keep the two disjoint rather than merging them, so neither PR's baseline
fights the other's.

KNOWN GAP: doctype- and page-level JS (`verenigingen/verenigingen/doctype/*/*.js`,
`*/page/*/*.js`) is covered by NEITHER guard, and is the more dangerous half --
it is Desk-loaded on every form view, not conditionally reachable like a
standalone page. A manual pass while building this script found 4 more dead
targets there (`e_boekhouden_migration.js`). Left out of SCAN_ROOTS deliberately:
extending scope should be its own change with its own baseline, not smuggled in
here.

WHAT IS CHECKED
---------------
Every string literal following `method:` or inside `frappe.xcall(` that looks
like a dotted call path into THIS app (`verenigingen.*`). A bare word (no dot)
is a whitelisted *instance* method reached via `doc: frm.doc` and is out of
scope -- resolving those needs the DocType, not the file tree. Framework and
other-app targets (`frappe.client.*`, `erpnext.*`, ...) are skipped; this
resolver only knows this app's tree.

Resolution parses each candidate module with `ast` (no bench/frappe import
needed) and asks whether `func` ends up bound in that module's namespace:
directly (`def func`, `class func`, `func = ...`, `import ... as func`,
`from X import func`), or transitively through `from X import *` -- recursing
into X and, if X declares `__all__`, requiring `func` to be listed there (the
same rule Python itself uses for what a wildcard import re-exports). This
catches a compat-shim re-export like the payment-utils.js case above without
needing a full import-system implementation. It does NOT check
`@frappe.whitelist()` -- a resolvable-but-unwhitelisted target 403s identically
to a nonexistent one, which is a real but separate risk; walking every def site
behind this script's current 41 resolved targets found a whitelist decorator on
all 41, so this is a latent gap, not a live one, as of this writing.

Ratcheted against `public_js_endpoint_baseline.txt` so the known-dead calls do
not block anything -- the baseline should only ever shrink; `--update-baseline`
refuses to grow it (use `--update-baseline --force` for a deliberate rescan that
adds new entries, e.g. after moving SCAN_ROOTS). ADVISORY: it prints and exits
0; pass --strict to fail on a target not in the baseline (a NEW dead call).

Usage:
    python scripts/validation/public_js_endpoint_resolver.py
    python scripts/validation/public_js_endpoint_resolver.py --update-baseline
    python scripts/validation/public_js_endpoint_resolver.py --strict
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("verenigingen/public/js",)
DEFAULT_BASELINE = Path(__file__).with_name("public_js_endpoint_baseline.txt")

# `method: 'verenigingen.foo.bar'` / `method: "verenigingen.foo.bar"`
# `frappe.xcall('verenigingen.foo.bar', ...)`
CALL_RE = re.compile(
    r"""(?:method\s*:\s*|frappe\.xcall\(\s*)['"]([A-Za-z_][A-Za-z0-9_.]*)['"]"""
)


def _iter_js_files(root: Path):
    for ext in ("*.js", "*.vue"):
        yield from root.rglob(ext)


def find_targets(paths):
    """Yield (relpath, lineno, dotted_target) for every in-app call target."""
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = REPO_ROOT / raw
        if not p.exists():
            continue
        roots = [p] if p.is_file() else list(_iter_js_files(p))
        for f in roots:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = f.relative_to(REPO_ROOT).as_posix()
            for i, line in enumerate(text.splitlines(), 1):
                for m in CALL_RE.finditer(line):
                    target = m.group(1)
                    if target.startswith("verenigingen.") and target.count(".") >= 2:
                        yield rel, i, target


def _module_file(module_dotted: str) -> Path | None:
    """Map a dotted module path (relative to REPO_ROOT) onto a real .py file."""
    rel = module_dotted.replace(".", "/")
    for candidate in (f"{rel}.py", f"{rel}/__init__.py"):
        f = REPO_ROOT / candidate
        if f.is_file():
            return f
    return None


def _relative_import_target(file_path: Path, node: ast.ImportFrom) -> str | None:
    """Resolve a possibly-relative `from ... import ...` to a dotted module path."""
    if node.level == 0:
        return node.module
    # A regular (non-__init__) module's own package is its containing directory.
    package_dir = file_path.parent
    for _ in range(node.level - 1):
        package_dir = package_dir.parent
    try:
        rel = package_dir.relative_to(REPO_ROOT)
    except ValueError:
        return None
    dotted = rel.as_posix().replace("/", ".")
    if node.module:
        dotted = f"{dotted}.{node.module}"
    return dotted


def _parse(file_path: Path) -> ast.Module | None:
    try:
        return ast.parse(file_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return None


def _bound_names(tree: ast.Module) -> set[str]:
    """Names directly bound at module level (defs, assigns, non-star imports)."""
    names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _star_import_targets(file_path: Path, tree: ast.Module) -> list[str]:
    targets = []
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                if alias.name == "*":
                    dotted = _relative_import_target(file_path, stmt)
                    if dotted:
                        targets.append(dotted)
    return targets


def _dunder_all(tree: ast.Module) -> list[str] | None:
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in stmt.targets
        ):
            if isinstance(stmt.value, (ast.List, ast.Tuple)):
                return [
                    elt.value
                    for elt in stmt.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                ]
    return None


def _wildcard_exports(file_path: Path, visited: set[Path]) -> set[str] | None:
    """Names `from file_path import *` would bring in, or None if unresolvable."""
    tree = _parse(file_path)
    if tree is None:
        return None
    all_list = _dunder_all(tree)
    if all_list is not None:
        return set(all_list)
    # No __all__: a wildcard import takes every public (non-underscore) name
    # bound in the module, INCLUDING names arriving through the module's own
    # wildcard imports.
    exported = {n for n in _bound_names(tree) if not n.startswith("_")}
    for target in _star_import_targets(file_path, tree):
        sub_file = _module_file(target)
        if sub_file is None or sub_file in visited:
            continue
        visited.add(sub_file)
        sub_exports = _wildcard_exports(sub_file, visited)
        if sub_exports:
            exported |= {n for n in sub_exports if not n.startswith("_")}
    return exported


def _resolves_in_file(file_path: Path, func: str, visited: set[Path]) -> bool:
    if file_path in visited:
        return False
    visited.add(file_path)
    tree = _parse(file_path)
    if tree is None:
        return False
    if func in _bound_names(tree):
        return True
    for target in _star_import_targets(file_path, tree):
        sub_file = _module_file(target)
        if sub_file is None:
            continue
        exports = _wildcard_exports(sub_file, visited)
        if exports is not None and func in exports:
            return True
    return False


def resolve(target: str) -> bool:
    """Does `target` (module.path.func) end up bound in that module's namespace?"""
    segments = target.split(".")
    module_dotted, func = ".".join(segments[:-1]), segments[-1]
    module_file = _module_file(module_dotted)
    if module_file is None:
        return False
    return _resolves_in_file(module_file, func, set())


def load_baseline(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        keys.add(line)
    return keys


def write_baseline(path: Path, dead: list[tuple[str, int, str]]) -> None:
    header = [
        "# Known dead public/js endpoint targets -- the ratchet baseline for",
        "# scripts/validation/public_js_endpoint_resolver.py. Format:",
        "#     <js file>::<dotted target>",
        "#",
        "# A finding is a (file, target) pair whose dotted Python path resolves to",
        "# nothing in the tree -- see the module docstring for how each entry here",
        "# was found and why it is not yet fixed. This baseline should only shrink;",
        "# a fix removes its line here rather than needing an update.",
        "#",
    ]
    body = sorted({f"{rel}::{target}" for rel, _lineno, target in dead})
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", default=list(SCAN_ROOTS))
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument(
        "--force",
        action="store_true",
        help="with --update-baseline, allow the baseline to grow (default: refuse)",
    )
    ap.add_argument("--stats", action="store_true", help="print totals and exit 0")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on a target not in the baseline (default: advisory, exit 0)",
    )
    args = ap.parse_args(argv[1:])

    strict = args.strict or os.environ.get("PUBLIC_JS_ENDPOINT_STRICT") == "1"
    paths = args.paths or list(SCAN_ROOTS)

    checked = 0
    dead: list[tuple[str, int, str]] = []
    for rel, lineno, target in find_targets(paths):
        checked += 1
        if not resolve(target):
            dead.append((rel, lineno, target))

    if args.update_baseline:
        new_keys = {f"{r}::{t}" for r, _, t in dead}
        old_keys = load_baseline(args.baseline)
        grew = new_keys - old_keys
        if grew and not args.force:
            print(f"refusing to grow the baseline with {len(grew)} new target(s):")
            for key in sorted(grew):
                print(f"  {key}")
            print("pass --force if this growth is deliberate (e.g. SCAN_ROOTS changed)")
            return 1
        write_baseline(args.baseline, dead)
        print(f"baseline written: {len(new_keys)} targets")
        return 0

    if args.stats:
        print(f"{checked} in-app call targets checked, {len(dead)} unresolved")
        return 0

    baseline = load_baseline(args.baseline)
    new = [(rel, lineno, target) for rel, lineno, target in dead if f"{rel}::{target}" not in baseline]

    if not new:
        return 0

    mode = "STRICT" if strict else "advisory"
    print(f"\n\U0001f50c public/js call target resolves to nothing  [{mode}]\n")
    for rel, lineno, target in sorted(new):
        print(f"  {rel}:{lineno}  {target}")
    print(
        "\n  This dotted path does not resolve to any def, class, assignment, import,\n"
        "  or __all__-declared wildcard re-export in the tree, so a browser hitting\n"
        "  this call gets a 404-shaped failure, not the server logic the JS assumes.\n"
        "  See #679 for the class this guards against: a renamed/moved module, or JS\n"
        "  written against a server contract that was never built. Fix by repointing\n"
        "  the call at the real module, or by confirming the caller is unreachable\n"
        "  and deleting the dead file.\n"
    )
    return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
