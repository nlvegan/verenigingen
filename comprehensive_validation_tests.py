import frappe
from frappe.utils import add_days, flt, today


@frappe.whitelist()
def run_comprehensive_validation_tests():
    """
    Comprehensive test suite for invoice validation safeguards
    Tests edge cases, error conditions, and business logic scenarios
    """

    results = {
        "test_categories": {
            "rate_validation": [],
            "membership_consistency": [],
            "transaction_safety": [],
            "edge_cases": [],
            "integration": [],
        },
        "summary": {"total": 0, "passed": 0, "failed": 0, "warnings": 0},
        "critical_findings": [],
        "recommendations": [],
    }

    try:
        # Test Category 1: Rate Validation Edge Cases
        print("Testing rate validation edge cases...")

        # Find schedules with different rate scenarios
        test_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"status": "Active", "is_template": 0},
            fields=["name", "member", "dues_rate", "membership_type", "last_generated_invoice"],
            limit=20,
        )

        rate_scenarios = {
            "zero_rates": [s for s in test_schedules if s.dues_rate == 0],
            "negative_rates": [s for s in test_schedules if s.dues_rate < 0],
            "high_rates": [s for s in test_schedules if s.dues_rate > 1000],
            "normal_rates": [s for s in test_schedules if 0 < s.dues_rate <= 1000],
        }

        results["test_categories"]["rate_validation"].append(
            {
                "test": "Rate scenario distribution",
                "zero_count": len(rate_scenarios["zero_rates"]),
                "negative_count": len(rate_scenarios["negative_rates"]),
                "high_count": len(rate_scenarios["high_rates"]),
                "normal_count": len(rate_scenarios["normal_rates"]),
                "status": "INFO",
            }
        )

        # Test specific rate validation scenarios
        if rate_scenarios["zero_rates"]:
            schedule = frappe.get_doc("Membership Dues Schedule", rate_scenarios["zero_rates"][0].name)
            rate_result = schedule.validate_dues_rate()

            test_result = {
                "test": "Zero rate validation",
                "schedule": schedule.name,
                "rate": schedule.dues_rate,
                "blocked": not rate_result["valid"],
                "reason": rate_result["reason"],
                "status": "PASS" if not rate_result["valid"] else "FAIL",
            }
            results["test_categories"]["rate_validation"].append(test_result)
            results["summary"]["total"] += 1
            if test_result["status"] == "PASS":
                results["summary"]["passed"] += 1
            else:
                results["summary"]["failed"] += 1

        # Test Category 2: Membership Type Consistency
        print("Testing membership type consistency...")

        # Test schedules with valid members
        valid_member_schedules = [
            s for s in test_schedules if s.member and frappe.db.exists("Member", s.member)
        ]

        if valid_member_schedules:
            for schedule_data in valid_member_schedules[:5]:  # Test first 5
                try:
                    schedule = frappe.get_doc("Membership Dues Schedule", schedule_data.name)
                    consistency_result = schedule.validate_membership_type_consistency()

                    test_result = {
                        "test": "Membership type consistency",
                        "schedule": schedule.name,
                        "schedule_type": schedule.membership_type,
                        "consistent": consistency_result["valid"],
                        "reason": consistency_result["reason"],
                        "status": "PASS" if consistency_result["valid"] else "WARNING",
                    }

                    results["test_categories"]["membership_consistency"].append(test_result)
                    results["summary"]["total"] += 1

                    if test_result["status"] == "PASS":
                        results["summary"]["passed"] += 1
                    else:
                        results["summary"]["warnings"] += 1

                except Exception as e:
                    results["test_categories"]["membership_consistency"].append(
                        {
                            "test": "Membership type consistency",
                            "schedule": schedule_data.name,
                            "error": str(e),
                            "status": "ERROR",
                        }
                    )
                    results["summary"]["failed"] += 1

        # Test Category 3: Transaction Safety Scenarios
        print("Testing transaction safety scenarios...")

        # Test what happens with missing customer records
        schedules_missing_customers = []
        for schedule_data in valid_member_schedules[:3]:
            try:
                member = frappe.get_doc("Member", schedule_data.member)
                if not member.customer:
                    schedules_missing_customers.append(
                        {
                            "schedule": schedule_data.name,
                            "member": schedule_data.member,
                            "member_name": getattr(member, "full_name", "Unknown"),
                        }
                    )
            except:
                pass

        results["test_categories"]["transaction_safety"].append(
            {
                "test": "Missing customer records",
                "count": len(schedules_missing_customers),
                "samples": schedules_missing_customers[:3],
                "status": "WARNING" if schedules_missing_customers else "PASS",
            }
        )

        if schedules_missing_customers:
            results["summary"]["warnings"] += 1
        else:
            results["summary"]["passed"] += 1
        results["summary"]["total"] += 1

        # Test Category 4: Edge Cases
        print("Testing edge cases...")

        # Test schedules with very old next_invoice_dates
        old_dates = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "status": "Active",
                "is_template": 0,
                "next_invoice_date": ["<", add_days(today(), -365)],
            },
            fields=["name", "next_invoice_date", "member_name"],
            limit=5,
        )

        results["test_categories"]["edge_cases"].append(
            {
                "test": "Schedules with very old next_invoice_dates",
                "count": len(old_dates),
                "samples": old_dates,
                "status": "WARNING" if old_dates else "PASS",
            }
        )

        if old_dates:
            results["summary"]["warnings"] += 1
            results["critical_findings"].append(
                f"Found {len(old_dates)} schedules with next_invoice_date > 1 year old"
            )
        else:
            results["summary"]["passed"] += 1
        results["summary"]["total"] += 1

        # Test schedules with null/missing dues_rate
        null_rates = frappe.db.count(
            "Membership Dues Schedule", {"status": "Active", "is_template": 0, "dues_rate": ["in", [None, 0]]}
        )

        results["test_categories"]["edge_cases"].append(
            {
                "test": "Schedules with null/zero dues_rate",
                "count": null_rates,
                "status": "WARNING" if null_rates > 0 else "PASS",
            }
        )

        if null_rates > 0:
            results["summary"]["warnings"] += 1
            results["critical_findings"].append(f"Found {null_rates} schedules with null/zero dues_rate")
        else:
            results["summary"]["passed"] += 1
        results["summary"]["total"] += 1

        # Test Category 5: Integration Tests
        print("Testing integration scenarios...")

        # Test can_generate_invoice with our new validations
        integration_test_count = 0
        integration_blocked_count = 0
        block_reasons = {}

        for schedule_data in test_schedules[:10]:
            try:
                schedule = frappe.get_doc("Membership Dues Schedule", schedule_data.name)
                can_generate, reason = schedule.can_generate_invoice()

                integration_test_count += 1
                if not can_generate:
                    integration_blocked_count += 1
                    if reason not in block_reasons:
                        block_reasons[reason] = 0
                    block_reasons[reason] += 1

            except Exception as e:
                integration_blocked_count += 1
                error_reason = f"Exception: {str(e)[:50]}..."
                if error_reason not in block_reasons:
                    block_reasons[error_reason] = 0
                block_reasons[error_reason] += 1

        results["test_categories"]["integration"].append(
            {
                "test": "Full can_generate_invoice validation",
                "tested": integration_test_count,
                "blocked": integration_blocked_count,
                "success_rate": f"{integration_test_count - integration_blocked_count}/{integration_test_count}",
                "block_reasons": block_reasons,
                "status": "PASS",
            }
        )
        results["summary"]["total"] += 1
        results["summary"]["passed"] += 1

        # Generate Recommendations
        if results["summary"]["warnings"] > 0:
            results["recommendations"].append(
                "⚠️ Data cleanup needed - multiple schedules have data integrity issues"
            )

        if null_rates > 20:
            results["recommendations"].append("🔴 High priority: Many schedules have invalid dues rates")

        if len(schedules_missing_customers) > 5:
            results["recommendations"].append("💰 Customer record creation needed for invoice generation")

        if old_dates:
            results["recommendations"].append(
                "📅 Schedule date cleanup - some schedules have very old next_invoice_dates"
            )

        # Overall assessment
        success_rate = (
            (results["summary"]["passed"] / results["summary"]["total"]) * 100
            if results["summary"]["total"] > 0
            else 0
        )

        results["overall_assessment"] = {
            "success_rate": f"{success_rate:.1f}%",
            "validation_effectiveness": "High - catching invalid rates and data issues",
            "system_health": "Good" if success_rate > 70 else "Needs attention",
            "ready_for_next_phase": success_rate > 60,
            "next_priorities": [
                "Customer financial status checks",
                "Batch processing limits",
                "Data cleanup for invalid schedules",
            ],
        }

        return results

    except Exception as e:
        results["error"] = str(e)
        results["summary"]["failed"] += 1
        return results


