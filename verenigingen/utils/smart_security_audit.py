#!/usr/bin/env python3
"""
Smart Security Audit Script for @frappe.whitelist() Functions

This script intelligently identifies unsecured @frappe.whitelist() functions
and avoids redundant work by tracking which files have already been secured.

Key Features:
1. Caches results to avoid redundant searches
2. Prioritizes high-risk files (financial, admin, public templates)
3. Tracks security framework usage to identify secured vs unsecured
4. Provides intelligent filtering and prioritization
5. Generates actionable security recommendations

Usage:
    bench --site dev.veganisme.net execute verenigingen.utils.smart_security_audit.find_unsecured_functions
    bench --site dev.veganisme.net execute verenigingen.utils.smart_security_audit.get_priority_targets
    bench --site dev.veganisme.net execute verenigingen.utils.smart_security_audit.analyze_security_coverage

Author: Development Team
Date: 2025-09-14
Version: 2.0 - Smart Search
"""

import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Tuple

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


class SmartSecurityAuditor:
    """Intelligent security auditor that avoids redundant work"""

    def __init__(self):
        self.app_path = Path("/home/frappe/frappe-bench/apps/verenigingen")
        self.cache = {}
        self.priority_patterns = {
            "critical": [
                "nuke",
                "delete",
                "destroy",
                "drop",
                "truncate",
                "wipe",
                "mollie",
                "payment",
                "sepa",
                "bank",
                "financial",
                "invoice",
            ],
            "high": [
                "admin",
                "manage",
                "dashboard",
                "export",
                "import",
                "template",
                "public",
                "guest",
                "webhook",
            ],
            "medium": ["member", "user", "customer", "volunteer", "chapter"],
        }

    def find_files_with_whitelist(self) -> Dict[str, Dict]:
        """Find all files with @frappe.whitelist() functions"""
        if "whitelist_files" in self.cache:
            return self.cache["whitelist_files"]

        print("🔍 Scanning for files with @frappe.whitelist() functions...")

        # Use find + grep for efficient search
        cmd = [
            "find",
            str(self.app_path),
            "-name",
            "*.py",
            "-exec",
            "grep",
            "-l",
            "@frappe\\.whitelist()",
            "{}",
            ";",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            files = [f.strip() for f in result.stdout.split("\n") if f.strip()]

            file_data = {}
            for file_path in files:
                file_data[file_path] = self._analyze_file(file_path)

            self.cache["whitelist_files"] = file_data
            print(f"📊 Found {len(files)} files with @frappe.whitelist() functions")
            return file_data

        except subprocess.CalledProcessError as e:
            print(f"❌ Error scanning files: {e}")
            return {}

    def _analyze_file(self, file_path: str) -> Dict:
        """Analyze a single file for security status"""
        try:
            with open(file_path, "r") as f:
                content = f.read()

            # Count whitelist functions
            whitelist_count = len(re.findall(r"@frappe\.whitelist\(\)", content))

            # Enhanced security import detection (multiple patterns)
            has_security_import = (
                bool(re.search(r"from verenigingen\.utils\.security\.api_security_framework import", content))
                or bool(re.search(r"from verenigingen\.utils\.security import", content))
                or bool(re.search(r"import.*api_security_framework", content))
            )

            # Count security decorators (more comprehensive)
            security_decorators = len(
                re.findall(
                    r"@(critical_api|high_security_api|standard_api|public_api|development_only_api)", content
                )
            )

            # Also check for legacy security patterns that might be missed
            legacy_security = len(re.findall(r"@(validate_api_access|secure_api|authenticated_api)", content))
            total_secured = security_decorators + legacy_security

            # Determine priority level
            priority = self._get_file_priority(file_path)

            # Check for false positive patterns
            is_false_positive = self._is_false_positive(file_path, content)

            # Calculate security coverage
            coverage = (total_secured / whitelist_count * 100) if whitelist_count > 0 else 0

            return {
                "whitelist_functions": whitelist_count,
                "security_decorators": total_secured,
                "has_security_import": has_security_import,
                "security_coverage": coverage,
                "priority": priority,
                "is_secured": coverage >= 100,  # All functions have decorators
                "is_false_positive": is_false_positive,
                "relative_path": str(Path(file_path).relative_to(self.app_path)),
            }

        except Exception as e:
            print(f"⚠️ Error analyzing {file_path}: {e}")
            return {"error": str(e)}

    def _is_false_positive(self, file_path: str, content: str) -> bool:
        """Detect false positive patterns that shouldn't be high priority"""
        path_lower = file_path.lower()

        # Archived/obsolete code
        if any(pattern in path_lower for pattern in ["/archived/", "/obsolete/", "_obsolete", "_deprecated"]):
            return True

        # Generated or fixture files
        if any(pattern in path_lower for pattern in ["_fixture", "fixture_", "/fixtures/", "generated_"]):
            return True

        # Migration scripts that are one-time use
        if "migration" in path_lower and ("one_time" in path_lower or "temp_" in path_lower):
            return True

        # Debug files in production
        if "/debug/" in path_lower and "simple_" in path_lower:
            return True

        return False

    def _get_file_priority(self, file_path: str) -> str:
        """Determine priority level based on file path and name"""
        path_lower = file_path.lower()

        # False positives get downgraded to low priority
        if self._is_false_positive(file_path, ""):
            return "low"

        # Critical patterns (financial/payment operations)
        for pattern in self.priority_patterns["critical"]:
            if pattern in path_lower:
                return "critical"

        # High priority patterns
        for pattern in self.priority_patterns["high"]:
            if pattern in path_lower:
                return "high"

        # Template pages are always high priority (public-facing)
        if "/templates/pages/" in path_lower:
            return "high"

        # API directories are high priority
        if "/api/" in path_lower:
            return "high"

        # DocType files are medium-high priority
        if "/doctype/" in path_lower and path_lower.endswith(".py"):
            return "medium"

        # Medium priority patterns
        for pattern in self.priority_patterns["medium"]:
            if pattern in path_lower:
                return "medium"

        return "low"

    def get_unsecured_files(
        self, min_priority: str = "medium", exclude_false_positives: bool = True
    ) -> List[Dict]:
        """Get files that need security attention"""
        files = self.find_files_with_whitelist()

        priority_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        min_level = priority_order.get(min_priority, 2)

        unsecured = []
        for file_path, data in files.items():
            if data.get("error"):
                continue

            # Skip false positives if requested
            if exclude_false_positives and data.get("is_false_positive", False):
                continue

            file_priority = priority_order.get(data["priority"], 1)
            if file_priority >= min_level and not data["is_secured"]:
                data["file_path"] = file_path
                unsecured.append(data)

        # Sort by priority and number of unsecured functions
        unsecured.sort(
            key=lambda x: (
                -priority_order.get(x["priority"], 1),
                -(x["whitelist_functions"] - x["security_decorators"]),
            )
        )

        return unsecured

    def get_security_summary(self) -> Dict:
        """Get overall security coverage summary"""
        files = self.find_files_with_whitelist()

        total_files = len(files)
        secured_files = sum(1 for data in files.values() if data.get("is_secured", False))
        total_functions = sum(data.get("whitelist_functions", 0) for data in files.values())
        secured_functions = sum(data.get("security_decorators", 0) for data in files.values())

        priority_stats = defaultdict(lambda: {"files": 0, "secured": 0})
        for data in files.values():
            if not data.get("error"):
                priority = data["priority"]
                priority_stats[priority]["files"] += 1
                if data.get("is_secured", False):
                    priority_stats[priority]["secured"] += 1

        return {
            "total_files": total_files,
            "secured_files": secured_files,
            "file_coverage": (secured_files / total_files * 100) if total_files > 0 else 0,
            "total_functions": total_functions,
            "secured_functions": secured_functions,
            "function_coverage": (secured_functions / total_functions * 100) if total_functions > 0 else 0,
            "priority_breakdown": dict(priority_stats),
        }


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def find_unsecured_functions(min_priority: str = "medium", limit: int = 20):
    """Find unsecured @frappe.whitelist() functions with smart prioritization"""

    auditor = SmartSecurityAuditor()
    unsecured = auditor.get_unsecured_files(min_priority)

    print(f"\n🔍 Smart Security Audit Results")
    print(f"{'=' * 60}")

    if not unsecured:
        print("✅ No unsecured functions found at the specified priority level!")
        return {"message": "All functions secured at specified priority level"}

    results = []
    for i, file_data in enumerate(unsecured[:limit]):
        unsecured_count = file_data["whitelist_functions"] - file_data["security_decorators"]

        print(f"\n{i+1}. 🚨 {file_data['priority'].upper()} PRIORITY")
        print(f"   📁 {file_data['relative_path']}")
        print(f"   🔢 Functions: {file_data['whitelist_functions']} total, {unsecured_count} unsecured")
        print(f"   📊 Coverage: {file_data['security_coverage']:.1f}%")
        print(f"   🔒 Has Security Import: {'✅' if file_data['has_security_import'] else '❌'}")

        results.append(
            {
                "file_path": file_data["file_path"],
                "relative_path": file_data["relative_path"],
                "priority": file_data["priority"],
                "unsecured_functions": unsecured_count,
                "total_functions": file_data["whitelist_functions"],
                "coverage": file_data["security_coverage"],
                "has_security_import": file_data["has_security_import"],
            }
        )

    return {"unsecured_files": results, "total_found": len(unsecured)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def get_security_summary():
    """Get comprehensive security coverage summary"""

    auditor = SmartSecurityAuditor()
    summary = auditor.get_security_summary()

    print(f"\n📊 Security Coverage Summary")
    print(f"{'=' * 50}")
    print(
        f"📁 Files: {summary['secured_files']}/{summary['total_files']} secured ({summary['file_coverage']:.1f}%)"
    )
    print(
        f"⚡ Functions: {summary['secured_functions']}/{summary['total_functions']} secured ({summary['function_coverage']:.1f}%)"
    )

    print(f"\n🎯 Priority Breakdown:")
    for priority, stats in summary["priority_breakdown"].items():
        coverage = (stats["secured"] / stats["files"] * 100) if stats["files"] > 0 else 0
        print(f"   {priority.upper()}: {stats['secured']}/{stats['files']} files ({coverage:.1f}%)")

    return summary


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def get_next_batch(priority: str = "critical", batch_size: int = 5):
    """Get next batch of files to secure for efficient work"""

    auditor = SmartSecurityAuditor()
    unsecured = auditor.get_unsecured_files(priority)

    batch = unsecured[:batch_size]

    print(f"\n🎯 Next {len(batch)} files to secure ({priority.upper()} priority):")
    print(f"{'=' * 60}")

    for i, file_data in enumerate(batch):
        unsecured_count = file_data["whitelist_functions"] - file_data["security_decorators"]
        print(f"{i+1}. {file_data['relative_path']} ({unsecured_count} functions)")

    return {
        "batch": [
            {
                "file_path": f["file_path"],
                "relative_path": f["relative_path"],
                "unsecured_functions": f["whitelist_functions"] - f["security_decorators"],
            }
            for f in batch
        ]
    }
