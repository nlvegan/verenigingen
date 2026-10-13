# 2026-10-11: the dialog said success

This session started from a maintainer bug report, not from an issue:

> i recently used the 'create volunteer' js button on the member record and selected 'full' but it
> didn't actually seem to create a user account, nor employee. can you check if this already uses the
> ACR system for creating these or not, and if not make it use it, and if it does, investigate and fix?

It was done in one coordinator session, which reviewed with sonnet `general-purpose` agents briefed
from `dispatch/reviewer_brief_common.md`. The maintainer's later instructions, in order:

1. "please do" (fix the silent failure; scope the Activate Volunteer role picker);
2. "request a skeptical review first";
3. rulings on the role picker (below);
4. "could you check if the custom role assignments for national chapter board member are limited to
   the chapter set as the national one?";
5. "we're not in production yet, it's fine" (public filing of the escalation it found);
6. "request a skeptical review when done, merge when CI goes green, then write handoff";
7. "yes merge the lot when green" (including #1608, owned by another session).

## Decisions made by the maintainer

| Subject | Decision | Where recorded |
|---|---|---|
| Activate Volunteer role picker | Offer only real roles, never more than the activating user's own | PR #1617 |
| Board / team roles | "CBM can only be assigned via the chapter we're talking about; same goes for team roles": never offered from activation | PR #1617, `get_requestable_volunteer_roles` docstring |
| Desk access | Drop roles without desk access from the picker | PR #1617 |
| National Board Member / Treasurer | Assigned by a seat on the board of `Verenigingen Settings.national_board_chapter`; the reverse route (granting them from activation) is to be blocked | #1615, PR #1617, PR #1619 |
| Disclosure | Pre-production, so the privilege escalation was filed publicly | #1616 |
| #1608 | Merge it (another session's PR) so the queue can go green | ledger |

Still open for the maintainer: #1612's (a)/(b) choice. On explicit full activation, either set the
volunteer to `Onboarding`, or make `is_active_volunteer` count a linked Employee.

## What shipped

- **PR #1617**: the Create Volunteer dialog no longer fails silently, and the Activate Volunteer picker
  offers only real, grantable, non-position roles.
  - The root cause, measured on test_site_2: the member had no email, and
    `queue_account_creation_for_member` refused. `create_volunteer_from_member` routed every refusal
    to a `frappe.logger().warning` that is never written. It read the reason from `result["message"]`,
    which the decorator-serialized `OperationResult` does not have (it is `error.message`).
  - Found on the way: the unticked "full" box reached Python as the string `"0"`, which is truthy, so
    "profile only" also queued an activation. Confirmed through `frappe.get_newargs`; no real browser
    request was made.
- **PR #1619** (fixes #1616): a chapter's board members could map any Role Profile onto their own
  board, including one that grants System Manager. The guard now requires the editor to hold every
  role a newly mapped (slot, profile) pair grants, and keeps the national profiles to the national
  chapter.
- **#1608** (another session's develop-green fix for frappe v16.50) was merged at the maintainer's
  instruction, because every PR was red on it.

## The pattern: the success message was the defect

Every layer of the reported bug was "working": the ACR system was used, the queue function returned
a clean `OperationResult.fail`, and the caller logged it. Nothing reached a human. The dialog's green
"Volunteer profile created successfully" was the only output, and it was false. Three separate
causes stacked up:

1. `frappe.logger().warning(...)` is never written (CLAUDE.md, "Known traps", counts three defects
   from it; this is a fourth, and that count should be updated);
2. the reason was read from a key the serialized result does not have;
3. the caller's response had no field for "created, but not activated", so the JS had nothing to show.

The same shape is in two more callers (`Volunteer.queue_secure_account_creation`,
`_check_auto_activation`) and the MijnRood volunteer sync. These are filed as #1613 and not fixed here.

**When a refusal has no Error Log, no record and no UI, check whether the caller's response can even
express it.** If it cannot, the fix starts at the response shape, not at the logging.

## The pattern repeated: a "check" question found an escalation

Question 4 was asked as a yes/no question. The answer was no. Following it one step further showed
that no profile restriction existed at all, and a board member of any chapter could map "Verenigingen
Administrator" onto their own board.

The probe deliberately did not stop at "the save succeeded":
- a profile sync run by the board member's own session fails (an empty-message "Role Profile Sync
  Failed");
- an Administrator-run sync applied it and produced System Manager;
- an intermediate National Board Member profile gives Verenigingen Staff, and with Staff the board
  member's own `bulk_apply_chapter_board_role_profiles` call was accepted.

That chain is what made it #1616 and not a nit.

## Each review round found a real defect in #1616

| Round | Finding | Fix |
|---|---|---|
| 1 (CHANGES REQUIRED) | the national rule ran on every save, so a chapter keeping a national mapping after `national_board_chapter` moved could not be saved at all | new-only |
| 1 | `ensure_chapter` (MijnRood dispatcher/CSV import) and `_ensure_default_teams` map fixed profiles but were checked against the session user's roles, so non-SM staff silently created no chapter | `flags.system_profile_mapping` |
| 1 | two `_save_default` helpers formed a clone family; the shrink gate only said "matches the tree" because it ran with `--already-regenerated` | renamed |
| 2 (APPROVE W/ NITS) | "new" was computed over a flat set, so moving an admin's role-specific mapping into the default slot widened it to the whole board unchecked | (slot, profile) pairs |

Not a review finding: the author's own first draft also refused any profile granting System
Manager. It was dropped before the reviewed commit (`bb227f256`), because team "Landelijk Beheer" is
wired to "Verenigingen Administrator" on purpose. The editor's-roles rule already covers a board
member mapping it.

Round 1's opposite-harm findings (lockout, provisioning) were both in code paths the author's sweep
had grepped for writers, but not run as a non-System-Manager. **A guard keyed on "who is saving" must
be driven as every caller that saves, including system code under a non-admin session.**

## Coordinator-checked deltas (not sent for another review round)

- #1617 `6b289a535`: a test-docstring nit from round 2 (comment-only).
- #1617 `6cf24efe6`: the pre-push cache-guard flagged two `get_roles(user)` reads made before
  `as_user`. They were moved inside the switch.
- #1619 `b1032f46e`: the slot-pair fix. The new test was red against `8c846ea1a` and green after;
  related modules were green on test_site_5.
- #1619 `a9a9751a8`: rename only. Once #1617 merged, the guard's private `_profile_roles` and the
  #1617 test helper of the same name formed a duplicate-helper clone family. `automerge.sh`'s
  pre-merge gate stopped on it ("No newly duplicated"). Each branch was clean alone. **Two PRs
  developed in parallel by the same coordinator can still collide in the clone census; run
  `premerge.sh <sha>` on the second one after the first lands, before re-queuing.**

## Coordinator notes

- **TDD slip, owned.** The #1616 round-1 fixes were written before their tests. The tests were added
  afterwards and shown red against the reviewed commit's code (`git checkout bb227f256 -- <code>`),
  then green. CLAUDE.md asks for the red first.
- **A mutant survived and exposed a test passing for the wrong reason.** The control "an existing
  mapping does not block a board member's unrelated save" stayed green with the previous-mapping logic
  removed. Mapping the profile *before* seating the board member synced them *into* that profile, so
  they held its roles. The test now seats first, and asserts the mapping is in place and the roles are
  absent before the save.
- **Red CI was the framework.** #1617's shard 11/12 failures were a subset of develop's own: frappe
  v16.50.0 (2026-10-06) made `Workspace.module` mandatory and added a native `module_onboarding`
  field. `cf8145756` was simply the first develop commit to run CI after that release. Diagnosis: grep
  the shard log for this PR's own error strings (0 hits), reproduce on untouched develop, then
  `git tag --contains` on the frappe commit that set `reqd`. The fix was already #1608.
- **Lock-wait in `test_bulk_queue_single_member_happy_path`**: 2 of 7 local runs on the branch, 0 of
  5 on develop. It happened in that test's own teardown (`Contact ... FOR UPDATE NOWAIT`), with live
  RQ workers on the bench. No leaked rows were found, and the reviewer could not reproduce it.
  Unattributed.
- **Reviewer worktree slip.** One reviewer's relative `worktree add` path created
  `apps/verenigingen/apps/`; it cleaned it up. The brief already says to use absolute paths.
- **Verenigingen Financial Manager can write Verenigingen Settings**, and so can Verenigingen
  Administrator, so either can move `national_board_chapter`. The #1616 round-2 reviewer noted
  Financial Manager; this is not changed or filed.
- **The handoff fact-checker detached the live checkout's HEAD** (`apps/verenigingen`, which veg11
  serves) to read `origin/develop`, then put it back on `develop`. The reflog shows both checkouts.
  It was harmless here, but read-only agents should read via `git show origin/develop:<path>` or a
  detached worktree of their own, never by moving the live tree. Add that to the fact-check brief.