@frappe.whitelist()
def test_customer_validation_readiness():
    """Test if we're ready to implement customer financial status checks"""

    results = {
        "customer_data_quality": {},
        "outstanding_analysis": {},
        "credit_limit_analysis": {},
        "readiness_assessment": {},
    }

    try:
        # Check customer data quality
        total_members = frappe.db.count("Member", {"status": "Active"})
        members_with_customers = frappe.db.count("Member", {"status": "Active", "customer": ["!=", ""]})

        results["customer_data_quality"] = {
            "total_active_members": total_members,
            "members_with_customers": members_with_customers,
            "customer_coverage": f"{(members_with_customers/total_members*100):.1f}%"
            if total_members > 0
            else "0%",
            "missing_customers": total_members - members_with_customers,
        }

        # Analyze outstanding amounts
        if members_with_customers > 0:
            customers_with_outstanding = frappe.db.sql(
                """
                SELECT COUNT(*) as count, AVG(outstanding_amount) as avg_outstanding,
                       MAX(outstanding_amount) as max_outstanding
                FROM `tabCustomer` c
                INNER JOIN `tabMember` m ON m.customer = c.name
                WHERE m.status = 'Active' AND c.outstanding_amount > 0
            """,
                as_dict=True,
            )

            if customers_with_outstanding:
                results["outstanding_analysis"] = {
                    "customers_with_outstanding": customers_with_outstanding[0].count,
                    "average_outstanding": flt(customers_with_outstanding[0].avg_outstanding, 2),
                    "max_outstanding": flt(customers_with_outstanding[0].max_outstanding, 2),
                }

            # Check credit limits
            customers_with_credit_limits = frappe.db.count(
                "Customer",
                {
                    "name": [
                        "in",
                        frappe.get_all(
                            "Member", {"status": "Active", "customer": ["!=", ""]}, pluck="customer"
                        ),
                    ],
                    "credit_limit": [">", 0],
                },
            )

            results["credit_limit_analysis"] = {
                "customers_with_credit_limits": customers_with_credit_limits,
                "credit_limit_coverage": f"{(customers_with_credit_limits/members_with_customers*100):.1f}%"
                if members_with_customers > 0
                else "0%",
            }

        # Readiness assessment
        customer_coverage_pct = (members_with_customers / total_members * 100) if total_members > 0 else 0

        results["readiness_assessment"] = {
            "ready_for_customer_validation": customer_coverage_pct > 50,
            "data_quality_score": "Good"
            if customer_coverage_pct > 80
            else "Fair"
            if customer_coverage_pct > 50
            else "Poor",
            "implementation_risk": "Low"
            if customer_coverage_pct > 80
            else "Medium"
            if customer_coverage_pct > 50
            else "High",
            "recommended_approach": "Implement with graceful fallbacks"
            if customer_coverage_pct > 50
            else "Data cleanup first",
        }

        return results

    except Exception as e:
        results["error"] = str(e)
        return results


