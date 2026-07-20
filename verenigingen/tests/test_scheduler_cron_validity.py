import frappe
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFinancialHistoryCron(EnhancedTestCase):
    def test_financial_history_cron_is_a_valid_5_field_expression(self):
        from croniter import croniter
        from verenigingen.hooks import scheduler

        crons = scheduler.scheduler_events["cron"]
        key = next(
            k
            for k, v in crons.items()
            if any("financial_history_batch_processor" in fn for fn in v)
        )
        self.assertEqual(len(key.split()), 5, "must be a valid 5-field cron")
        self.assertTrue(croniter.is_valid(key))