## Filed this session, still open

| # | What | Established / not |
|---|---|---|
| #1612 | ACR Phase 3 (`_sync_role_profile`) undoes explicit volunteer activation: a `New` volunteer is downgraded to the Member profile, which strips Volunteer, Employee and any picked roles | measured with a synchronous pipeline; policy (a)/(b) pending |
| #1613 | the sibling silent refusals (`queue_secure_account_creation`, `_check_auto_activation`, and `volunteer_sync_service.py:129`, which still calls `mark_acr_queued` when activation was refused) | the button path was measured on test_site_2; the three siblings were read only |
| #1614 | an old Failed ACR blocks every new request for the member; `_check_auto_activation` ignores Failed | measured on test_site_2. The session's probe set the ACR's status to Failed directly (`db.set_value`), which the issue body does not say. Per rule 13, the Failed state was not reached through the real flow |
| #1615 | national chapter board seats never grant the National Board Member / Treasurer profiles | read |
| #1616 | board profile mapping escalation | fixed by #1619 |
| #1618 | other Role Profile selectors outside the guard (Membership Type, MijnRood Role Mapping, ACR) | read, not probed |

Follow-up, not filed: after both PRs land, `account_creation_api._position_and_volunteer_profile_roles`
and `role_profile_mapping_guard.NATIONAL_PROFILES` both spell out the two national profile names.
The picker could import the guard's constant.

