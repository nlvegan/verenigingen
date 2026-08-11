# Test harness: stop suppressing production document behavior (`in_import`, Phase 1)

Date: 2026-07-30
Status: implemented; fallout measurement pending
Revision 2 — corrected after adversarial review. Revision 1's central mechanism
(`in_bulk_import` as an `in_import` substitute) was **proven wrong** and has been removed;
see "Rejected: `in_bulk_import`" below.

## Problem

`EnhancedTestCase.setUp` set `frappe.flags.in_import = True`. The stated reason, in the
comment directly above it, was to bypass Frappe's `throttle_user_creation()`, whose entire
guard is:

```python
def throttle_user_creation():
    if frappe.flags.in_import:
        return
    if frappe.db.get_creation_count("User", 60) > frappe.local.conf.get("throttle_user_limit", 60):
        frappe.throw(_("Throttled"))
```

That flag buys one thing and pays for many. The following were disabled in every test on the
harness. This list is **not exhaustive** — `in_import` is read in ~35 places across Frappe:

**Validation and defaults (the motivation for this change):**

| Suppressed | Location | Consequence in tests |
|---|---|---|
| `_set_defaults()` | defined `frappe/model/document.py:998` | No document defaults on new docs |
| `_validate_selects()` | defined `frappe/model/base_document.py:1094` | Invalid Select values accepted that production rejects |
| `_validate_constants()` | `frappe/model/base_document.py:1170` | `set_only_once` fields silently mutable |
| Autoname regeneration | `frappe/model/naming.py:158` | See the caveat below — this one cuts both ways |
| Subscriber dispatch | `verenigingen/events/subscribers/subscriber_utils.py:45`, `chapter_subscribers.py:132` | The app's own event subscribers never ran |

**Also restored, and not previously listed — each is a behavior change to audit:**

| Now live | Location | Note |
|---|---|---|
| `notify_update()` realtime publish per save | `frappe/model/document.py:1420` | |
| `clear_cache()` on new docs | `frappe/model/document.py:1388` | |
| `run_webhooks()` | `frappe/integrations/doctype/webhook/__init__.py:40` | |
| `assignment_rule.update_due_date` | `frappe/automation/.../assignment_rule.py:368` | hooked on `"*"` `on_update`, so it runs on **every** save |
| `insert_feed` on delete | `frappe/model/delete_doc.py:546` | a `Comment` row per `delete_doc`; the harness drains many docs |
| `NestedSet.after_insert` cache clear | `frappe/utils/nestedset.py:270` | |
| table-count / domain caches | `frappe/cache_manager.py:215,247,264` | |
| `trigger_notifications` | `frappe/email/doctype/notification/notification.py:763` | |
| standard-file export under `developer_mode` | `doctype.py:548`, `modules/utils.py:35`, `report.py:157,429`, `web_form.py:95`, `print_style.py:40`, `website_theme.py:57,68`, `export_file.py:21`, others | see Risks |

**Autoname caveat.** `naming.py:158` is not purely a benefit. With `in_import` off,
`doc.name = None` is applied, which *discards* an explicitly set `name` on an autonamed
DocType. Any test that sets `name` and later looks up that literal will now fail. This is a
silent breaking change in the opposite direction from the others.

**Not affected, contrary to revision 1.** `run_notifications` (`frappe/model/document.py:1199`)
requires `in_import` **and** `mute_emails`; `EnhancedTestCase` never set `mute_emails`, so
notification behavior is unchanged.

`send_welcome_email` also defaults to `'1'` in `user.json`, so restoring defaults means test
Users that don't set it explicitly will now attempt a welcome email.

Critical Operation Rule also branches on `in_import` (`critical_operation_rule.py:120,201`),
but only for notification validation and digest queueing. COR *enforcement* is not disabled.
This is not a security hole.

## Design

In `EnhancedTestCase.setUp`, replace `frappe.flags.in_import = True` with a raised throttle
limit and nothing else:

```python
self._original_throttle_limit = frappe.local.conf.get("throttle_user_limit")
self.addCleanup(self._restore_throttle_user_limit)
frappe.local.conf["throttle_user_limit"] = 1000000
```

`addCleanup` rather than `tearDown`: if `setUp` raises after this line, unittest skips
`tearDown` but still runs cleanups, so the override cannot leak into the rest of the process.
`_restore_throttle_user_limit()` **deletes** the key when it was originally absent rather
than restoring `None` — a stored `None` would make `count > conf.get(..., 60)` raise
`TypeError` instead of falling back to 60 — and tests `is None` rather than falsiness so a
deliberate `0` survives.

Mechanically sound: `throttle_user_creation()` reads `frappe.local.conf`, and in tests
`local.conf` is a fresh non-cached `_dict` (`frappe/config.py:28-30`, `cached=bool(frappe.request)`
is False), so the mutation neither leaks into the site-config cache nor across sites.

### Rejected: `in_bulk_import` as a substitute

Revision 1 additionally set `frappe.flags.in_bulk_import = True`, intending to hold the phase
boundary by keeping subscriber dispatch suppressed. **This is wrong and was removed.** It
suppresses strictly *more* than `in_import`, not the same:

The event **emitters** in `events/team_events.py:36`, `events/member_events.py:34-36` and
`events/chapter_events.py:37` gate on `bulk_*_operations or in_bulk_import` and never look at
`in_import`. Under `in_import` they emit normally; setting `in_bulk_import` short-circuits
them *before* `event_emitter.emit_event()` is reached, including the `run_events_synchronously`
test affordance. Only the **subscriber** side consults `in_import`.

