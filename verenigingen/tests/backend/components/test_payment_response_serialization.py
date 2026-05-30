"""Unit tests for the OperationResult -> flat HTTP response serializer.

Guards the fix for the bug where whitelisted payment endpoints returned a raw
OperationResult dataclass, which Frappe's json_handler cannot serialize (HTTP
500), and whose nested to_dict() shape did not match the flat keys the report JS
(`r.message.file_url` / `r.message.count`) and the test-suite read.

Plain unittest.TestCase (no DB) — the serializer is a pure function.
"""
import json
import unittest

from verenigingen.api.payment_processing import _operation_result_to_response
from verenigingen.utils.operation_result import OperationResult


class TestPaymentResponseSerialization(unittest.TestCase):
    def test_success_payload_is_flattened_to_top_level(self):
        result = OperationResult.ok(
            data={"count": 3, "file_url": "/files/x.csv", "file_name": "x.csv"},
            message="Export completed successfully",
        )
        response = _operation_result_to_response(result)
        self.assertIs(response["success"], True)
        self.assertEqual(response["count"], 3)
        self.assertEqual(response["file_url"], "/files/x.csv")
        self.assertEqual(response["file_name"], "x.csv")
        self.assertEqual(response["message"], "Export completed successfully")
        # data must NOT be nested under a "data" key — the JS reads r.message.file_url
        self.assertNotIn("data", response)

    def test_no_data_success(self):
        result = OperationResult.ok(data={"count": 0}, message="No data to export")
        response = _operation_result_to_response(result)
        self.assertEqual(response, {"success": True, "count": 0, "message": "No data to export"})

    def test_failure_payload(self):
        result = OperationResult.fail("You don't have permission", http_status_code=403)
        response = _operation_result_to_response(result)
        self.assertIs(response["success"], False)
        self.assertEqual(response["message"], "You don't have permission")

    def test_response_is_json_serializable(self):
        # The actual production bug: a raw OperationResult is not JSON-serializable,
        # so a whitelisted endpoint returning one 500s during response serialization.
        for result in (
            OperationResult.ok(data={"count": 1, "file_url": "/f"}, message="ok"),
            OperationResult.fail("nope", http_status_code=500),
        ):
            json.dumps(_operation_result_to_response(result))  # must not raise

    def test_non_operation_result_passes_through(self):
        self.assertEqual(_operation_result_to_response({"a": 1}), {"a": 1})
        self.assertIsNone(_operation_result_to_response(None))


if __name__ == "__main__":
    unittest.main()
