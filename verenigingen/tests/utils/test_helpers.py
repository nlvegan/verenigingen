import unittest

from verenigingen.verenigingen.doctype.member.test_member import TestMember


def run_member_tests():
    """Run member tests and return results"""
    try:
        suite = unittest.TestLoader().loadTestsFromTestCase(TestMember)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        return {
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "success_rate": (result.testsRun - len(result.failures) - len(result.errors))
            / result.testsRun
            * 100
            if result.testsRun > 0
            else 0}
    except Exception as e:
        return {"error": str(e)}