## Final state

- **Merged:**

  | PR | merge commit | what |
  |---|---|---|
  | #1608 | `b15a4dd76` | another session's develop-green fix |
  | #1617 | `558840f9d` | volunteer activation |
  | #1619 | `e298d22fb` | closes #1616 |

  All went through `automerge.sh`: fully green CI, the `premerge.sh` gates, merged pinned to head.
- **The live checkout** (`apps/verenigingen`, served as veg11) was fast-forwarded to `e298d22fb` by
  `automerge.sh`.
  - No DocType JSON, hooks, patches or fixtures changed, so no migrate is needed for schema. #1608
    changed install/migrate-time setup code (`setup/__init__.py`, `setup/workflow_setup.py`). That
    takes effect on the next migrate, and #1608's review measured 0 affected workflows on veg11.
  - `volunteer-utils.js` is loaded straight from the symlinked `public/` folder (`member.js:114`), so
    no build is needed.
  - **veg11 was restarted** at the maintainer's request ("sync and restart veg11"): `supervisorctl
    restart frappe-bench-web: frappe-bench-workers:`. Afterwards ping answered, and an anonymous call
    to the new `get_requestable_volunteer_roles` returned 403 (it exists), against 417 for an unknown
    method.
- **Open, waiting on the maintainer:** the #1612 policy (a)/(b). Until it is decided, roles picked in
  the Activate Volunteer dialog, and the Volunteer role itself for a `New` volunteer, are stripped by
  ACR Phase 3.
- **Open, workable:** #1613, #1614, #1615, #1618.
- **Worktrees:** `worktrees/vol-activation`, `worktrees/issue-1616` and `worktrees/handoff-1011` can
  be removed once this handoff PR merges. No agents are running, and test sites 2-5, 8 and 9 are free.
