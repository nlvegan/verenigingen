"""
Tests for ResponseBuilder and compute_hmac_signature helpers.

These are pure-Python helpers with no Frappe dependency; plain unittest is used.
"""

import hashlib
import hmac
import unittest


class TestResponseBuilderError(unittest.TestCase):
    """ResponseBuilder.error() produces a well-formed error dict."""

    def setUp(self):
        from verenigingen.verenigingen_payments.utils.shared.responses import ResponseBuilder

        self.rb = ResponseBuilder

    def test_status_defaults_to_error(self):
        result = self.rb.error("something went wrong")
        self.assertEqual(result["status"], "error")

    def test_message_is_set(self):
        result = self.rb.error("something went wrong")
        self.assertEqual(result["message"], "something went wrong")

    def test_error_code_defaults_to_none(self):
        result = self.rb.error("oops")
        self.assertIsNone(result["error_code"])

    def test_error_code_can_be_set(self):
        result = self.rb.error("oops", error_code="NOT_FOUND")
        self.assertEqual(result["error_code"], "NOT_FOUND")

    def test_details_defaults_to_none(self):
        result = self.rb.error("oops")
        self.assertIsNone(result["details"])

    def test_details_can_be_set(self):
        detail = {"field": "amount", "reason": "negative"}
        result = self.rb.error("oops", details=detail)
        self.assertEqual(result["details"], detail)

    def test_custom_status_overrides_default(self):
        result = self.rb.error("fail", status="validation_error")
        self.assertEqual(result["status"], "validation_error")

    def test_all_expected_keys_present(self):
        result = self.rb.error("oops")
        for key in ("status", "message", "error_code", "details"):
            self.assertIn(key, result)

    def test_returns_dict(self):
        result = self.rb.error("oops")
        self.assertIsInstance(result, dict)

    def test_all_args_together(self):
        result = self.rb.error(
            "bad input", status="validation_error", error_code="BAD_INPUT", details={"x": 1}
        )
        self.assertEqual(result["status"], "validation_error")
        self.assertEqual(result["message"], "bad input")
        self.assertEqual(result["error_code"], "BAD_INPUT")
        self.assertEqual(result["details"], {"x": 1})


class TestResponseBuilderSuccess(unittest.TestCase):
    """ResponseBuilder.success() produces a well-formed success dict."""

    def setUp(self):
        from verenigingen.verenigingen_payments.utils.shared.responses import ResponseBuilder

        self.rb = ResponseBuilder

    def test_status_defaults_to_success(self):
        result = self.rb.success()
        self.assertEqual(result["status"], "success")

    def test_message_defaults_to_empty_string(self):
        result = self.rb.success()
        self.assertEqual(result["message"], "")

    def test_message_can_be_set(self):
        result = self.rb.success("all good")
        self.assertEqual(result["message"], "all good")

    def test_data_defaults_to_none(self):
        result = self.rb.success()
        self.assertIsNone(result["data"])

    def test_data_can_be_set(self):
        result = self.rb.success(data={"a": 1})
        self.assertEqual(result["data"], {"a": 1})

    def test_custom_status_overrides_default(self):
        result = self.rb.success("ok", status="ignored")
        self.assertEqual(result["status"], "ignored")

    def test_all_expected_keys_present(self):
        result = self.rb.success()
        for key in ("status", "message", "data"):
            self.assertIn(key, result)

    def test_returns_dict(self):
        result = self.rb.success()
        self.assertIsInstance(result, dict)

    def test_all_args_together(self):
        result = self.rb.success("done", status="success", data={"id": 42})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["message"], "done")
        self.assertEqual(result["data"], {"id": 42})


class TestComputeHmacSignature(unittest.TestCase):
    """compute_hmac_signature replicates the hmac.new pattern used in webhook_security.py."""

    def setUp(self):
        from verenigingen.verenigingen_payments.utils.shared.responses import compute_hmac_signature

        self.fn = compute_hmac_signature

    def _reference(self, secret: str, payload: str, algorithm: str = "sha256") -> str:
        return hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            getattr(hashlib, algorithm),
        ).hexdigest()

    def test_matches_reference_basic(self):
        self.assertEqual(self.fn("k", "p"), self._reference("k", "p"))

    def test_returns_hex_string(self):
        result = self.fn("secret", "body")
        # hex digest of sha256 is 64 characters
        self.assertEqual(len(result), 64)
        self.assertRegex(result, r"^[0-9a-f]+$")

    def test_empty_payload(self):
        self.assertEqual(self.fn("secret", ""), self._reference("secret", ""))

    def test_empty_secret(self):
        self.assertEqual(self.fn("", "payload"), self._reference("", "payload"))

    def test_known_vector(self):
        # HMAC-SHA256("key", "The quick brown fox jumps over the lazy dog")
        expected = hmac.new(
            b"key",
            b"The quick brown fox jumps over the lazy dog",
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(self.fn("key", "The quick brown fox jumps over the lazy dog"), expected)

    def test_algorithm_sha256_explicit(self):
        self.assertEqual(
            self.fn("secret", "data", algorithm="sha256"),
            self._reference("secret", "data", "sha256"),
        )

    def test_algorithm_sha512(self):
        expected = hmac.new(b"secret", b"data", hashlib.sha512).hexdigest()
        self.assertEqual(self.fn("secret", "data", algorithm="sha512"), expected)

    def test_different_keys_produce_different_sigs(self):
        sig1 = self.fn("key1", "payload")
        sig2 = self.fn("key2", "payload")
        self.assertNotEqual(sig1, sig2)

    def test_different_payloads_produce_different_sigs(self):
        sig1 = self.fn("key", "payload1")
        sig2 = self.fn("key", "payload2")
        self.assertNotEqual(sig1, sig2)


if __name__ == "__main__":
    unittest.main()
