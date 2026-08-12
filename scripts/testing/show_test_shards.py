#!/usr/bin/env python3
"""Replicate CI's parallel-test shard layout locally.

WHY THIS EXISTS
---------------
`run-parallel-tests` splits test FILES across shards, runs each shard as ONE process
against ONE site, and does NOT reset the database between files. So a test's result can
depend on which files precede it in its shard. The split itself is global LPT bin-packing
over measured weights (`scripts/frappe-parallel-test-weights.patch` +
`verenigingen/tests/test_timings.json`), which means **adding or reweighting a single test
file re-packs every shard** and silently moves unrelated files to new neighbours.

That is how #291 happened: a new test file in #289 reddened four unrelated shards. The
round-2 failure was diagnosed in five minutes only once someone replicated the split by
hand and saw the file had moved to position 1 of its shard, losing the earlier test that
had been leaving master data behind. There was no tool for that. This is that tool.

It deliberately imports frappe's OWN `get_all_tests` / `get_test_weight` /
`split_by_weight` rather than reimplementing the algorithm, so it cannot drift from what
CI actually does. The flip side is that it reports whatever the local frappe does: if the
weights patch is not applied, the layout shown is the STOCK count-based one, not CI's, and
the script says so loudly instead of quietly lying.

USAGE (needs the bench venv python, and any site that has the app installed)

    cd ~/frappe-bench
    ./env/bin/python apps/verenigingen/scripts/testing/show_test_shards.py            # summary
    ./env/bin/python .../show_test_shards.py --shard 3                                # list a shard
    ./env/bin/python .../show_test_shards.py --find test_sales_invoice_hooks          # locate a file
    ./env/bin/python .../show_test_shards.py --first                                  # per-shard first file
    ./env/bin/python .../show_test_shards.py --modules-for 3                           # feed the detector

The last mode emits the ordered, comma-separated dotted module list that
`order_dependence_detector.py --modules` expects, so the two compose:

    ./env/bin/python .../show_test_shards.py --modules-for 3 > /tmp/shard3.txt
    ./env/bin/python .../order_dependence_detector.py --site test_site_1 \
        --modules "$(cat /tmp/shard3.txt)" --json-out /tmp/shard3.json

Reproducing a HISTORICAL split (what a past CI run actually ran) takes more than checking
the commit out: the layout is a function of the test files on disk AND that commit's
test_timings.json, and `get_all_tests()` walks whichever copy of the app Python IMPORTED --
the installed `apps/verenigingen`, not your worktree. Shadow it explicitly:

    PYTHONPATH=<worktree> ./env/bin/python <worktree>/scripts/testing/show_test_shards.py

Without that, running the script from a worktree still reports the INSTALLED tree's layout.
"""

import argparse
import json
import os
import sys


def _bench_root(override: str | None = None, starts: tuple[str, ...] | None = None) -> str | None:
    """Locate the bench: the nearest ancestor holding both `apps/` and `sites/`.

    Deliberately a search rather than a fixed number of `..` hops. This file is run both
    from the installed checkout (<bench>/apps/verenigingen/scripts/testing/) and from git
    worktrees under a temp dir, where that layout does not hold -- and hardcoding the hops
    silently found the wrong directory instead of failing.

    PRECEDENCE: this file's own location first, then the cwd. A script in a bench should
    describe *that* bench regardless of where it was invoked from; cwd is the fallback for
    the worktree case, where the file sits outside any bench.

    `starts` exists so the precedence can be tested without depending on where this file
    happens to live -- the first version of that test asserted cwd won, which was only
    true when run from a worktree and broke the moment the script was installed.
    """
    if override:
        return os.path.abspath(override)
    if starts is None:
        starts = (os.path.dirname(os.path.abspath(__file__)), os.getcwd())
    for start in starts:
        path = os.path.abspath(start)
        while True:
            if os.path.isdir(os.path.join(path, "apps")) and os.path.isdir(os.path.join(path, "sites")):
                return path
            parent = os.path.dirname(path)
            if parent == path:
                break
            path = parent
    return None


def _default_site(bench_root: str) -> str | None:
    """Read `default_site` from sites/common_site_config.json.

    That file is the real source of the bench default. `sites/currentsite.txt` does not
    exist on this bench -- anything reading it silently falls through to its own
    hardcoded default, which is how a test runner once pointed at the live site.
    """
    try:
        with open(os.path.join(bench_root, "sites", "common_site_config.json")) as f:
            return json.load(f).get("default_site")
    except (OSError, ValueError):
        return None


