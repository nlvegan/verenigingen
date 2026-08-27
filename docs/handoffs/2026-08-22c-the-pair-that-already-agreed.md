# Handoff — 2026-08-22c: the pair that already agreed

Rebuilt #459 from scratch after the previous session's fix was reviewed and rejected, and
merged it as **#468**. The rebuild found something the rejection had not: the fix was not
merely insufficient, it was **negative**, and for a reason that generalises past locks.

> **Flipping one of an agreeing pair is worse than leaving both wrong.** Three paths took
> the same two locks. The issue named two of them, in opposite orders. The third was in
> the *same* order as the one I was about to change — so correcting the named path turned
> an agreeing pair into a deadlocking one, on every chapter save rather than sometimes.
> When you reorder anything shared, enumerate every participant **before** changing one.

## State

| | |
|---|---|
| `develop` | `452a2450` — #468 merged 09:10Z |
| **veg11 working tree (live)** | **`df43b092`**, checked 2026-08-22 09:12Z — **45 commits** behind. #459 **not live**. That tree fast-forwards on its own; re-check in the same breath as any sentence about it |
| CI on #468 | 44/44 SUCCESS on head `38f04201`, base unmoved at `00beeba8`, `mergeStateStatus: CLEAN` |
| Merged | **#468** (closes #459) |
| Filed | **#469** same-doctype Member inversion · **#470** TerminationExecutor swallows 1205/1213 |
| Superseded | `fix/459-history-lock-order` @ `5c9eee77` — never pushed, do not resurrect |
| Memory | `lock-probe-second-connection-2026-08-21.md` — corrected and extended |

## What the rebuild changed, and why each differs from the first attempt

**1. The chapter save.** Swapping the two handler groups is not behaviour-neutral:
`handle_board_member_additions` appended to `members`, and `handle_member_additions` diffs
that table *when it runs*, so board-last dropped the auto-added member's history row
entirely. The append moved into its own pass, `seat_board_members_as_chapter_members`,
which runs before everything — it takes no row lock, so it is free to go first, and the
append then precedes the diff regardless of where the board group sits. Both passes share
`_newly_seated_board_members`, so the two diffs cannot drift apart.

**2. Both terminations.** `UpdateMemberStatusOperation` is deliberately idx 13 and its
`member.save()` is a Member lock, so no reordering fixes it. Each implementation takes the
member's row up front instead, making every later acquisition a re-lock of a row already
held.

**3. The third path.** `api/termination_api.py:execute_safe_termination` — a second, older
implementation of the same termination behind two whitelisted ADMIN endpoints, with no
chapter-membership step at all, so its inversion was unconditional rather than
data-dependent. Found by the skeptical review, confirmed independently, fixed with the same
hoist.

## Three claims that were wrong, and what made each wrong

**#459's own premise: the termination is Member-first.** It is not a property of the
operation list. `disable_chapter_memberships_safe` returns before touching anything when
the member has no *enabled* `Chapter Member` row, so a board member off the roster locks
Volunteer at idx 3 and Member only at idx 13. Whether the order inverted was decided by the
member's data. **A fixture with a chapter membership measures green and proves nothing** —
the test that discriminates is the one whose member is off every roster.

**The previous handoff: `Member → Volunteer → Member` is non-canonical.** It is canonical
when the two Member acquisitions are the *same row* — a lock lives to end-of-transaction,
so the third is free. Asserting on the raw sequence reddens correct code. But dedupe by
*doctype alone* and `Member(A) → Volunteer → Member(B)` also reads as canonical, and that
one is a real inversion. **Row identity is not optional**, and the difference is invisible
without it.

**My own `_with_doc` comment: "the two paths".** Written inside the commit that fixes a
rule-6 bug, again — the third path is one `grep end_board_positions_safe` away. The comment
now names three, and the derivation moved to the test module docstring: which calls were
searched, the two near misses, and why no static grep of this can be exhaustive (any
`doc.save()` is a row lock). **A completeness claim needs its method attached, or the next
person inherits it instead of redoing it.**

## The instrument, third generation

Three claims about locks, three instruments — and each one was wrong for the previous
claim's question:

