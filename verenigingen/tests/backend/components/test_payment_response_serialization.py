"""Unit tests for the flat-API-response helper on the payment endpoints.

In production, ``@critical_api`` serializes the endpoint's OperationResult with
``OperationResult.to_dict(scrub_sensitive=True)`` (nested) BEFORE the
``_flatten_operation_result`` decorator runs, so the decorator receives a NESTED
dict ``{success, timestamp, data, meta}`` — NOT a raw OperationResult. The
overdue-payments report JS and the test-suite read flat top-level keys
(``r.message.file_url`` / ``r.message.count``), so the helper must flatten that
nested envelope. These tests feed it the exact ``to_dict`` output critical_api
produces, so they guard the real runtime path.

Plain unittest.TestCase (no DB) — the helper is a pure function.
"""
import json
import unittest

from verenigingen.api.payment_processing import _flatten_api_response
from verenigingen.utils.operation_result import OperationResult


def _as_critical_api_emits(result: OperationResult) -> dict:
    """Reproduce exactly what @critical_api returns: to_dict(scrub_sensitive=True)."""
    return result.to_dict(scrub_sensitive=True)


class TestPaymentResponseSerialization(unittest.TestCase):
    def test_success_envelope_is_flattened_to_top_level(self):
        envelope = _as_critical_api_emits(
            OperationResult.ok(
                data={"count": 3, "file_url": "/files/x.csv", "file_name": "x.csv"},
                message="Export completed successfully",
            )
        )
        # Precondition: the envelope really is nested (the bug the JS hits).
        self.assertIn("data", envelope)
        self.assertIsNone(envelope.get("file_url"))

        flat = _flatten_api_response(envelope)
        self.assertIs(flat["success"], True)
        self.assertEqual(flat["count"], 3)
        self.assertEqual(flat["file_url"], "/files/x.csv")
        self.assertEqual(flat["file_name"], "x.csv")
        self.assertEqual(flat["message"], "Export completed successfully")
        # data/meta envelope keys must be gone (JS reads r.message.file_url, not .data.file_url)
        self.assertNotIn("data", flat)
        self.assertNotIn("meta", flat)

    def test_no_data_success(self):
        envelope = _as_critical_api_emits(
            OperationResult.ok(data={"count": 0}, message="No data to export")
        )
        flat = _flatten_api_response(envelope)
        self.assertIs(flat["success"], True)
        self.assertEqual(flat["count"], 0)
        self.assertEqual(flat["message"], "No data to export")

    def test_failure_envelope_is_flattened(self):
        envelope = _as_critical_api_emits(
            OperationResult.fail("You don't have permission", http_status=403)
        )
        self.assertIn("error", envelope)  # precondition: nested error object
        flat = _flatten_api_response(envelope)
        self.assertIs(flat["success"], False)
        self.assertEqual(flat["message"], "You don't have permission")
        self.assertNotIn("error", flat)

    def test_response_is_json_serializable(self):
        for result in (
            OperationResult.ok(data={"count": 1, "file_url": "/f"}, message="ok"),
            OperationResult.fail("nope", http_status=500),
        ):
            json.dumps(_flatten_api_response(_as_critical_api_emits(result)))  # must not raise

    def test_raw_operation_result_is_serialized_defensively(self):
        # If @critical_api is ever absent, a raw OperationResult must still flatten.
        flat = _flatten_api_response(
            OperationResult.ok(data={"count": 2, "file_url": "/g"}, message="ok")
        )
        self.assertEqual(flat["count"], 2)
        self.assertEqual(flat["file_url"], "/g")
        self.assertNotIn("data", flat)

    def test_plain_dict_and_non_dict_pass_through(self):
        self.assertEqual(_flatten_api_response({"already": "flat"}), {"already": "flat"})
        self.assertIsNone(_flatten_api_response(None))


if __name__ == "__main__":
    unittest.main()
