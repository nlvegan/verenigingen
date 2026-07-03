"""
Regression tests for shared-mutable-SecurityProfile contamination.

Audit finding #1 (2026-07-02): the api_security_framework wrapper mutated the
shared class-level SECURITY_PROFILES instance when applying per-endpoint
overrides (allowed_environments / max_request_size). Because every endpoint of
a given SecurityLevel shares one profile object, a single @development_only_api
call would poison the LOW profile's allowed_environments (403-ing all
self-service/utility endpoints in production), and a custom max_request_size
would raise the size limit for every other endpoint of that level.

The fix copies the profile (dataclasses.replace) before applying overrides, so
overrides are request-local. These tests assert the shared template is never
mutated by decorated endpoints.
"""

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.security.api_security_framework import (
    development_only_api,
    get_security_framework,
    standard_api,
)
from verenigingen.utils.security.types import EnvironmentLevel, SecurityLevel


class TestSecurityProfileIsolation(VereningingenTestCase):
    """Per-endpoint profile overrides must not mutate the shared templates."""

    def test_development_only_does_not_poison_shared_low_profile(self):
        """A @development_only_api call must not strip PRODUCTION/STAGING from the
        shared LOW profile that @self_service_api / @utility_api also use."""
        framework = get_security_framework()
        low_profile = framework.SECURITY_PROFILES[SecurityLevel.LOW]
        original_envs = list(low_profile.allowed_environments)

        # PRODUCTION and STAGING must be allowed pre-call (that is what the
        # self-service/utility endpoints rely on).
        self.assertIn(EnvironmentLevel.PRODUCTION, original_envs)

        @development_only_api()
        def _dev_only_endpoint():
            return {"ok": True}

        # Invoke the wrapper. In a non-development environment this raises
        # (correctly blocking the dev endpoint) but the override is applied
        # BEFORE that check, so it is the ideal trigger for the mutation bug.
        try:
            _dev_only_endpoint()
        except Exception:
            pass

        self.assertEqual(
            list(framework.SECURITY_PROFILES[SecurityLevel.LOW].allowed_environments),
            original_envs,
            "development_only_api leaked allowed_environments onto the shared LOW profile",
        )
        self.assertIn(
            EnvironmentLevel.PRODUCTION,
            framework.SECURITY_PROFILES[SecurityLevel.LOW].allowed_environments,
            "shared LOW profile no longer permits PRODUCTION after a dev-only call",
        )

    def test_max_request_size_override_does_not_poison_shared_medium_profile(self):
        """A @standard_api(max_request_size=...) call must not raise the request
        size limit for every other MEDIUM endpoint."""
        framework = get_security_framework()
        medium_profile = framework.SECURITY_PROFILES[SecurityLevel.MEDIUM]
        original_size = medium_profile.max_request_size

        oversized = original_size + 13 * 1024 * 1024

        @standard_api(max_request_size=oversized)
        def _big_payload_endpoint():
            return {"ok": True}

        # The size override is applied before any auth/env check, so invoking the
        # wrapper triggers the mutation path regardless of whether the call itself
        # ultimately succeeds.
        try:
            _big_payload_endpoint()
        except Exception:
            pass

        self.assertEqual(
            framework.SECURITY_PROFILES[SecurityLevel.MEDIUM].max_request_size,
            original_size,
            "max_request_size override leaked onto the shared MEDIUM profile",
        )
