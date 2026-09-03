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

This is a live-defect class, not a one-off: the same sweep that found #679 also
found `verenigingen.e_boekhouden.api.*` (12 calls, `eboekhouden_migration_config.js`
-- the real module is `verenigingen.e_boekhouden.doctype.e_boekhouden_account_mapping.api`),
`verenigingen.api.volunteer.expenses.*` (2 calls, `expense_claim_form.vue`), and,
worse, two calls inside `member/js_modules/payment-utils.js` --
`get_current_dues_schedule_details` / `refresh_fee_change_history` -- wired to a
LIVE "Refresh Membership & Dues Info" button on the Member form
(`verenigingen/verenigingen/doctype/member/member.js`). None of those four are
fixed by this change; they are baselined below and tracked for follow-up so this
guard does not fail the commit that merely adds it.

SCOPE
-----
Only `verenigingen/public/js/**/*.js` and `**/*.vue` -- the JS-side half of this
bug class. `verenigingen/templates/`, `verenigingen/www/`, and `verenigingen/api/`
are a separate guard's territory (#430, same defect class in the server-rendered
side): keep the two disjoint rather than merging them, so neither PR's baseline
fights the other's.

WHAT IS CHECKED
---------------
Every string literal following `method:` or inside `frappe.xcall(` that looks
like a dotted call path into THIS app (`verenigingen.*`). A bare word (no dot)
is a whitelisted *instance* method reached via `doc: frm.doc` and is out of
scope -- resolving those needs the DocType, not the file tree. Framework and
other-app targets (`frappe.client.*`, `erpnext.*`, ...) are skipped; this
resolver only knows this app's tree.

Resolution is intentionally simple, matching how #679 was found by hand: split
the dotted path into a module and a function name, map the module onto
`<segments>.py` or `<segments>/__init__.py`, and look for either a `def func(`
in that file or the bare name `func` on an `import`/`from ... import` line (a
package `__init__.py` that re-exports a submodule's endpoint). No AST, no
import resolution across files beyond that one hop -- enough to catch a path
that is wrong at the FIRST segment after the app name, which is what every
instance found here looked like, without chasing every re-export chain in the
app and risking false positives on this app's genuinely deep import graphs.

Ratcheted against `public_js_endpoint_baseline.txt` so the four already-known
dead calls do not block anything -- the baseline should only ever shrink.
ADVISORY while those four are triaged: it prints and exits 0; pass --strict to
fail on a target not in the baseline (a NEW dead call).

Usage:
    python scripts/validation/public_js_endpoint_resolver.py
    python scripts/validation/public_js_endpoint_resolver.py --update-baseline
    python scripts/validation/public_js_endpoint_resolver.py --strict
"""

from __future__ import annotations

import argparse
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


def resolve(target: str) -> bool:
    """Best-effort: does `target` (module.path.func) name something real?"""
    segments = target.split(".")
    module_segments, func = segments[:-1], segments[-1]
    module_rel = "/".join(module_segments)
    for candidate in (f"{module_rel}.py", f"{module_rel}/__init__.py"):
        f = REPO_ROOT / candidate
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(rf"\bdef\s+{re.escape(func)}\s*\(", text):
            return True
        # a package __init__ (or module) re-exporting a submodule's function
        for line in text.splitlines():
            if line.strip().startswith(("import ", "from ")) and re.search(
                rf"\b{re.escape(func)}\b", line
            ):
                return True
    return False


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
        write_baseline(args.baseline, dead)
        print(f"baseline written: {len({f'{r}::{t}' for r, _, t in dead})} targets")
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
        "\n  This dotted path does not match any `def` (or re-exported name) in the\n"
        "  tree, so a browser hitting this call gets a 404-shaped failure, not the\n"
        "  server logic the JS assumes. See #679 for the class this guards against:\n"
        "  a renamed/moved module, or JS written against a server contract that was\n"
        "  never built. Fix by repointing the call at the real module, or by\n"
        "  confirming the caller is unreachable and deleting the dead file.\n"
    )
    return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