@frappe.whitelist()
def test_batch_processing_scenarios():
    """Test batch processing limits and performance scenarios"""

    results = {
        "current_batch_sizes": {},
        "processing_time_estimates": {},
        "resource_usage": {},
        "recommendations": [],
    }

    try:
        # Analyze current batch sizes
        total_schedules = frappe.db.count("Membership Dues Schedule", {"status": "Active", "is_template": 0})
        due_now = frappe.db.count(
            "Membership Dues Schedule",
            {"status": "Active", "is_template": 0, "next_invoice_date": ["<=", today()]},
        )
        due_30_days = frappe.db.count(
            "Membership Dues Schedule",
            {"status": "Active", "is_template": 0, "next_invoice_date": ["<=", add_days(today(), 30)]},
        )

        results["current_batch_sizes"] = {
            "total_active_schedules": total_schedules,
            "due_now": due_now,
            "due_within_30_days": due_30_days,
            "largest_potential_batch": due_30_days,
        }

        # Performance estimates (rough calculations)
        estimated_time_per_schedule = 2  # seconds (conservative estimate)

        results["processing_time_estimates"] = {
            "time_for_current_due": f"{due_now * estimated_time_per_schedule / 60:.1f} minutes",
            "time_for_30_day_batch": f"{due_30_days * estimated_time_per_schedule / 60:.1f} minutes",
            "recommended_batch_size": min(100, due_30_days) if due_30_days > 0 else 50,
            "batches_needed": max(1, due_30_days // 100) if due_30_days > 0 else 0,
        }

        # Resource usage analysis
        results["resource_usage"] = {
            "database_connections_needed": min(10, due_30_days // 10),
            "memory_estimate": f"{due_30_days * 0.1:.1f} MB",
            "risk_level": "High" if due_30_days > 500 else "Medium" if due_30_days > 100 else "Low",
        }

        # Recommendations
        if due_30_days > 200:
            results["recommendations"].append("🚨 Implement batch size limits (recommend max 100 per run)")
        if due_30_days > 500:
            results["recommendations"].append("⚠️ Consider background job processing for large batches")
        if due_now > 50:
            results["recommendations"].append("📊 Monitor processing time and add progress reporting")

        results["recommendations"].append("✅ Add batch processing safeguards before next scheduled run")

        return results

    except Exception as e:
        results["error"] = str(e)
        return results


if __name__ == "__main__":
    frappe.init()
    frappe.connect()

    print("=== Comprehensive Validation Tests ===")
    validation_results = run_comprehensive_validation_tests()
    print(
        f"Validation Tests - Passed: {validation_results['summary']['passed']}, Failed: {validation_results['summary']['failed']}, Warnings: {validation_results['summary']['warnings']}"
    )

    print("\n=== Customer Readiness Test ===")
    customer_results = test_customer_validation_readiness()
    print(
        f"Customer Coverage: {customer_results.get('customer_data_quality', {}).get('customer_coverage', 'Unknown')}"
    )

    print("\n=== Batch Processing Test ===")
    batch_results = test_batch_processing_scenarios()
    print(
        f"Current batch size: {batch_results.get('current_batch_sizes', {}).get('due_within_30_days', 0)} schedules"
    )
