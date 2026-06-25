import unittest

from verenigingen.verenigingen_payments.utils.shared.backoff import calculate_backoff_delay


class TestBackoffCalculator(unittest.TestCase):
    """Test the shared backoff delay calculator."""

    def test_exponential_no_jitter(self):
        """Test exponential backoff with no jitter."""
        # Base 1.0, exponential_base 2.0, no jitter
        # attempt 1: 1.0 * 2^0 = 1.0
        # attempt 2: 1.0 * 2^1 = 2.0
        # attempt 3: 1.0 * 2^2 = 4.0
        self.assertEqual(calculate_backoff_delay(1, base_delay=1.0, max_delay=60.0), 1.0)
        self.assertEqual(calculate_backoff_delay(2, base_delay=1.0, max_delay=60.0), 2.0)
        self.assertEqual(calculate_backoff_delay(3, base_delay=1.0, max_delay=60.0), 4.0)

    def test_caps_at_max_delay(self):
        """Test that delay is capped at max_delay before jitter."""
        # attempt 10: 1.0 * 2^9 = 512.0, capped at 60.0
        self.assertEqual(calculate_backoff_delay(10, base_delay=1.0, max_delay=60.0), 60.0)

    def test_linear(self):
        """Test linear backoff strategy."""
        # Linear: base_delay * attempt
        self.assertEqual(calculate_backoff_delay(1, base_delay=1.0, strategy="linear"), 1.0)
        self.assertEqual(calculate_backoff_delay(2, base_delay=1.0, strategy="linear"), 2.0)
        self.assertEqual(calculate_backoff_delay(3, base_delay=1.0, strategy="linear"), 3.0)
        self.assertEqual(calculate_backoff_delay(4, base_delay=1.0, strategy="linear"), 4.0)
        self.assertEqual(calculate_backoff_delay(5, base_delay=1.0, strategy="linear"), 5.0)

    def test_fixed(self):
        """Test fixed backoff strategy."""
        # Fixed: always base_delay
        self.assertEqual(calculate_backoff_delay(1, base_delay=1.0, strategy="fixed"), 1.0)
        self.assertEqual(calculate_backoff_delay(2, base_delay=1.0, strategy="fixed"), 1.0)
        self.assertEqual(calculate_backoff_delay(5, base_delay=1.0, strategy="fixed"), 1.0)
        # With different base
        self.assertEqual(calculate_backoff_delay(3, base_delay=2.5, strategy="fixed"), 2.5)

    def test_fibonacci(self):
        """Test fibonacci backoff strategy."""
        # Fibonacci with base 1.0: fib(1)=1, fib(2)=1, fib(3)=2, fib(4)=3, fib(5)=5
        # delay = base_delay * fib(attempt)
        self.assertEqual(calculate_backoff_delay(1, base_delay=1.0, strategy="fibonacci"), 1.0)
        self.assertEqual(calculate_backoff_delay(2, base_delay=1.0, strategy="fibonacci"), 1.0)
        self.assertEqual(calculate_backoff_delay(3, base_delay=1.0, strategy="fibonacci"), 2.0)
        self.assertEqual(calculate_backoff_delay(4, base_delay=1.0, strategy="fibonacci"), 3.0)
        self.assertEqual(calculate_backoff_delay(5, base_delay=1.0, strategy="fibonacci"), 5.0)

    def test_jitter_uses_injected_rng(self):
        """Test that jitter uses injected rng function."""
        # exponential attempt 1: delay = 1.0
        # jitter = delay * jitter_factor * rng() = 1.0 * 0.1 * 0.5 = 0.05
        # result = 1.0 + 0.05 = 1.05
        result = calculate_backoff_delay(
            1,
            base_delay=1.0,
            max_delay=60.0,
            strategy="exponential",
            jitter_factor=0.1,
            rng=lambda: 0.5,
        )
        self.assertEqual(result, 1.05)

    def test_jitter_with_default_rng(self):
        """Test that jitter works with default rng (random.random)."""
        # Just ensure it returns a value within expected range
        # exponential attempt 1: delay = 1.0
        # jitter_factor = 0.1, so jitter should be in [0, 0.1)
        # result should be in [1.0, 1.1)
        result = calculate_backoff_delay(
            1,
            base_delay=1.0,
            max_delay=60.0,
            strategy="exponential",
            jitter_factor=0.1,
        )
        self.assertGreaterEqual(result, 1.0)
        self.assertLess(result, 1.1)

    def test_returns_non_negative(self):
        """Test that result is never negative."""
        result = calculate_backoff_delay(1, base_delay=0.0, strategy="fixed")
        self.assertGreaterEqual(result, 0.0)


if __name__ == "__main__":
    unittest.main()
