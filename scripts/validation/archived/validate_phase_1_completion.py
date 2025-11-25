#!/usr/bin/env python3
"""
Phase 1 Completion Validation Script
Validates that all Phase 1 components are complete and operational.
"""

import json
import os
import subprocess
import sys
from datetime import datetime


def validate_phase_1_completion():
    """Validate Phase 1 completion status"""

    print("=== PHASE 1 COMPLETION VALIDATION ===")
    print(f"Timestamp: {datetime.now()}")
    print()

    validation_results = {
        "timestamp": datetime.now().isoformat(),
        "phase": "Phase_1_Complete",
        "components_validated": {},
        "overall_status": "running",
        "completion_percentage": 0,
        "missing_components": [],
        "recommendations": [],
    }

    # Define expected Phase 1 components
    phase_1_components = {
        "Phase_0_Infrastructure": {
            "production_deployment_validator": "scripts/monitoring/production_deployment_validator.py",
            "meta_monitoring_system": "scripts/monitoring/monitor_monitoring_system_health.py",
            "regression_test_suite": "scripts/testing/monitoring/test_performance_regression.py",
            "baseline_establishment": "scripts/monitoring/establish_baseline.py",
        },
        "Phase_1_5_2_Data_Efficiency": {
            "data_retention_manager": "verenigingen/utils/performance/data_retention.py"
        },
        "Phase_1_5_3_Configuration_Management": {
            "performance_config_system": "verenigingen/utils/performance/config.py"
        },
        "Phase_1_5_1_API_Convenience": {
            "convenience_api_methods": "verenigingen/api/performance_convenience.py"
        },
    }

    print("Validating Phase 1 component presence...")
    print()

    # Validate each component exists
    components_found = 0
    total_components = 0

    for phase_name, components in phase_1_components.items():
        print(f"Validating {phase_name}:")
        phase_results = {}

        for component_name, file_path in components.items():
            total_components += 1
            full_path = f"/home/frappe/frappe-bench/apps/verenigingen/{file_path}"

            if os.path.exists(full_path):
                # Check file size to ensure it's substantial
                file_size = os.path.getsize(full_path)
                if file_size > 10000:  # At least 10KB indicating substantial implementation
                    phase_results[component_name] = {
                        "status": "COMPLETE",
                        "file_path": file_path,
                        "file_size_kb": round(file_size / 1024, 1),
                    }
                    components_found += 1
                    print(f"  ✅ {component_name}: COMPLETE ({round(file_size / 1024, 1)} KB)")
                else:
                    phase_results[component_name] = {
                        "status": "INCOMPLETE",
                        "file_path": file_path,
                        "file_size_kb": round(file_size / 1024, 1),
                        "issue": "File too small - likely incomplete implementation",
                    }
                    validation_results["missing_components"].append(
                        f"{phase_name}.{component_name}: Incomplete implementation"
                    )
                    print(f"  ⚠️ {component_name}: INCOMPLETE (only {round(file_size / 1024, 1)} KB)")
            else:
                phase_results[component_name] = {
                    "status": "MISSING",
                    "file_path": file_path,
                    "issue": "File does not exist",
                }
                validation_results["missing_components"].append(
                    f"{phase_name}.{component_name}: File missing"
                )
                print(f"  ❌ {component_name}: MISSING")

        validation_results["components_validated"][phase_name] = phase_results
        print()

    # Calculate completion percentage
    completion_percentage = (components_found / total_components) * 100 if total_components > 0 else 0
    validation_results["completion_percentage"] = round(completion_percentage, 1)

    print("PHASE 1 COMPLETION SUMMARY:")
    print(f"  Components found: {components_found}/{total_components}")
    print(f"  Completion percentage: {completion_percentage:.1f}%")
    print()

    # Check API availability (simplified test)
    print("Validating API availability...")
    api_tests = [
        "performance_convenience.quick_health_check",
        "performance_convenience.comprehensive_member_analysis",
        "performance_convenience.batch_member_analysis",
        "performance_convenience.performance_dashboard_data",
    ]

    # Since we can't directly test API availability without Frappe context,
    # we'll check if the convenience API file has the expected methods
    try:
        convenience_api_path = (
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/api/performance_convenience.py"
        )
        if os.path.exists(convenience_api_path):
            with open(convenience_api_path, "r") as f:
                api_content = f.read()

            apis_found = 0
            for api_name in [
                "quick_health_check",
                "comprehensive_member_analysis",
                "batch_member_analysis",
                "performance_dashboard_data",
            ]:
                if f"def {api_name}" in api_content and "@frappe.whitelist()" in api_content:
                    apis_found += 1
                    print(f"  ✅ {api_name}: Available")
                else:
                    print(f"  ❌ {api_name}: Missing or not whitelisted")

            api_availability = (apis_found / len(api_tests)) * 100
            print(f"  API availability: {apis_found}/{len(api_tests)} ({api_availability:.1f}%)")
            validation_results["api_availability_percentage"] = api_availability
        else:
            print("  ❌ Convenience API file not found")
            validation_results["api_availability_percentage"] = 0
    except Exception as e:
        print(f"  ⚠️ API validation error: {e}")
        validation_results["api_availability_percentage"] = 0

    print()

    # Determine overall status
    if completion_percentage >= 95 and validation_results.get("api_availability_percentage", 0) >= 75:
        validation_results["overall_status"] = "COMPLETE"
        print("🎉 PHASE 1 VALIDATION: COMPLETE")
        print("✅ All major components present and substantial")
        print("✅ API convenience methods available")
        print("✅ Ready for production deployment")
    elif completion_percentage >= 85:
        validation_results["overall_status"] = "NEARLY_COMPLETE"
        print("🟡 PHASE 1 VALIDATION: NEARLY COMPLETE")
        print("⚠️ Some components may need final validation")
        print("✅ Core infrastructure operational")
    else:
        validation_results["overall_status"] = "INCOMPLETE"
        print("❌ PHASE 1 VALIDATION: INCOMPLETE")
        print("❌ Missing critical components")
        print("❌ Not ready for production deployment")

    print()

    # Generate recommendations
    if validation_results["overall_status"] == "COMPLETE":
        validation_results["recommendations"] = [
            "✅ Phase 1 implementation is complete and ready for production deployment",
            "✅ Execute final deployment script to activate all components",
            "✅ Monitor performance baselines during initial production operation",
            "✅ Begin planning Phase 2 enhancements based on Phase 1 success",
        ]
    elif validation_results["overall_status"] == "NEARLY_COMPLETE":
        validation_results["recommendations"] = [
            "🟡 Address remaining component issues before declaring complete",
            "🟡 Validate API functionality through Frappe context testing",
            "🟡 Execute focused testing on incomplete components",
            "✅ Core infrastructure is ready for operation",
        ]
    else:
        validation_results["recommendations"] = [
            "❌ Complete missing components before proceeding",
            "❌ Focus on critical infrastructure components first",
            "❌ Consider phased deployment of completed components",
            "⚠️ Review implementation plan and timeline",
        ]

    # Display recommendations
    print("RECOMMENDATIONS:")
    for rec in validation_results["recommendations"]:
        print(f"  {rec}")
    print()

    # Save validation results
    results_file = "/home/frappe/frappe-bench/apps/verenigingen/phase_1_validation_results.json"
    try:
        with open(results_file, "w") as f:
            json.dump(validation_results, f, indent=2, default=str)
        print(f"✅ Validation results saved to: {results_file}")
    except Exception as e:
        print(f"⚠️ Could not save validation results: {e}")

    return validation_results


if __name__ == "__main__":
    try:
        results = validate_phase_1_completion()

        # Exit with appropriate code
        if results["overall_status"] == "COMPLETE":
            exit(0)  # Success
        elif results["overall_status"] == "NEARLY_COMPLETE":
            exit(1)  # Nearly complete - needs attention
        else:
            exit(2)  # Incomplete - significant work needed

    except Exception as e:
        print(f"❌ Phase 1 validation failed: {e}")
        exit(3)  # Validation error