| claim | instrument | why the previous one failed |
|---|---|---|
| is this row locked (#424) | second connection, 1205 = held | source reading cannot see a `FOR UPDATE` that matched zero rows |
| *when* is it locked (#436) | second connection grabs the row **first** | a probe run after the code sees only that *a* lock exists by end-of-transaction |
| in what *order* (#459) | spy on `frappe.db.sql`, dedupe by (doctype, row) | a `get_value` spy sees 1 of 4 lock shapes and missed idx 13's plain `member.save()` |

Two traps inside the third one, both worth remembering:

- **`frappe.db.sql` passes a single parameter bare.** `Document.load_from_db`'s for-update
  fast path does `frappe.db.sql(..., (self.name))`, and `(x)` is not a tuple. An
  `isinstance(values, (list, tuple))` guard therefore failed to resolve **every** for-update
  document load, marked each as a fresh row, and **turned two correct paths red**. Caught
  only because those tests had been green a minute earlier.
- **No production path produces the shape the dedup rule is about.** `Member(A) → Volunteer
  → Member(B)` is unreachable on all three covered paths, which is exactly why the weakness
  would never have been noticed. `TestTheRecorderItself` feeds the classifier literal query
  strings instead — **an instrument whose weakness the fixtures cannot reach needs a
  synthetic control.**

## How #468 was verified

Five mutations, each reddening only its own tests:

| mutation | fails |
|---|---|
| board group back before member group | chapter lock-order test |
| up-front lock removed from `execute_system_updates` | the off-roster termination test |
| up-front lock removed from `execute_safe_termination` | the whitelisted-API test |
| seating pass moved after the member handlers | board-seating history test, on the *history* assertion |
| dedup reverted to doctype-only | the two row-identity self-tests |

The fourth is worth copying: the obvious control is *deleting* the seating pass, but that
also removes the `members` row, so the test would redden for the wrong reason. Moving it
leaves the row and breaks only the ordering, which is what the test is about.

`test_the_real_termination_operation_list_runs_and_takes_both_locks` was renamed from
`..._locks_in_canonical_order`: under the fix no reordering of the fourteen operations can
redden it, so the old name overstated its coverage. It stays as the only thing pinning that
the real production `operations = [...]` runs end to end.

## What is left

- **#469 — same-doctype Member inversion.** Seven unsorted loops over `chapter_doc.members`
  in `member_manager.py`; a member's `idx` differs per chapter, so two concurrent Chapter
  saves sharing members lock in opposite orders. The mechanism is measured (one save locks
  two different Member rows in child-table order); the *inversion* is inferred from the
  absence of sorting, not observed. Sorting by member name likely closes it, but the seven
  loops are not interchangeable — one of them appends, one is the board auto-seat path.
- **#470 — `TerminationExecutor` swallows 1205/1213** and runs operations N+1…13 against a
  transaction the server discarded. Pre-existing; #460 made `_with_doc` propagate precisely
  so callers would see these, and this caller does not. Fixing it is a visible behaviour
  change for admins (abort-and-retry instead of limp-on), which is why it was left out of
  #468 rather than bundled.
- **Nothing from #459 is live.** veg11 is 45 commits behind.
- **No live deadlock has ever been reproduced** through the application, on any of these
  three issues. What is demonstrated is acquisition order. That opposite orders deadlock is
  InnoDB semantics, not something this work shows.
- `fix/459-lock-order-canonical` deleted from the remote after merge.

## For whoever picks this up

- **Run the skeptical review before opening the PR, and then verify what it says.** It
  found the third path — the single most valuable finding in this session — and it was also
  wrong about the dedup rule being unexploitable (it measured "single row per doctype" for
  the termination, which held, but the fix for it immediately exposed a bug in my own row
  extraction). Both halves of that matter: brief it to *verify*, and check its work.
- **`gh issue view --comments` fails on this repo** (Projects-classic GraphQL). Use
  `gh api repos/{o}/{r}/issues/{n}` and `.../issues/{n}/comments`. `gh pr view --json` works;
  `gh pr edit` is still broken — use `gh api -X PATCH`.
- The lock instruments and their blind spots are in
  `.claude/projects/.../memory/lock-probe-second-connection-2026-08-21.md`, now with the
  agreeing-pair rule, the bare-scalar trap, and the synthetic-control rule.
- `verenigingen/tests/unit/test_history_lock_order.py` is the gate for any new multi-lock
  path. Its docstring carries the derivation of the three-path list and the reason that list
  can never be proven complete.
