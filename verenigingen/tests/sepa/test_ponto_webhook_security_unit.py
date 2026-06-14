# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto Webhook Security (JWT/JWKS) verification tests.

Tests the RS512 JWT signature verification in
``verenigingen.verenigingen_payments.ponto.utils.webhook_security``.

Testing approach (Tier-1 unit, ``*_unit.py``):
    No live Ponto credentials / JWKS endpoint exist, so we generate a real
    RSA keypair inside the test, sign real RS512 JWTs with it, and stub ONLY
    the external JWKS-fetch boundary (``PyJWKClient.get_signing_key_from_jwt``
    or the mTLS ``requests.get``) to return the matching public key. The JWT
    decode / claim-validation / digest-comparison logic runs for real - this
    is real cryptographic verification, not mocked business logic.

Usage:
    bench --site test_site_1 run-tests --app verenigingen \\
        --module verenigingen.tests.sepa.test_ponto_webhook_security_unit
"""

import base64
import hashlib
import json
import time
import unittest
from unittest.mock import MagicMock, patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from frappe.tests.utils import FrappeTestCase
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from verenigingen.verenigingen_payments.ponto.exceptions import PontoWebhookError
from verenigingen.verenigingen_payments.ponto.utils.webhook_security import (
    PontoWebhookVerifier,
    get_webhook_verifier,
    verify_ponto_webhook,
)

SECURITY_MODULE = "verenigingen.verenigingen_payments.ponto.utils.webhook_security"

TEST_AUDIENCE = "ponto-app-test-123"
TEST_ISSUER = "https://api.ibanity.com"
TEST_KID = "ponto-test-kid-1"


def _generate_keypair():
    """Generate an RSA-2048 keypair; return (private_pem_str, public_key_obj)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return private_pem, private_key.public_key()


def _build_jwk(public_key, kid=TEST_KID):
    """Build a PyJWK signing key (as PyJWKClient would return) from a public key."""
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk_dict.update({"kid": kid, "use": "sig", "alg": "RS512"})
    return PyJWK.from_dict(jwk_dict), jwk_dict


def _sha512_b64(payload: bytes) -> str:
    return base64.b64encode(hashlib.sha512(payload).digest()).decode("utf-8")


def _make_token(
    private_pem: str,
    payload: bytes,
    *,
    audience=TEST_AUDIENCE,
    issuer=TEST_ISSUER,
    kid=TEST_KID,
    algorithm="RS512",
    iat=None,
    exp_offset=300,
    include_digest=True,
    digest_value=None,
    extra_claims=None,
    drop_claims=(),
):
    """Sign an Ibanity-style webhook JWT with the test private key."""
    now = int(time.time())
    iat = now if iat is None else iat
    claims = {
        "iss": issuer,
        "aud": audience,
        "iat": iat,
        "exp": iat + exp_offset,
        "sub": "webhook-subject",
    }
    if include_digest:
        claims["digest"] = digest_value if digest_value is not None else _sha512_b64(payload)
    if extra_claims:
        claims.update(extra_claims)
    for claim in drop_claims:
        claims.pop(claim, None)
    return jwt.encode(claims, private_pem, algorithm=algorithm, headers={"kid": kid})


