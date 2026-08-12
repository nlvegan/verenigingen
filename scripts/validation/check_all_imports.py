#!/usr/bin/env python3
"""
Runtime Import Validator
========================

Validates that ALL Python modules in the verenigingen package can be imported
without errors. Unlike the static import_path_validator (which checks if files
exist on disk), this script actually imports every module, catching:

- Wrong enum values (e.g. OperationType.FINANCIAL_SYNC when only FINANCIAL exists)
- Missing function/class exports from target modules
- Circular import failures
- Runtime initialization errors

Requirements:
    - Must be run via bench python (needs Frappe on sys.path)
    - Needs a Frappe site (connects automatically)

Usage:
    # Via make (recommended):
    make check-imports

    # Or directly:
    cd ~/frappe-bench
    bench --site <your-site> python apps/verenigingen/scripts/validation/check_all_imports.py

Exit codes:
    0 - All modules imported successfully
    1 - Import errors found
"""

import importlib
import json
import os
import pkgutil
import sys
import time


def get_bench_dir():
    """Find the bench directory (parent of apps/)."""
    # Walk up from this script: scripts/validation/check_all_imports.py -> apps/verenigingen/
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # script_dir = .../apps/verenigingen/scripts/validation
    return os.path.abspath(os.path.join(script_dir, "..", "..", "..", ".."))


def get_site(bench_dir):
    """Determine the Frappe site to connect to.

    `bench use` records the default as `default_site` in common_site_config.json;
    it does not write sites/currentsite.txt, which this only consulted first and
    which does not exist on this bench. The alphabetical auto-discovery below was
    therefore always what ran, and it answers with whatever sorts first rather
    than with the configured default (#313).
    """
    sites_dir = os.path.join(bench_dir, "sites")

    try:
        with open(os.path.join(sites_dir, "common_site_config.json")) as f:
            default_site = json.load(f).get("default_site")
        if default_site:
            return default_site
    except (OSError, ValueError):
        pass

    # For benches old enough to write it.
    currentsite = os.path.join(sites_dir, "currentsite.txt")
    if os.path.exists(currentsite):
        with open(currentsite) as f:
            site = f.read().strip()
            if site:
                return site

    # Auto-discover: find directories containing site_config.json
    for entry in sorted(os.listdir(sites_dir)):
        if os.path.isfile(os.path.join(sites_dir, entry, "site_config.json")):
            return entry

    print("ERROR: No Frappe site found in", sites_dir)
    sys.exit(1)


def main():
    """Run the runtime import validator."""
    import frappe

    # Connect to site if not already connected
    if not getattr(frappe.local, "site", None):
        bench_dir = get_bench_dir()
        site = get_site(bench_dir)
        os.chdir(os.path.join(bench_dir, "sites"))
        frappe.connect(site=site)
        should_destroy = True
    else:
        should_destroy = False

    start = time.time()

    try:
        import verenigingen
    except ImportError:
        print("ERROR: Cannot import verenigingen.")
        sys.exit(1)

    errors = []
    count = 0
    skipped = 0

    for _importer, modname, _ispkg in pkgutil.walk_packages(
        verenigingen.__path__, "verenigingen."
    ):
        # Skip test modules and node_modules
        if ".tests." in modname or ".node_modules." in modname:
            skipped += 1
            continue

        count += 1
        try:
            importlib.import_module(modname)
        except Exception as e:
            errors.append((modname, type(e).__name__, str(e)[:200]))

    elapsed = time.time() - start

    if should_destroy:
        frappe.destroy()

    print(f"Scanned {count} modules ({skipped} test/node modules skipped) in {elapsed:.1f}s")

    if errors:
        print(f"\nFOUND {len(errors)} IMPORT ERROR(S):\n")
        for mod, etype, msg in sorted(errors):
            print(f"  {mod}")
            print(f"    {etype}: {msg}\n")
        sys.exit(1)
    else:
        print("All modules imported successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
