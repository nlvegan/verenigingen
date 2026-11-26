#!/usr/bin/env python3
"""API security audit used by ci.yml's ``api-security-audit`` job (#1096).

The audit used to be inline Python in ci.yml that matched
``line.strip().startswith('@frappe.whitelist')``. That cannot tell a decorator
from the same text inside a string literal (a code-rewriting script under
scripts/ embeds ``@frappe.whitelist()`` in a replace pattern). This module finds
endpoints from the ``ast`` instead: a decorator on a FunctionDef/AsyncFunctionDef.

Modes:
  audit   exit 1 if a whitelisted function in a high-risk file has no security decorator
  report  write api-security-report.json (counts over the same scan roots)
"""
import ast
import json
import os
import re
import sys
from datetime import datetime

SCAN_ROOTS = ("verenigingen", "scripts")

SECURITY_DECORATORS = [
    "@critical_api", "@standard_api", "@high_security_api",
    "@self_service_api", "@api_security_framework",
    "@development_only_api", "@public_api", "@utility_api",
    "@development_only", "@_development_only", "@require_role",
    "@webhook_api",
]

HIGH_RISK_PATTERNS = [
    "payment", "sepa", "invoice", "financial", "settlement", "batch", "mandate", "sync", "audit",
]


def _is_frappe_whitelist_decorator_node(node):
    target = node.func if isinstance(node, ast.Call) else node
    return (
        isinstance(target, ast.Attribute)
        and target.attr == "whitelist"
        and isinstance(target.value, ast.Name)
        and target.value.id == "frappe"
    )


def _decorator_has_security(node):
    text = "@" + ast.unparse(node)
    return any(d in text for d in SECURITY_DECORATORS)


def find_api_endpoints(source):
    """Return [(func_name, lineno, has_security, is_method)] for every function
    carrying a ``frappe.whitelist`` decorator. Text inside strings/comments is
    never a decorator, so it is never returned."""
    endpoints = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_frappe_whitelist_decorator_node(d) for d in node.decorator_list):
            continue
        has_security = any(_decorator_has_security(d) for d in node.decorator_list)
        first_arg = node.args.args[0].arg if node.args.args else None
        endpoints.append((node.name, node.lineno, has_security, first_arg == "self"))
    return endpoints


def iter_audit_scan_files():
    for scan_root in SCAN_ROOTS:
        for root, _dirs, files in os.walk(scan_root):
            if "test" in root.lower() or "__pycache__" in root:
                continue
            for file in files:
                if file.endswith(".py") and not file.startswith("__"):
                    yield os.path.join(root, file)


def _read_endpoints(filepath):
    try:
        with open(filepath, "r") as f:
            return find_api_endpoints(f.read())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def find_unprotected_high_risk():
    found = []
    for filepath in iter_audit_scan_files():
        if not any(p in filepath.lower() for p in HIGH_RISK_PATTERNS):
            continue
        endpoints = _read_endpoints(filepath)
        if endpoints is None:
            # Fail closed: a file the audit cannot parse must not read as "no endpoints".
            found.append((filepath, "<unparseable>"))
            continue
        for name, _line, has_security, is_method in endpoints:
            if not has_security and not is_method:
                found.append((filepath, name))
    return found


def run_audit():
    # A checkout missing BOTH scan roots must hard-fail rather than report
    # "0 endpoints scanned, audit passed" (#1078).
    if not any(os.path.isdir(r) for r in SCAN_ROOTS):
        print("❌ Neither scan root (verenigingen/, scripts/) was found.")
        return 1
    unprotected = find_unprotected_high_risk()
    if unprotected:
        print("❌ SECURITY AUDIT FAILED: Unprotected high-risk API endpoints found!")
        print("=" * 70)
        for path, func in unprotected:
            print(f"  HIGH-RISK: {path}:{func}")
        print()
        print("These endpoints must have security decorators (@critical_api, @high_security_api, etc.)")
        return 1
    print("✅ API Security Audit Passed")
    print("All high-risk @frappe.whitelist() endpoints have security decorators.")
    return 0


def run_report():
    report = {
        "timestamp": datetime.now().isoformat(),
        "audit_type": "api_security",
        "endpoints_scanned": 0,
        "protected_endpoints": 0,
        "unprotected_endpoints": 0,
        "high_risk_unprotected": 0,
        "details": [],
    }
    for filepath in iter_audit_scan_files():
        endpoints = _read_endpoints(filepath)
        if not endpoints:
            continue
        with open(filepath, "r") as f:
            content = f.read()
        whitelist_count = len(endpoints)
        security_count = sum(len(re.findall(d.replace("(", r"\("), content)) for d in SECURITY_DECORATORS)
        report["endpoints_scanned"] += whitelist_count
        report["protected_endpoints"] += min(whitelist_count, security_count)
        report["unprotected_endpoints"] += max(0, whitelist_count - security_count)
    report["protection_rate"] = (
        round(report["protected_endpoints"] / report["endpoints_scanned"] * 100, 1)
        if report["endpoints_scanned"] > 0
        else 100
    )
    with open("api-security-report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("📈 API Security Report")
    print(f"   Endpoints scanned: {report['endpoints_scanned']}")
    print(f"   Protected: {report['protected_endpoints']}")
    print(f"   Protection rate: {report['protection_rate']}%")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "audit"
    sys.exit({"audit": run_audit, "report": run_report}[mode]())