class TestPontoWebhookVerifierHappyPath(FrappeTestCase):
    """Valid RS512 signatures should verify and return claims."""

    def setUp(self):
        self.private_pem, self.public_key = _generate_keypair()
        self.signing_key, _ = _build_jwk(self.public_key)
        self.payload = json.dumps(
            {"data": {"type": "pontoConnect.synchronization.succeeded", "id": "abc"}}
        ).encode("utf-8")
        self.verifier = PontoWebhookVerifier(
            application_id=TEST_AUDIENCE, issuer=TEST_ISSUER
        )

    def test_valid_signature_verifies_and_returns_claims(self):
        token = _make_token(self.private_pem, self.payload)
        with patch.object(
            PontoWebhookVerifier, "_fetch_signing_key", return_value=self.signing_key
        ):
            claims = self.verifier.verify(self.payload, token)
        self.assertEqual(claims["aud"], TEST_AUDIENCE)
        self.assertEqual(claims["iss"], TEST_ISSUER)
        self.assertEqual(claims["sub"], "webhook-subject")

    def test_valid_signature_via_pyjwkclient_boundary_stub(self):
        """Stub only the JWKS HTTP boundary; full decode runs for real."""
        token = _make_token(self.private_pem, self.payload)
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = self.signing_key
        # mTLS disabled -> uses PyJWKClient path
        with patch.object(PontoWebhookVerifier, "_is_mtls_enabled", return_value=False):
            with patch.object(
                PontoWebhookVerifier, "_get_jwks_client", return_value=mock_client
            ):
                claims = self.verifier.verify(self.payload, token)
        self.assertEqual(claims["aud"], TEST_AUDIENCE)
        mock_client.get_signing_key_from_jwt.assert_called_once_with(token)


class TestPontoWebhookVerifierRejections(FrappeTestCase):
    """Tampered / invalid signatures must be rejected with PontoWebhookError."""

    def setUp(self):
        self.private_pem, self.public_key = _generate_keypair()
        self.signing_key, _ = _build_jwk(self.public_key)
        self.payload = json.dumps({"data": {"type": "t", "id": "1"}}).encode("utf-8")
        self.verifier = PontoWebhookVerifier(
            application_id=TEST_AUDIENCE, issuer=TEST_ISSUER
        )

    def _verify(self, token, payload=None):
        with patch.object(
            PontoWebhookVerifier, "_fetch_signing_key", return_value=self.signing_key
        ):
            return self.verifier.verify(payload if payload is not None else self.payload, token)

    def test_missing_signature_rejected(self):
        with self.assertRaises(PontoWebhookError) as ctx:
            self.verifier.verify(self.payload, "")
        self.assertIn("Missing webhook signature", str(ctx.exception))

    def test_empty_payload_rejected(self):
        token = _make_token(self.private_pem, self.payload)
        with self.assertRaises(PontoWebhookError) as ctx:
            self.verifier.verify(b"", token)
        self.assertIn("Empty webhook payload", str(ctx.exception))

    def test_wrong_key_rejected(self):
        """A token signed by a different key must fail signature verification."""
        other_pem, _ = _generate_keypair()
        token = _make_token(other_pem, self.payload)  # signed with the WRONG key
        with self.assertRaises(PontoWebhookError):
            self._verify(token)

    def test_expired_signature_rejected(self):
        token = _make_token(self.private_pem, self.payload, iat=int(time.time()) - 1000, exp_offset=10)
        with self.assertRaises(PontoWebhookError) as ctx:
            self._verify(token)
        self.assertIn("expired", str(ctx.exception).lower())

    def test_wrong_audience_rejected(self):
        token = _make_token(self.private_pem, self.payload, audience="some-other-app")
        with self.assertRaises(PontoWebhookError) as ctx:
            self._verify(token)
        self.assertIn("audience", str(ctx.exception).lower())

    def test_wrong_issuer_rejected(self):
        token = _make_token(self.private_pem, self.payload, issuer="https://evil.example.com")
        with self.assertRaises(PontoWebhookError) as ctx:
            self._verify(token)
        self.assertIn("issuer", str(ctx.exception).lower())

    def test_wrong_algorithm_rejected(self):
        """RS256 token must be rejected - verifier only accepts RS512."""
        token = _make_token(self.private_pem, self.payload, algorithm="RS256")
        with self.assertRaises(PontoWebhookError):
            self._verify(token)

    def test_missing_required_claim_rejected(self):
        """A token without the required digest claim must be rejected."""
        token = _make_token(self.private_pem, self.payload, include_digest=False)
        with self.assertRaises(PontoWebhookError):
            self._verify(token)

    def test_tampered_payload_digest_mismatch_rejected(self):
        """Valid JWT but payload bytes differ from the signed digest."""
        token = _make_token(self.private_pem, self.payload)
        tampered = json.dumps({"data": {"type": "t", "id": "TAMPERED"}}).encode("utf-8")
        with self.assertRaises(PontoWebhookError) as ctx:
            self._verify(token, payload=tampered)
        self.assertIn("digest", str(ctx.exception).lower())

    def test_iat_out_of_tolerance_rejected(self):
        """An iat far in the past (but exp still valid) is rejected by the iat-tolerance check."""
        now = int(time.time())
        # iat 10 minutes ago, but exp far in the future so JWT exp check passes
        token = _make_token(
            self.private_pem, self.payload, iat=now - 600, exp_offset=7200
        )
        # leeway/tolerance default is 30s; the explicit iat check should trip.
        with self.assertRaises(PontoWebhookError) as ctx:
            self._verify(token)
        self.assertIn("tolerance", str(ctx.exception).lower())

    def test_malformed_token_decode_error(self):
        with self.assertRaises(PontoWebhookError):
            self._verify("not-a-jwt-token")


