# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""`member_id` must not rest on the clock alone (#549).

`member_id` is a UNIQUE column. `CoreTestDataFactory._generate_member_id` built it
from the sub-second microsecond plus a per-instance sequence:

    f"TEST{microsec:06d}{seq:03d}"     microsec = int(now.timestamp() * 1e6) % 1_000_000

`VereningingenTestCase.setUp` constructs a NEW factory for every test method
(`tests/utils/base.py`), so `_sequence_counters` restarts and the first member of
every test method is `...001`. All of them therefore contend for one 10^6 space, and
a repeat is `IntegrityError 1062`. Measured twice on 2026-08-23, different shards,
different modules, both ending `001`:

    PR #524 shard 3/12   TEST153429001   report.test_member_end_date_reconstruction
    develop  shard 9/12   TEST311263001   member.test_member_service_coverage

`EnhancedTestDataFactory._generate_unique_test_member_id`
(`enhanced_test_factory.py:589`) was already fixed for this and its docstring gives
`TEST161453001` as the example; the fix was never applied to this second copy. Note that
method has no callers, so it is a source for the format, not evidence for it. (That docstring also blames parallel shards sharing one database --
they do not: `services: mariadb:` sits inside the matrix job in
`.github/workflows/_base-server-tests.yml`, so each shard gets its own container.
The within-process mechanism above is the real one and is sufficient.)

Why the clock is frozen BEFORE the factories are constructed: `test_run_id` is itself
`datetime.now()`-derived, so two factories built in the same microsecond share it.
Deriving `member_id` from `test_run_id` alone would still collide in that window --
freezing first is what makes this test refuse that near-miss and demand per-call
entropy.
"""

import unittest
from unittest.mock import patch

from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory

MODULE = "verenigingen.tests.fixtures.test_data_factory"
ENHANCED_MODULE = "verenigingen.tests.fixtures.enhanced_test_factory"


class _FrozenDatetime:
    """`datetime` stand-in whose `now()` never advances."""

    _FIXED = 1_756_000_000.311263  # .311263 -> the microsec field seen on develop

    @classmethod
    def now(cls):
        return cls

    @classmethod
    def timestamp(cls):
        return cls._FIXED


class MemberIdMustNotRestOnTheClockAloneTest(unittest.TestCase):
    def test_the_freeze_actually_freezes_the_clock(self):
        """The control. Without it every assertion below could pass because the real
        clock advanced between calls, which is exactly the luck #549 runs on."""
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            first = CoreTestDataFactory().test_run_id
            second = CoreTestDataFactory().test_run_id

        self.assertEqual(
            first,
            second,
            "the patch did not freeze the clock, so nothing below is testing what it claims",
        )

    def test_the_sequence_restarts_at_one_for_every_factory(self):
        """The mechanism, pinned separately: this is why the colliding ids all end
        `001`. If a future factory shared its counter, the pin below would still pass
        but for a different reason, and that is worth knowing."""
        self.assertEqual(CoreTestDataFactory()._get_next_sequence("member_id"), 1)
        self.assertEqual(CoreTestDataFactory()._get_next_sequence("member_id"), 1)

    def test_two_factories_sharing_one_microsecond_still_get_different_ids(self):
        """The pin. Two factories built in the same microsecond -- the collision
        window -- must not produce the same first `member_id`."""
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            first = CoreTestDataFactory()._generate_member_id()
            second = CoreTestDataFactory()._generate_member_id()

        self.assertNotEqual(
            first,
            second,
            f"both factories emitted {first!r}: member_id rests on the clock alone, so "
            "two tests whose first member lands in the same microsecond collide on a "
            "UNIQUE column (IntegrityError 1062)",
        )

    def test_the_id_keeps_the_prefix_other_code_keys_on(self):
        """Scope guard: the fix must not change what consumers match on. The gap
        analysis in `member_id_manager` filters `member_id REGEXP '^[0-9]+$'`, which
        a `TEST` prefix is what keeps these rows out of."""
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            generated = CoreTestDataFactory()._generate_member_id()

        self.assertTrue(generated.startswith("TEST"), generated)
        self.assertFalse(generated.isdigit(), generated)


