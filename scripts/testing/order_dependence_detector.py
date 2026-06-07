"""Order-dependence detector for the parallel test suite.

WHY THIS EXISTS
---------------
`run-parallel-tests` runs each shard as ONE process against ONE site, executing
its test files sequentially with NO database reset between files. State therefore
bleeds file -> file *within* a shard. Because the LPT/count split decides which
files land in which shard (and `chunk.sort()` orders them alphabetically inside
it), a test's pass/fail can depend on which files alphabetically precede it in its
shard. Reshuffling the split (3 vs 4 shards, count vs measured weights) changes a
file's neighbours and trades one set of flakes for another -- the "churn" we saw
between baselines v22/v28/v29.

This tool makes that dependence *reproducible*. It runs a caller-supplied,
explicitly ordered list of test files in a single process, faithfully reusing the
real `ParallelTestRunner` machinery (same `before_test_setup` global seeding, same
shared-process semantics, same per-file preload + loader). The only thing it
overrides is *which* files run and *in what order*. That lets us answer, per test:

    * Does it fail when run SOLO on a clean site?   -> genuine bug / under-seeding
    * Does it pass solo but fail behind a prefix?   -> order-dependent (find polluter)

Usage (from the frappe-bench root):

    env/bin/python apps/verenigingen/scripts/testing/order_dependence_detector.py \
        --site test_site_1 \
        --modules verenigingen.tests.a,verenigingen.tests.b \
        --json-out /tmp/result.json

`--modules` is an ordered, comma-separated list of dotted test-module paths
(e.g. ``verenigingen.tests.backend.components.test_team_assignment_history``).
The last module is the "victim"; everything before it is the prefix under test.
Exit code is 0 regardless of test outcome -- read the JSON for results.
"""

import argparse
import json
import os
import sys

import frappe
from frappe.parallel_test_runner import ParallelTestRunner


class ExplicitListRunner(ParallelTestRunner):
    """ParallelTestRunner that runs a caller-supplied ordered module list.

    Everything inherited -- ``setup_test_site`` (toggles test mode, clears cache,
    disables scheduler, runs ``before_test_setup`` which fires the app's
    ``before_tests`` hooks + global_test_dependencies) and ``run_tests_for_file``
    (preloads test records, loads the module, runs it into a single shared
    ``TestResult``) -- is identical to a production shard. Only the file list is
    ours.
    """

    def __init__(self, app, site, modules, lightmode=False):
        # Must be set before super().__init__, which calls setup_test_file_list().
        self._explicit_modules = list(modules)
        super().__init__(
            app,
            site=site,
            build_number=1,
            total_builds=1,
            dry_run=False,
            lightmode=lightmode,
        )

    def get_test_file_list(self):
        """Return [path, filename] pairs for the explicit module list, in order."""
        app_path = frappe.get_app_path(self.app)
        file_list = []
        for dotted in self._explicit_modules:
            parts = dotted.split(".")
            if parts[0] != self.app:
                raise ValueError(
                    f"module {dotted!r} is not under app {self.app!r}; "
                    "pass fully-qualified dotted paths"
                )
            rel_dirs = parts[1:-1]
            filename = parts[-1] + ".py"
            path = os.path.join(app_path, *rel_dirs)
            full = os.path.join(path, filename)
            if not os.path.isfile(full):
                raise FileNotFoundError(f"no such test file: {full} (from {dotted})")
            file_list.append([path, filename])
        return file_list


def _testcase_id(testcase):
    """Stable 'module.Class.method' id for a unittest TestCase instance."""
    cls = testcase.__class__
    method = getattr(testcase, "_testMethodName", "<unknown>")
    return f"{cls.__module__}.{cls.__qualname__}.{method}"


def run_scenario(app, site, modules, lightmode=False):
    """Run the ordered module list in one process; return a results dict."""
    # The base runner re-inits frappe in setup_test_site() with the default
    # sites_path=".", so this process MUST run with cwd = the bench's sites/ dir
    # (exactly like the bench CLI does). init here too so the constructor's
    # get_app_path / file-weight reads work before setup_test_site() runs.
    frappe.init(site)
    if not frappe.db:
        frappe.connect()

    runner = ExplicitListRunner(app, site, modules, lightmode=lightmode)
    # setup_and_run() would also call print_result(), which arms signal.alarm(60)
    # + faulthandler and may sys.exit(1) under CI. We want neither -- run the two
    # phases ourselves and read the TestResult directly.
    runner.setup_test_site()
    runner.run_tests()

    res = runner.test_result
    # Dump failure/error tracebacks to stderr so the run log explains WHY a test
    # failed (the base runner's print_result, which we skip, would do this).
    for tc, tb in list(res.failures) + list(res.errors):
        print(f"\n===== TRACEBACK {_testcase_id(tc)} =====\n{tb}", file=sys.stderr)
    failures = sorted(_testcase_id(tc) for tc, _ in res.failures)
    errors = sorted(_testcase_id(tc) for tc, _ in res.errors)
    skipped = sorted(_testcase_id(tc) for tc, _ in res.skipped)
    return {
        "site": site,
        "modules": list(modules),
        "victim": modules[-1] if modules else None,
        "tests_run": res.testsRun,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "n_failures": len(failures),
        "n_errors": len(errors),
        "ok": not (failures or errors),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--site", required=True)
    ap.add_argument("--app", default="verenigingen")
    ap.add_argument("--modules", required=True, help="ordered, comma-separated dotted module paths")
    ap.add_argument("--json-out", required=True)
    ap.add_argument("--lightmode", action="store_true", help="skip before_test_setup (debug only)")
    args = ap.parse_args()

    modules = [m.strip() for m in args.modules.split(",") if m.strip()]
    if not modules:
        sys.exit("no modules given")

    result = run_scenario(args.app, args.site, modules, lightmode=args.lightmode)

    with open(args.json_out, "w") as f:
        json.dump(result, f, indent=2)

    v = result["victim"]
    vic_fail = [t for t in (result["failures"] + result["errors"]) if v and v in t]
    print(
        f"[detector] site={args.site} ran={result['tests_run']} "
        f"fail={result['n_failures']} err={result['n_errors']} "
        f"victim={v.split('.')[-1] if v else None} victim_failed={bool(vic_fail)}"
    )


if __name__ == "__main__":
    main()
