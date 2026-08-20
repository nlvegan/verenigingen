# Handoff — 2026-08-14: the fix that was standing next to the bug

Session goal was "merge the open PRs, fix the annual-donation bug I'd flagged, tidy the
stale docs". All three landed. The third turned into something else: a skeptical review
of my fix found that the value I was correcting never reached Mollie at all, and that
the failure mode I had written into the PR description was impossible.

## Landed

| PR | | merge |
|---|---|---|
| #338 | find the dues schedule, and stop downgrading annual to monthly | `16623264` |
| #339 | a recurring charge that actually settles, and delete the demo | `12c71484` |
| #341 | recurring donations ignored the donor's chosen frequency | `3de609ae` |

## The bug under the bug

I opened #341 to fix `donate.html`'s "Annually" button, which emitted
`subscription_interval = "1 year"` — an interval Mollie refuses. The review asked the
question I had not: does that value actually arrive?

It does not. `PublicDonationService.process_mollie_payment`'s recurring branch read
`form_data["recurring_interval"]`. The form posts **`subscription_interval`**.
Repo-wide, `recurring_interval` had **two readers and zero writers** — the two reads in
`public_donation_service.py` (line 210 had the correct `subscription_interval or
recurring_interval` precedence; line 617 did not) and two tests written against the
wrong key, which is exactly why nothing caught it.

**Every recurring Mollie donation from the public form was created as `"1 month"`,
whatever the donor pressed.** Quarterly billed monthly, annual billed monthly, silently.
Reproduced through production code before fixing: `'1 month' != '3 months'`.

So the button was wrong *and* the value was discarded. `"1 year"` never left the server,
which means the 422 I had described in the PR — donor charged once, no subscription —
could not happen on that path. Fixing only the button would have switched on a path that
had never carried a real interval.

The live chain, worth writing down because I guessed it wrong at first:

```
donation_form.js
  -> templates/pages/donate.submit_donation
  -> PublicDonationService.process_mollie_payment
  -> CompletePaymentService.create_recurring_donation_payment
  -> payment metadata -> Mollie
```

`MollieGateway.process_payment` is **not** on it. It serves the `mollie_checkout` guest
endpoint and `PaymentService.create_recurring_first_payment`.

## Mollie's interval grammar, measured

Days, weeks and months only. There is no year unit. Established against the test API,
not the docs:

| candidate | result |
|---|---|
| `1 day` / `7 days` / `14 days` / `1 week` / `2 weeks` | 201 accepted |
| `1 month` / `3 months` / `6 months` / `12 months` | 201 accepted |
| `1 year` / `2 years` | 422 "The interval unit is invalid" |
| `banana` / `0 months` *(controls)* | 422 |

**The first probe was blind and I nearly reported from it.** With no mandate on the
customer, all eleven candidates returned an identical 422 — "no suitable mandates found"
is checked *before* the interval is. Every interval looked equally rejected, including
nonsense. Creating a directdebit mandate first (`consumerAccount: NL55INGB0000000000`,
valid immediately in test mode) is what made the probe discriminate.

This also corrected a claim in my own previous handoff: `7 days` and `14 days` *are*
supported. The docs fix ended up narrower than planned — only the year unit was wrong.

## veg11 is a test instance

Foppe's correction, mid-session, and it invalidated published claims in two PRs. I had
been querying veg11 for blast-radius figures and writing them up as production facts —
"1087 Annual / 563 Quarterly schedules", "all 413 subscribers are Quarterly, so this is
latent", "no Yearly donation rows". The site config corroborates the correction:
`allow_tests: true`, `developer_mode: true`.

Corrected in both places — #341's description rewritten, and a comment on the merged
#338. **There is no production database reachable from this bench, so incidence is
simply unknown.** Argue blast radius from code facts instead: a filter that matches
nothing matches nothing for any population.

Note the update path: `gh pr edit --body` **failed silently** on a Projects-classic
GraphQL deprecation error and left the old body in place. Verify the edit took, or use
the `updatePullRequest` mutation directly.

## What else the review found

All verified independently before acting on them:

- **My guards had removed Error Logs.** `create_error_response` only builds a dict, and
  the caller catches only *raised* exceptions — so my early return was quieter than the
  422 it replaced. Both guards now log first.
- **`CompletePaymentService._is_valid_interval` already implemented this grammar**, and
  differed from mine (it accepted `"0 months"` and `"-1 months"`). Two grammars for one
  API is the shape of defect this whole change was about; it now delegates.
- **Three comments/docstrings claimed more than the code did** — including citing
  `tests/contracts/mollie-contracts.json` as the authority for the grammar when nothing
  loads that file.
- It also established the new tests were *meaningful* with controls rather than by
  reading: re-binding the guards to no-ops turned all three red, and repointing the
  template test at develop's markup turned it red too.

## Open, not addressed

Reported by the review, **not independently verified by me** — worth confirming before
acting:

1. **`mollie_subscription_webhook` may be unreachable for a donation first payment.** It
   is `@frappe.whitelist()` *without* `allow_guest=True` (Mollie posts unauthenticated),
   and returns `{"status": "ignored"}` unless a Customer already carries the incoming
   subscription id. If true, the two `_activate_*_after_first_payment` helpers never fire
   for the flow they exist to serve, and the guards I added there buy nothing yet.
2. **`PaymentService.create_recurring_first_payment` has no production caller** — only
   `mollie/tests/mollie_integration_check.py`.

Verified by me, low priority:

3. `Mollie Settings.default_subscription_interval` **has no readers** anywhere. Its
   Select is corrected but the field is decorative.
4. `tests/contracts/mollie-contracts.json` is loaded by nothing. It documents; it
   enforces nothing.

Pre-existing and still open: **#289** (no Weekly branch → Weekly billed monthly;
`Semi-Annual` unhandled in `dues_schedule_health_manager.py`).

## Deploy note

The working tree is on `3de609ae`, so the code is live. One thing the pull does not do:
`mollie_settings.json`'s Select options changed, and the DocType meta on veg11 still
carries the old list until someone runs

```bash
bench --site veg11.veganisme.org migrate     # or reload-doctype "Mollie Settings"
```

Harmless either way — the field has no readers — but the old `1 year` option stays
selectable in the UI until then. No asset build is needed: `donation_form.js` is served
straight from `/assets/verenigingen/js/`, not bundled.

## The lesson worth keeping

I fixed a value at its producer, guarded the two places it was consumed, and wrote a
test that **parses the HTML template with regexes**. That test was green while the value
was being thrown away one function later, and a template test can never see it.

When fixing "value X is wrong at the producer", trace X to its consumer and assert it
arrives. One end-to-end test is worth more than any number of tests on either end. And a
string key crossing a module boundary has no compiler — grep it repo-wide and check it
has a *producer*, not just readers. Two readers and zero writers is the signature.

CI, the validators, and I all passed this. The review agent did not.