class SiblingGeneratorsMustNotRestOnTheClockEitherTest(unittest.TestCase):
    """The two generators called immediately above `member_id` have the same defect (#552).

    `create_test_member` calls `_generate_name` and `_generate_email` on the lines just
    above the `member_id` that #550 fixed. Both derive from the same per-factory,
    clock-derived `test_run_id` with no per-call entropy, so two factories built in the
    same microsecond produce identical values -- the identical shape, only the field
    differs.

    `_generate_name("last")` is the sharper of the two: `test_run_id[-5:]` is a **10^5**
    space, ten times narrower than the `member_id` bug, and its own docstring states the
    stake -- "prevent Customer name collisions (Customer uses full_name as primary key)".
    `Member.email` is not a unique column (the unique ones are `member_id`,
    `application_id`, `user`), so email is the lower-stakes half.
    """

    def test_two_factories_sharing_one_microsecond_get_different_emails(self):
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            first = CoreTestDataFactory()._generate_email()
            second = CoreTestDataFactory()._generate_email()

        self.assertNotEqual(
            first, second, f"both factories emitted {first!r}: email rests on the clock alone"
        )

    def test_two_factories_sharing_one_microsecond_get_different_last_names(self):
        with patch(f"{MODULE}.datetime", _FrozenDatetime):
            first = CoreTestDataFactory()._generate_name("last")
            second = CoreTestDataFactory()._generate_name("last")

        self.assertNotEqual(
            first,
            second,
            f"both factories emitted {first!r}: the last name rests on a 10^5 slice of the "
            "clock, and Customer uses full_name as its primary key",
        )


class SecureFactoryMemberIdMustNotUseWholeSecondsTest(unittest.TestCase):
    """`SecureTestDataFactory` collides DETERMINISTICALLY, not probabilistically (#552).

    Its `test_run_id` is `f"TEST-{random_string(8)}-{int(datetime.now().timestamp())}"`,
    and the member_id took `split("-")[-1]` -- which **discards the random component and
    keeps whole epoch seconds**. Any two factories constructed in the same second
    therefore produced the same id. Measured before the fix, two instances with
    DIFFERENT seeds:

        A  TEST-pMDXmlQg-1787520889 -> 1787520889001
        B  TEST-tix8ymDH-1787520889 -> 1787520889001

    Live via `verenigingen/verenigingen/doctype/chapter_member/test_chapter_members.py`,
    which constructs one in `setUp`.

    The ids were also **purely numeric**, so unlike every other factory id they passed
    `member_id REGEXP '^[0-9]+$'` and entered `member_id_manager`'s gap analysis and
    counter initialisation at ~1.79e12. The fix carries the `TEST` prefix the other
    factories use, which is what keeps them out.
    """

    def _factory(self):
        from verenigingen.tests.fixtures.enhanced_test_factory import SecureTestDataFactory

        return SecureTestDataFactory(test_user="Administrator", seed=1, cleanup_on_exit=False)

    def test_the_seconds_slice_really_is_shared(self):
        """The control: without a frozen clock two factories built in the same real
        second already share the slice, but the test would not be pinning that."""
        with patch(f"{ENHANCED_MODULE}.datetime", _FrozenDatetime):
            first = self._factory().test_run_id.split("-")[-1]
            second = self._factory().test_run_id.split("-")[-1]

        self.assertEqual(first, second, "the freeze did not take; nothing below is pinned")

    def test_two_factories_in_one_second_get_different_member_ids(self):
        with patch(f"{ENHANCED_MODULE}.datetime", _FrozenDatetime):
            first = self._factory()._generate_secure_member_id()
            second = self._factory()._generate_secure_member_id()

        self.assertNotEqual(
            first,
            second,
            f"both factories emitted {first!r}: the id is built from WHOLE epoch seconds, "
            "so this collides deterministically for any two factories in the same second",
        )

    def test_the_id_is_not_purely_numeric(self):
        """It must not pass `member_id REGEXP '^[0-9]+$'`: those rows reach
        `member_id_manager`'s gap analysis and counter init, where a ~1.79e12 value
        becomes `highest_assigned`."""
        with patch(f"{ENHANCED_MODULE}.datetime", _FrozenDatetime):
            generated = self._factory()._generate_secure_member_id()

        self.assertFalse(
            generated.isdigit(),
            f"{generated!r} is all digits, so it enters the numeric counter logic",
        )


if __name__ == "__main__":
    unittest.main()