Measured on `test_site_2`, `verenigingen.tests.events.test_team_events_coverage`:

- with `in_bulk_import = True`: **Ran 28, FAILED (failures=3)** —
  `test_emit_membership_changed_dispatches_to_subscriber_synchronously`,
  `test_emit_membership_changed_emitter_swallows_dispatch_failure`,
  `test_team_dispatch_forwards_bulk_flag_to_emitter` (`AssertionError: None != 'bulk_team_operations'`)
- without it: **Ran 28, OK**

Consequence: **there is no Phase 1/Phase 2 split.** No existing flag suppresses subscriber
dispatch without also suppressing emission, so holding that boundary would require adding a
new test-only flag to production code in `subscriber_utils.py` and `chapter_subscribers.py`.
That was judged not worth it, because the four modules that directly exercise the subscriber
path all pass with dispatch restored (`test_member_events_coverage` 29 OK,
`test_subscriber_utils_coverage` 8 OK, `test_chapter_subscribers` 38 OK,
`test_team_events_coverage` 28 OK). Event dispatch now runs in tests.

## Measured blast radius

**This measurement does not bound the implemented change and should not be cited as if it
does.** It was taken on a configuration that differs from what shipped.

32 modules, stratified across 16 subsystems, on `test_site_1` with `in_import` unset and
`throttle_user_limit` raised:

- 29 clean
- 2 false alarms — `test_email_newsletter_system` fails identically with the flag **on**;
  `test_enhanced_sepa_integration` produces no summary either way. Both pre-existing.
- 1 caused by the flip — `test_bulk_account_creation`: 36.5s/OK becomes 290s with 5 failures

One failure in 32 is a point estimate with a 95% confidence interval of roughly 0.1%–16%,
i.e. **≈1–105 modules** on a 658 denominator. It cannot support a "~20 modules" planning
figure or a stop-condition. The 658 is the number of entries in
`verenigingen/tests/test_timings.json`, not a file count; `find verenigingen -name "test_*.py"`
returns 1308.

**No performance claim is made.** Revision 1 asserted "there is no performance argument for
keeping the flag" on the basis of one A/B pair where the flag-off run was *faster*
(197s vs 219s). A negative delta on a single 200s module is noise. Establishing a suite-wide
figure needs repeated runs; until then, neither direction is claimed.

## Verification

1. **Two failing tests first** — done, in `verenigingen/tests/test_harness_production_fidelity.py`.
   Confirmed RED before the change: defaults absent, `ValidationError not raised`,
   `user.enabled` was `None`. The Select precondition held, so the design premise was sound.
2. A fourth test pins the throttle bypass itself. **This test needs its site-independent
   assertion**: `sites/test_site_1..4/site_config.json` already set
   `throttle_user_limit: 100000`, so the behavioral no-throw assertion passes on those sites
   even with the `setUp` override deleted. CI (`.github/helper/db/mariadb.json`) sets no
   limit, so CI is the only environment where the substitute is load-bearing. Proven to bite
   by temporarily disabling the override: `AssertionError: 100000 not >= 1000000`.
3. Full-suite run to enumerate real fallout. Pending.
4. Fix fallout module by module. `test_bulk_account_creation` is the one known casualty.

## Risks

- **`developer_mode` export hazard (local only).** `sites/test_site_1..5/site_config.json`
  all set `developer_mode = 1`, so inserting a standard Report / Notification / Web Form /
  Print Format / Page in a test now writes JSON and boilerplate **into the app source tree**.
  No current test creates such a doc — latent, not active. CI leaves `developer_mode` unset.
- **`assignment_rule.update_due_date` now runs on every save** (hooked on `"*"` `on_update`).
- **Autoname:** explicitly-set `name` on autonamed DocTypes is now discarded (above).
- **Threads.** A new thread gets a fresh `frappe.local`, so `local.conf` is re-read from disk
  and the raise is lost. This is a wash rather than a regression: `frappe.flags` lived in the
  same `frappe.local` and never propagated either.
- **`test_bulk_account_creation` is diagnosed only provisionally.** All five failures are
  `(1205, 'Lock wait timeout exceeded')` in `queue_bulk_accounts`, and the test passes in
  isolation in 10.5s, so it is order-dependent accumulated state — plausibly the
  `ThreadPoolExecutor` in `process_bulk_account_creation_batch`
  (`account_creation_api.py:596`, executor at `:738`) opening its own `frappe.connect()`
  connections once real background queuing is no longer suppressed. Not chased to ground.
- **Unproven lead:** one run of `verenigingen.verenigingen.doctype.team.test_team_coverage`
  hit `(1305, 'SAVEPOINT ... does not exist')` in `create_customer_for_member`; it did not
  reproduce and baseline was clean. Same class as the above. Watch for it in the full run.
- **Scope escalation.** Fallout fixes land in the same PR, since the change is not green
  without them. If the full run turns up a large number of modules, stop and report rather
  than silently expanding the change.

## Follow-up, not in this change

**Production has the same conflation.** `account_creation_api.py:52` and `:625`, and
`account_creation_manager.py:657`, set `frappe.flags.in_import = True` in production for the
same throttle reason. Production bulk account creation therefore also runs with defaults,
selects and constants suppressed. It survives only because `_prepare_user_data` passes
`"enabled": 1` explicitly (`account_creation_manager.py:629`). Same fix available; own change.

**Only 10 test files** manually flip `in_import = False` to get production behavior (revision 1
said ~28). They become redundant but harmless; cleaning them up is churn.