def _dotted(test: list[str]) -> str:
    """Dotted module path for a [dir, filename] test entry.

    Mirrors the conversion in the patched `get_test_weight` so the names printed here are
    the same keys used by test_timings.json and accepted by `--modules`.
    """
    file_name = "/".join(test)
    after = file_name.split("/apps/", 1)[1]
    return ".".join(after.split("/")[1:])[: -len(".py")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--app", default="verenigingen")
    ap.add_argument("--site", help="defaults to default_site in common_site_config.json")
    ap.add_argument("--total", type=int, default=12, help="shard count (CI uses 12)")
    ap.add_argument("--shard", type=int, help="list this shard's files, in execution order")
    ap.add_argument("--find", help="substring of a path/module; report shard and position")
    ap.add_argument("--first", action="store_true", help="show the first file of every shard")
    ap.add_argument("--modules-for", type=int, help="emit a shard's dotted modules, comma-separated")
    ap.add_argument("--bench-root", help="override bench autodetection")
    args = ap.parse_args()

    bench_root = _bench_root(args.bench_root)
    if not bench_root:
        print("Could not locate a bench (a dir with apps/ and sites/); pass --bench-root", file=sys.stderr)
        return 2
    sys.path.insert(0, os.path.join(bench_root, "apps", "frappe"))

    import frappe

    site = args.site or _default_site(bench_root)
    if not site:
        print("No site given and no default_site in common_site_config.json", file=sys.stderr)
        return 2
    frappe.init(site=site, sites_path=os.path.join(bench_root, "sites"))

    from frappe import parallel_test_runner as ptr

    # The layout is only CI's if the weighting patch is in place. Say so rather than
    # presenting the stock count-based split as though it were what CI runs.
    patched = hasattr(ptr, "_get_measured_weights")
    timings = os.path.join(bench_root, "apps", args.app, args.app, "tests", "test_timings.json")

    tests = ptr.get_all_tests(args.app)
    weights = [ptr.ParallelTestRunner.get_test_weight(t) for t in tests]
    chunks = ptr.split_by_weight(tests, weights, chunk_count=args.total)
    weight_of = {"/".join(t): w for t, w in zip(tests, weights, strict=True)}

    # --modules-for is machine-readable: no banner, nothing but the list on stdout.
    if args.modules_for:
        chunk = chunks[args.modules_for - 1]
        print(",".join(_dotted(t) for t in chunk))
        return 0

    if not patched:
        print(
            "WARNING: frappe is NOT patched with frappe-parallel-test-weights.patch, so this\n"
            "         is the STOCK count-based split, not the one CI runs. Apply it with:\n"
            "           git -C apps/frappe apply "
            "apps/verenigingen/scripts/frappe-parallel-test-weights.patch\n",
            file=sys.stderr,
        )
    if not os.path.exists(timings):
        print(
            f"WARNING: no measured timings at {timings}; weights fall back to test counts.\n", file=sys.stderr
        )

    if args.find:
        hits = 0
        for shard_no, chunk in enumerate(chunks, 1):
            for pos, test in enumerate(chunk, 1):
                if args.find in "/".join(test) or args.find in _dotted(test):
                    hits += 1
                    print(
                        f"shard {shard_no:>2}  position {pos:>4}/{len(chunk)}  "
                        f"weight {weight_of['/'.join(test)]:>8.1f}  {_dotted(test)}"
                    )
        if not hits:
            print(f"no test file matching {args.find!r}")
        elif hits > 1:
            # 44 test basenames are duplicated in this app, and the weight fallback keys on
            # the basename, so an ambiguous match is normal rather than a bug. Show all.
            print(f"\n{hits} matches -- narrow the pattern with more of the path to pick one.")
        return 0

    if args.first:
        print(f"First file of each shard ({args.total} shards) -- these run with no earlier")
        print("test in the shard to have left master data behind:\n")
        for shard_no, chunk in enumerate(chunks, 1):
            print(f"  shard {shard_no:>2}: {_dotted(chunk[0])}")
        return 0

    if args.shard:
        chunk = chunks[args.shard - 1]
        total = sum(weight_of["/".join(t)] for t in chunk)
        print(f"shard {args.shard}/{args.total}: {len(chunk)} files, weight {total:.1f}\n")
        for pos, test in enumerate(chunk, 1):
            print(f"  {pos:>4}. {weight_of['/'.join(test)]:>8.1f}  {_dotted(test)}")
        return 0

    print(f"app={args.app} site={site} shards={args.total} patched={patched}")
    print(f"{len(tests)} test files, total weight {sum(weights):.1f}\n")
    for shard_no, chunk in enumerate(chunks, 1):
        total = sum(weight_of["/".join(t)] for t in chunk)
        print(f"  shard {shard_no:>2}: {len(chunk):>5} files  weight {total:>9.1f}")
    spread = max(sum(weight_of["/".join(t)] for t in c) for c in chunks) - min(
        sum(weight_of["/".join(t)] for t in c) for c in chunks
    )
    print(f"\nheaviest-lightest spread: {spread:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
