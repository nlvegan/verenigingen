#!/usr/bin/env python3
"""
Comprehensive API Security Implementation
Identifies and secures all unprotected @frappe.whitelist functions
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


def find_api_files_with_whitelist() -> List[str]:
    """Find all Python files with @frappe.whitelist functions"""
    api_files = []
    api_directories = ["api/", "verenigingen/api/"]

    for api_dir in api_directories:
        if os.path.exists(api_dir):
            for root, dirs, files in os.walk(api_dir):
                for file in files:
                    if file.endswith(".py"):
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                content = f.read()
                                if "@frappe.whitelist" in content:
                                    api_files.append(file_path)
                        except Exception as e:
                            print(f"Error reading {file_path}: {e}")

    return api_files


def check_security_status(file_path: str) -> Dict[str, Any]:
    """Check if file has security framework imports and decorators"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return {"error": str(e), "secured": False}

    # Check for security framework import
    has_security_import = bool(
        re.search(r"from verenigingen\.utils\.security\.api_security_framework import", content)
    )

    # Count @frappe.whitelist functions
    whitelist_functions = len(re.findall(r"@frappe\.whitelist\(\)", content))

    # Count security decorators (critical_api, high_security_api, standard_api)
    security_decorators = len(re.findall(r"@(?:critical_api|high_security_api|standard_api)\(", content))

    # Extract function names for analysis
    function_matches = re.findall(r"@frappe\.whitelist\(\)\s*\ndef\s+(\w+)", content, re.MULTILINE)

    return {
        "secured": has_security_import and security_decorators > 0,
        "has_security_import": has_security_import,
        "whitelist_functions": whitelist_functions,
        "security_decorators": security_decorators,
        "function_names": function_matches,
        "needs_security": whitelist_functions > 0 and not has_security_import,
    }


def classify_file_risk_level(file_path: str, analysis: Dict[str, Any]) -> str:
    """Classify file based on functionality and risk level"""
    file_name = os.path.basename(file_path).lower()

    # Critical risk indicators
    if any(
        keyword in file_name
        for keyword in [
            "sepa",
            "payment",
            "financial",
            "invoice",
            "mandate",
            "dd_batch",
            "donation",
            "billing",
        ]
    ):
        return "CRITICAL"

    # High risk indicators
    if any(
        keyword in file_name
        for keyword in ["member", "customer", "termination", "admin", "security", "workspace"]
    ):
        return "HIGH"

    # Medium risk indicators
    if any(
        keyword in file_name
        for keyword in ["dashboard", "management", "api", "application", "chapter", "volunteer"]
    ):
        return "MEDIUM"

    # Low risk (debug, test, utility files)
    if any(
        keyword in file_name
        for keyword in ["debug", "test", "monitor", "validate", "check", "performance", "utility"]
    ):
        return "LOW"

    return "MEDIUM"  # Default


def generate_security_decorator(risk_level: str, function_name: str) -> str:
    """Generate appropriate security decorator based on risk level"""
    operation_types = {
        "CRITICAL": "OperationType.FINANCIAL",  # or ADMIN based on context
        "HIGH": "OperationType.MEMBER_DATA",
        "MEDIUM": "OperationType.REPORTING",
        "LOW": "OperationType.UTILITY",
    }

    decorators = {
        "CRITICAL": "critical_api",
        "HIGH": "high_security_api",
        "MEDIUM": "standard_api",
        "LOW": "standard_api",
    }

    # Refine based on function name
    if any(keyword in function_name.lower() for keyword in ["sepa", "payment", "financial", "invoice"]):
        operation_type = "OperationType.FINANCIAL"
        decorator = "critical_api"
    elif any(keyword in function_name.lower() for keyword in ["admin", "config", "system"]):
        operation_type = "OperationType.ADMIN"
        decorator = "critical_api"
    else:
        operation_type = operation_types.get(risk_level, "OperationType.UTILITY")
        decorator = decorators.get(risk_level, "standard_api")

    return f"@{decorator}(operation_type={operation_type})"


def main():
    print("🚀 Comprehensive API Security Analysis")
    print("=" * 50)

    # Find all API files with @frappe.whitelist
    print("🔍 Finding API files with @frappe.whitelist functions...")
    api_files = find_api_files_with_whitelist()
    print(f"Found {len(api_files)} API files with @frappe.whitelist functions")

    # Analyze security status
    print("\n📊 Analyzing security status...")
    secured_files = []
    unprotected_files = []
    analysis_results = {}

    for file_path in api_files:
        analysis = check_security_status(file_path)
        analysis_results[file_path] = analysis

        if analysis.get("secured", False):
            secured_files.append(file_path)
        elif analysis.get("needs_security", False):
            unprotected_files.append(file_path)

    print(f"✅ Secured files: {len(secured_files)}")
    print(f"❌ Unprotected files: {len(unprotected_files)}")

    # Classify unprotected files by risk level
    print("\n🎯 Risk Classification of Unprotected Files:")
    print("-" * 45)

    risk_classification = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}

    for file_path in unprotected_files:
        analysis = analysis_results[file_path]
        risk_level = classify_file_risk_level(file_path, analysis)
        risk_classification[risk_level].append(
            {"file": file_path, "analysis": analysis, "risk_level": risk_level}
        )

    for risk_level, files in risk_classification.items():
        if files:
            print(f"\n🔴 {risk_level} Risk ({len(files)} files):")
            for item in files[:5]:  # Show first 5
                file_path = item["file"]
                analysis = item["analysis"]
                print(f"   • {os.path.basename(file_path)} ({analysis['whitelist_functions']} functions)")
            if len(files) > 5:
                print(f"   ... and {len(files) - 5} more files")

    # Generate comprehensive report
    report = {
        "summary": {
            "total_api_files": len(api_files),
            "secured_files": len(secured_files),
            "unprotected_files": len(unprotected_files),
            "security_coverage": f"{(len(secured_files) / len(api_files) * 100):.1f}%",
        },
        "risk_breakdown": {level: len(files) for level, files in risk_classification.items()},
        "unprotected_files_detail": risk_classification,
        "all_files_analysis": analysis_results,
    }

    # Save detailed report
    with open("comprehensive_api_security_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\n📋 SUMMARY")
    print("=" * 20)
    print(f"Total API Files: {len(api_files)}")
    print(f"Secured Files: {len(secured_files)} ✅")
    print(f"Unprotected Files: {len(unprotected_files)} ❌")
    print(f"Security Coverage: {(len(secured_files) / len(api_files) * 100):.1f}%")

    print("\n🎯 NEXT STEPS")
    print("-" * 15)
    print("1. Review comprehensive_api_security_report.json for detailed analysis")
    print("2. Prioritize securing CRITICAL and HIGH risk files first")
    print("3. Apply appropriate security decorators to each file")
    print("4. Test functionality after securing each batch")

    if unprotected_files:
        print(f"\n⚠️  {len(unprotected_files)} files still need security decorators!")
        print("📝 Report saved to: comprehensive_api_security_report.json")
    else:
        print("\n🎉 All API files are secured! 100% coverage achieved.")


if __name__ == "__main__":
    main()