class TestPontoWebhookFetchSigningKey(FrappeTestCase):
    """Test the JWKS key-fetch dispatch (mTLS vs PyJWKClient)."""

    def setUp(self):
        self.private_pem, self.public_key = _generate_keypair()
        self.signing_key, self.jwk_dict = _build_jwk(self.public_key)
        self.payload = json.dumps({"data": {"type": "t", "id": "1"}}).encode("utf-8")
        self.token = _make_token(self.private_pem, self.payload)
        self.verifier = PontoWebhookVerifier(
            application_id=TEST_AUDIENCE, issuer=TEST_ISSUER
        )

    def test_fetch_signing_key_non_mtls_uses_pyjwkclient(self):
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.return_value = self.signing_key
        with patch.object(PontoWebhookVerifier, "_is_mtls_enabled", return_value=False):
            with patch.object(
                PontoWebhookVerifier, "_get_jwks_client", return_value=mock_client
            ):
                key = self.verifier._fetch_signing_key(self.token)
        self.assertIs(key, self.signing_key)

    def test_fetch_signing_key_mtls_matches_kid(self):
        """mTLS path: JWKS dict is parsed and key matched by kid."""
        jwks_data = {"keys": [self.jwk_dict]}
        with patch.object(PontoWebhookVerifier, "_is_mtls_enabled", return_value=True):
            with patch.object(
                PontoWebhookVerifier, "_fetch_jwks_with_mtls", return_value=jwks_data
            ):
                key = self.verifier._fetch_signing_key(self.token)
        self.assertEqual(key.key_id, TEST_KID)

    def test_fetch_signing_key_mtls_kid_not_found(self):
        """mTLS path with no matching kid raises PontoWebhookError."""
        other_jwk = dict(self.jwk_dict)
        other_jwk["kid"] = "a-different-kid"
        jwks_data = {"keys": [other_jwk]}
        with patch.object(PontoWebhookVerifier, "_is_mtls_enabled", return_value=True):
            with patch.object(
                PontoWebhookVerifier, "_fetch_jwks_with_mtls", return_value=jwks_data
            ):
                with self.assertRaises(PontoWebhookError) as ctx:
                    self.verifier._fetch_signing_key(self.token)
        self.assertIn("Signing key not found", str(ctx.exception))

    def test_fetch_signing_key_pyjwkclient_error_wrapped(self):
        """PyJWKClientError should be wrapped in PontoWebhookError."""
        mock_client = MagicMock()
        mock_client.get_signing_key_from_jwt.side_effect = jwt.exceptions.PyJWKClientError(
            "no keys"
        )
        with patch.object(PontoWebhookVerifier, "_is_mtls_enabled", return_value=False):
            with patch.object(
                PontoWebhookVerifier, "_get_jwks_client", return_value=mock_client
            ):
                with self.assertRaises(PontoWebhookError) as ctx:
                    self.verifier._fetch_signing_key(self.token)
        self.assertIn("Failed to fetch webhook signing keys", str(ctx.exception))


