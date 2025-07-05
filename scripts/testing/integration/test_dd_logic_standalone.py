#!/usr/bin/env python3
"""
Standalone DD Logic Testing
Tests core DD enhancement logic without Frappe dependencies
"""

import difflib
import re
import sys
from typing import Dict, List


class StandaloneMemberIdentityValidator:
    """Standalone version of MemberIdentityValidator for testing"""

    def __init__(self):
        self.similarity_threshold = 0.8
        self.phonetic_threshold = 0.9

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate name similarity using multiple algorithms"""
        if not name1 or not name2:
            return 0.0

        name1 = name1.lower().strip()
        name2 = name2.lower().strip()

        # Exact match
        if name1 == name2:
            return 1.0

        # Sequence similarity
        seq_similarity = difflib.SequenceMatcher(None, name1, name2).ratio()

        # Word-level similarity (handles different ordering)
        words1 = set(name1.split())
        words2 = set(name2.split())
        if len(words1) == 0 or len(words2) == 0:
            return seq_similarity

        word_similarity = len(words1.intersection(words2)) / max(len(words1), len(words2))

        # Take the maximum of both approaches
        return max(seq_similarity, word_similarity)

    def _normalize_iban(self, iban: str) -> str:
        """Normalize IBAN format for comparison"""
        if not iban:
            return ""
        return re.sub(r"[^A-Z0-9]", "", iban.upper())

    def _calculate_risk_score(self, factors: Dict) -> float:
        """Calculate overall risk score from multiple factors"""
        weights = {
            "name_similarity": 0.4,
            "email_similarity": 0.3,
            "iban_match": 0.2,
            "birth_date_match": 0.1,
        }

        score = 0.0
        for factor, value in factors.items():
            if factor in weights:
                if isinstance(value, bool):
                    value = 1.0 if value else 0.0
                score += weights[factor] * value

        return min(score, 1.0)

    def test_name_similarity_cases(self):
        """Test various name similarity scenarios"""
        test_cases = [
            # (name1, name2, expected_similarity_range)
            ("John Smith", "John Smith", (1.0, 1.0)),  # Exact match
            ("John Smith", "Jon Smith", (0.7, 0.95)),  # Similar names
            ("John Smith", "Johnny Smith", (0.6, 1.0)),  # Nickname
            ("John Smith", "Smith John", (0.8, 1.0)),  # Word order
            ("José García", "Jose Garcia", (0.7, 0.95)),  # Accent differences
            ("John Smith", "Jane Doe", (0.0, 0.3)),  # Different names
            ("", "John Smith", (0.0, 0.0)),  # Empty string
            ("John", "", (0.0, 0.0)),  # Empty string
        ]

        results = []
        for name1, name2, expected_range in test_cases:
            similarity = self._calculate_name_similarity(name1, name2)
            expected_min, expected_max = expected_range

            passed = expected_min <= similarity <= expected_max
            results.append(
                {
                    "name1": name1,
                    "name2": name2,
                    "similarity": similarity,
                    "expected_range": expected_range,
                    "passed": passed,
                }
            )

            status = "✅" if passed else "❌"
            print(
                f"{status} '{name1}' vs '{name2}': {similarity:.3f} (expected {expected_min:.1f}-{expected_max:.1f})"
            )

        return results

    def test_iban_normalization(self):
        """Test IBAN normalization"""
        test_cases = [
            ("NL43 INGB 1234 5678 90", "NL43INGB1234567890"),
            ("nl43-ingb-1234-5678-90", "NL43INGB1234567890"),
            ("NL43INGB1234567890", "NL43INGB1234567890"),
            ("", ""),
            ("INVALID IBAN!", "INVALIDIBAN"),
        ]

        results = []
        for input_iban, expected in test_cases:
            result = self._normalize_iban(input_iban)
            passed = result == expected
            results.append({"input": input_iban, "result": result, "expected": expected, "passed": passed})

            status = "✅" if passed else "❌"
            print(f"{status} '{input_iban}' -> '{result}' (expected '{expected}')")

        return results

    def test_risk_score_calculation(self):
        """Test risk score calculation"""
        test_cases = [
            # (factors, expected_range)
            (
                {
                    "name_similarity": 1.0,
                    "email_similarity": 1.0,
                    "iban_match": True,
                    "birth_date_match": True,
                },
                (0.9, 1.0),
            ),  # Very high risk
            (
                {
                    "name_similarity": 0.8,
                    "email_similarity": 0.0,
                    "iban_match": False,
                    "birth_date_match": False,
                },
                (0.3, 0.4),
            ),  # Medium risk
            (
                {
                    "name_similarity": 0.0,
                    "email_similarity": 0.0,
                    "iban_match": False,
                    "birth_date_match": False,
                },
                (0.0, 0.1),
            ),  # Low risk
            (
                {
                    "name_similarity": 0.5,
                    "email_similarity": 0.8,
                    "iban_match": True,
                    "birth_date_match": False,
                },
                (0.6, 0.7),
            ),  # High risk due to IBAN match
        ]

        results = []
        for factors, expected_range in test_cases:
            score = self._calculate_risk_score(factors)
            expected_min, expected_max = expected_range

            passed = expected_min <= score <= expected_max
            results.append(
                {"factors": factors, "score": score, "expected_range": expected_range, "passed": passed}
            )

            status = "✅" if passed else "❌"
            print(f"{status} Risk score: {score:.3f} (expected {expected_min:.1f}-{expected_max:.1f})")
            print(f"   Factors: {factors}")

        return results


class StandaloneAnomalyDetector:
    """Standalone anomaly detection for testing"""

    def analyze_payment_amounts(self, payments: List[Dict]) -> Dict:
        """Analyze payment amounts for anomalies"""
        anomalies = []

        for payment in payments:
            amount = payment.get("amount", 0)
            member_name = payment.get("member_name", "")

            issues = []

            # Check for unusual amounts
            if amount <= 0:
                issues.append("Zero or negative amount")
            elif amount > 500:  # Unusually high membership fee
                issues.append(f"Unusually high amount: {amount}")
            elif amount < 10:  # Unusually low membership fee
                issues.append(f"Unusually low amount: {amount}")

            if issues:
                anomalies.append({"payment": payment, "issues": issues})

        return {
            "anomalies": anomalies,
            "total_payments": len(payments),
            "anomaly_rate": len(anomalies) / max(1, len(payments)),
        }

    def test_amount_anomaly_detection(self):
        """Test payment amount anomaly detection"""
        test_payments = [
            {"member_name": "Normal Member", "amount": 50.00, "iban": "NL43INGB1111"},
            {"member_name": "Zero Member", "amount": 0.00, "iban": "NL43INGB2222"},
            {"member_name": "High Member", "amount": 999.99, "iban": "NL43INGB3333"},
            {"member_name": "Negative Member", "amount": -25.00, "iban": "NL43INGB4444"},
            {"member_name": "Low Member", "amount": 5.00, "iban": "NL43INGB5555"},
            {"member_name": "Another Normal", "amount": 75.00, "iban": "NL43INGB6666"},
        ]

        results = self.analyze_payment_amounts(test_payments)

        print(f"📊 Payment Analysis Results:")
        print(f"   Total payments: {results['total_payments']}")
        print(f"   Anomalies detected: {len(results['anomalies'])}")
        print(f"   Anomaly rate: {results['anomaly_rate']:.1%}")

        expected_anomalies = 4  # Zero, High, Negative, Low
        passed = len(results["anomalies"]) == expected_anomalies

        status = "✅" if passed else "❌"
        print(f"{status} Expected {expected_anomalies} anomalies, found {len(results['anomalies'])}")

        for anomaly in results["anomalies"]:
            member_name = anomaly["payment"]["member_name"]
            amount = anomaly["payment"]["amount"]
            issues = ", ".join(anomaly["issues"])
            print(f"   ⚠️  {member_name} (€{amount}): {issues}")

        return results


def run_standalone_tests():
    """Run all standalone tests"""
    print("🧪 DD Enhancement Standalone Logic Tests")
    print("=" * 50)

    # Test member identity validation
    print("\n1️⃣  Testing Name Similarity Calculation")
    print("-" * 40)
    validator = StandaloneMemberIdentityValidator()
    name_results = validator.test_name_similarity_cases()
    name_passed = sum(1 for r in name_results if r["passed"])
    print(f"   Results: {name_passed}/{len(name_results)} passed")

    print("\n2️⃣  Testing IBAN Normalization")
    print("-" * 35)
    iban_results = validator.test_iban_normalization()
    iban_passed = sum(1 for r in iban_results if r["passed"])
    print(f"   Results: {iban_passed}/{len(iban_results)} passed")

    print("\n3️⃣  Testing Risk Score Calculation")
    print("-" * 38)
    risk_results = validator.test_risk_score_calculation()
    risk_passed = sum(1 for r in risk_results if r["passed"])
    print(f"   Results: {risk_passed}/{len(risk_results)} passed")

    print("\n4️⃣  Testing Payment Anomaly Detection")
    print("-" * 42)
    detector = StandaloneAnomalyDetector()
    anomaly_results = detector.test_amount_anomaly_detection()
    anomaly_passed = len(anomaly_results["anomalies"]) == 4  # Expected anomalies

    # Summary
    print("\n📋 Test Summary")
    print("=" * 20)

    total_tests = 4
    passed_tests = sum(
        [
            name_passed == len(name_results),
            iban_passed == len(iban_results),
            risk_passed == len(risk_results),
            anomaly_passed,
        ]
    )

    print(f"✅ Passed: {passed_tests}/{total_tests}")
    print(f"❌ Failed: {total_tests - passed_tests}/{total_tests}")
    print(f"📈 Success Rate: {(passed_tests/total_tests)*100:.1f}%")

    if passed_tests == total_tests:
        print("\n🎉 All standalone logic tests passed!")
        print("   Core DD enhancement algorithms are working correctly.")
    else:
        print("\n⚠️  Some tests failed. Please review the logic.")

    return passed_tests == total_tests


def test_edge_case_scenarios():
    """Test specific edge case scenarios"""
    print("\n🔬 Testing Edge Case Scenarios")
    print("=" * 35)

    validator = StandaloneMemberIdentityValidator()

    # Test identical names with different addresses scenario
    print("\n📍 Scenario: Identical Names, Different Cities")
    john_amsterdam = {
        "first_name": "John",
        "last_name": "Smith",
        "email": "john.amsterdam@test.com",
        "iban": "NL43INGB1234567890",
    }

    john_rotterdam = {
        "first_name": "John",
        "last_name": "Smith",
        "email": "john.rotterdam@test.com",
        "iban": "NL43ABNA0987654321",
    }

    name_similarity = validator._calculate_name_similarity(
        f"{john_amsterdam['first_name']} {john_amsterdam['last_name']}",
        f"{john_rotterdam['first_name']} {john_rotterdam['last_name']}",
    )

    email_similarity = difflib.SequenceMatcher(None, john_amsterdam["email"], john_rotterdam["email"]).ratio()

    iban_match = validator._normalize_iban(john_amsterdam["iban"]) == validator._normalize_iban(
        john_rotterdam["iban"]
    )

    risk_score = validator._calculate_risk_score(
        {
            "name_similarity": name_similarity,
            "email_similarity": email_similarity,
            "iban_match": iban_match,
            "birth_date_match": False,
        }
    )

    print(f"   Name similarity: {name_similarity:.3f}")
    print(f"   Email similarity: {email_similarity:.3f}")
    print(f"   IBAN match: {iban_match}")
    print(f"   Risk score: {risk_score:.3f}")

    # Should detect high name similarity but reasonable risk due to different IBANs and emails
    scenario1_passed = name_similarity > 0.9 and risk_score < 0.8
    status1 = "✅" if scenario1_passed else "❌"
    print(f"   {status1} Should detect name similarity but allow different IBANs")

    # Test family members with same IBAN
    print("\n👨‍👩‍👧‍👦 Scenario: Family Members, Same IBAN")
    husband = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@family.com",
        "iban": "NL43INGB1111111111",
    }

    wife = {
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane.doe@family.com",
        "iban": "NL43INGB1111111111",  # Same IBAN
    }

    family_name_similarity = validator._calculate_name_similarity(
        f"{husband['first_name']} {husband['last_name']}", f"{wife['first_name']} {wife['last_name']}"
    )

    family_email_similarity = difflib.SequenceMatcher(None, husband["email"], wife["email"]).ratio()

    family_iban_match = validator._normalize_iban(husband["iban"]) == validator._normalize_iban(wife["iban"])

    family_risk_score = validator._calculate_risk_score(
        {
            "name_similarity": family_name_similarity,
            "email_similarity": family_email_similarity,
            "iban_match": family_iban_match,
            "birth_date_match": False,
        }
    )

    print(f"   Name similarity: {family_name_similarity:.3f}")
    print(f"   Email similarity: {family_email_similarity:.3f}")
    print(f"   IBAN match: {family_iban_match}")
    print(f"   Risk score: {family_risk_score:.3f}")

    # Should detect IBAN sharing but moderate risk due to family pattern
    scenario2_passed = family_iban_match and family_risk_score > 0.3 and family_risk_score < 0.8
    status2 = "✅" if scenario2_passed else "❌"
    print(f"   {status2} Should detect IBAN sharing with moderate risk for family")

    return scenario1_passed and scenario2_passed


if __name__ == "__main__":
    print("🚀 Starting DD Enhancement Standalone Tests")
    print("=" * 55)

    try:
        # Run core logic tests
        logic_success = run_standalone_tests()

        # Run edge case scenario tests
        scenario_success = test_edge_case_scenarios()

        # Overall results
        print("\n🏁 Final Results")
        print("=" * 20)

        if logic_success and scenario_success:
            print("🎉 ALL TESTS PASSED!")
            print("   DD enhancement logic is working correctly")
            print("   Ready for Frappe environment testing")
            sys.exit(0)
        else:
            print("💥 SOME TESTS FAILED!")
            print("   Please review and fix issues")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test error: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