class TestPontoWebhookFetchJwksWithMtls(FrappeTestCase):
    """Test the mTLS JWKS fetch + caching/fallback logic (HTTP boundary stubbed)."""

    def setUp(self):
        self.verifier = PontoWebhookVerifier(
            application_id=TEST_AUDIENCE, issuer=TEST_ISSUER
        )
        self.jwks_data = {"keys": [{"kid": "k1", "kty": "RSA", "n": "abc", "e": "AQAB"}]}

    def _cert_manager_cm(self, setup_ok=True):
        """Build a context-manager mock standing in for SecureCertManager()."""
        cm = MagicMock()
        cm.setup_from_settings.return_value = setup_ok
        cm.get_cert_files.return_value = ("/tmp/cert.pem", "/tmp/key.pem")
        ctx = MagicMock()
        ctx.__enter__.return_value = cm
        ctx.__exit__.return_value = False
        return ctx

    def test_mtls_fetch_success_caches(self):
        resp = MagicMock()
        resp.json.return_value = self.jwks_data
        resp.raise_for_status.return_value = None
        with patch(f"{SECURITY_MODULE}.SecureCertManager", return_value=self._cert_manager_cm()):
            with patch(f"{SECURITY_MODULE}.requests.get", return_value=resp):
                with patch("frappe.cache") as mock_cache:
                    mock_cache.return_value.get_value.return_value = None
                    result = self.verifier._fetch_jwks_with_mtls()
        self.assertEqual(result, self.jwks_data)
        mock_cache.return_value.set_value.assert_called_once()

    def test_mtls_cert_setup_failure_no_cache_raises(self):
        with patch(f"{SECURITY_MODULE}.SecureCertManager", return_value=self._cert_manager_cm(setup_ok=False)):
            with patch("frappe.cache") as mock_cache:
                mock_cache.return_value.get_value.return_value = None
                with self.assertRaises(PontoWebhookError) as ctx:
                    self.verifier._fetch_jwks_with_mtls()
        self.assertIn("Failed to setup mTLS certificates", str(ctx.exception))

    def test_mtls_cert_setup_failure_falls_back_to_cache(self):
        with patch(f"{SECURITY_MODULE}.SecureCertManager", return_value=self._cert_manager_cm(setup_ok=False)):
            with patch("frappe.cache") as mock_cache:
                mock_cache.return_value.get_value.return_value = self.jwks_data
                result = self.verifier._fetch_jwks_with_mtls()
        self.assertEqual(result, self.jwks_data)

    def test_mtls_temporary_error_falls_back_to_cache(self):
        import requests as _requests

        with patch(f"{SECURITY_MODULE}.SecureCertManager", return_value=self._cert_manager_cm()):
            with patch(
                f"{SECURITY_MODULE}.requests.get",
                side_effect=_requests.RequestException("503 Service Unavailable"),
            ):
                with patch("frappe.cache") as mock_cache:
                    mock_cache.return_value.get_value.return_value = self.jwks_data
                    result = self.verifier._fetch_jwks_with_mtls()
        self.assertEqual(result, self.jwks_data)

    def test_mtls_permanent_error_no_cache_raises(self):
        import requests as _requests

        with patch(f"{SECURITY_MODULE}.SecureCertManager", return_value=self._cert_manager_cm()):
            with patch(
                f"{SECURITY_MODULE}.requests.get",
                side_effect=_requests.RequestException("400 Bad Request"),
            ):
                with patch("frappe.cache") as mock_cache:
                    mock_cache.return_value.get_value.return_value = None
                    with self.assertRaises(PontoWebhookError) as ctx:
                        self.verifier._fetch_jwks_with_mtls()
        self.assertIn("Failed to fetch JWKS with mTLS", str(ctx.exception))


class TestPontoWebhookDigestAndDefaults(FrappeTestCase):
    """Test digest computation and constructor defaults."""

    def test_compute_payload_digest_matches_sha512_b64(self):
        verifier = PontoWebhookVerifier(application_id="x")
        payload = b'{"hello":"world"}'
        expected = base64.b64encode(hashlib.sha512(payload).digest()).decode("utf-8")
        self.assertEqual(verifier._compute_payload_digest(payload), expected)

    def test_default_issuer_and_jwks_url(self):
        from verenigingen.verenigingen_payments.ponto.utils.webhook_security import (
            IBANITY_PONTO_API_BASE,
            IBANITY_PONTO_JWKS_URL,
        )

        verifier = PontoWebhookVerifier(application_id="x")
        self.assertEqual(verifier.issuer, IBANITY_PONTO_API_BASE)
        self.assertEqual(verifier.jwks_url, IBANITY_PONTO_JWKS_URL)
        self.assertEqual(verifier.tolerance, 30)

    def test_get_jwks_client_is_cached(self):
        verifier = PontoWebhookVerifier(application_id="x")
        client1 = verifier._get_jwks_client()
        client2 = verifier._get_jwks_client()
        self.assertIs(client1, client2)


class TestVerifyPontoWebhookConvenience(FrappeTestCase):
    """Test the module-level verify_ponto_webhook() / get_webhook_verifier()."""

    def setUp(self):
        self.private_pem, self.public_key = _generate_keypair()
        self.signing_key, _ = _build_jwk(self.public_key)
        self.payload = json.dumps({"data": {"type": "t", "id": "1"}}).encode("utf-8")

    def test_verify_ponto_webhook_with_explicit_application_id(self):
        token = _make_token(self.private_pem, self.payload)
        with patch.object(
            PontoWebhookVerifier, "_fetch_signing_key", return_value=self.signing_key
        ):
            claims = verify_ponto_webhook(
                self.payload, token, application_id=TEST_AUDIENCE, issuer=TEST_ISSUER
            )
        self.assertEqual(claims["aud"], TEST_AUDIENCE)

    def test_verify_ponto_webhook_reads_application_id_from_settings(self):
        token = _make_token(self.private_pem, self.payload)
        fake_settings = MagicMock()
        fake_settings.get_webhook_application_id.return_value = TEST_AUDIENCE
        with patch("frappe.get_single", return_value=fake_settings):
            with patch.object(
                PontoWebhookVerifier, "_fetch_signing_key", return_value=self.signing_key
            ):
                claims = verify_ponto_webhook(self.payload, token, issuer=TEST_ISSUER)
        self.assertEqual(claims["aud"], TEST_AUDIENCE)
        fake_settings.get_webhook_application_id.assert_called_once()

    def test_verify_ponto_webhook_no_application_id_raises(self):
        fake_settings = MagicMock()
        fake_settings.get_webhook_application_id.return_value = ""
        with patch("frappe.get_single", return_value=fake_settings):
            with self.assertRaises(PontoWebhookError) as ctx:
                verify_ponto_webhook(self.payload, "sometoken")
        self.assertIn("no application ID configured", str(ctx.exception))

    def test_get_webhook_verifier_reads_settings_client_id(self):
        fake_settings = MagicMock()
        fake_settings.get_active_client_id.return_value = "client-abc"
        with patch("frappe.get_single", return_value=fake_settings):
            verifier = get_webhook_verifier()
        self.assertEqual(verifier.application_id, "client-abc")

    def test_get_webhook_verifier_with_explicit_id(self):
        verifier = get_webhook_verifier(application_id="explicit-id", tolerance=60)
        self.assertEqual(verifier.application_id, "explicit-id")
        self.assertEqual(verifier.tolerance, 60)


if __name__ == "__main__":
    unittest.main()
