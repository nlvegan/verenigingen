# ANBI Agreement Confirmation Receipts — Design (C1)

**Date:** 2026-07-10
**Audit finding:** C1 (ANBI tax receipts) in `docs/audits/2026-07-10-todo-unfinished-features-audit.md`
**Status:** Approved design, pending implementation plan

## Problem

`verenigingen/api/periodic_donation_operations.py::generate_tax_receipts()` is a
fake-success stub. For each active ANBI-eligible Periodic Donation Agreement it:

1. Calls `generate_tax_receipt_content(agreement)` — which returns a placeholder
   string — and **discards the return value**.
2. Adds a "Tax receipt generated" comment to the agreement.
3. Increments `generated_count` and reports `"N tax receipts generated"`.

No receipt is ever produced, saved, attached, or emailed. It is a live
`@frappe.whitelist()` + `@critical_api(FINANCIAL)` endpoint → a real ANBI
compliance gap (claims success while doing nothing).

**Second, independent defect:** the report button that is supposed to invoke this
feature is mis-wired. `verenigingen/verenigingen/report/anbi_periodic_agreements/
anbi_periodic_agreements.js:188` calls
`verenigingen.api.anbi_operations.generate_tax_receipts`, but that function does
**not exist** in `anbi_operations.py`. The button therefore fails with "Method
Not Found" — the real (stub) endpoint lives in `periodic_donation_operations`.

## Scope decisions (agreed)

- **Receipt type:** *Agreement confirmation receipt* — a static per-agreement
  confirmation, NOT an annual tax-year statement of amounts actually received.
  Content is derived from the agreement + donor + issuing org, not from summing
  linked donations.
- **Delivery:** *Save PDF to the agreement only.* Render → PDF → attach as a
  **private File** to the Periodic Donation Agreement. **No automatic email**
  (the button generates for all active ANBI agreements at once; bulk email is
  out of scope and higher blast-radius).
- **Idempotency:** *Replace.* Exactly one current receipt per agreement. On
  re-run, delete any existing receipt File for that agreement and attach a fresh
  one. Safe to re-run.
- **Org RSIN:** Include the issuing organization's RSIN (from the linked
  Company's `tax_id`) on the receipt **only if present**; otherwise omit that
  line. Never block receipt generation on a missing org RSIN.

## Design

### Behavior of `generate_tax_receipts(filters)`

For each **Active** + **`anbi_eligible`** Periodic Donation Agreement:

1. **Render** confirmation-receipt HTML via `frappe.render_template` against a
   new Jinja template. Content:
   - Issuing org: `company_name` from Verenigingen Settings; org RSIN from the
     linked Company's `tax_id` if set.
   - Donor: `donor_name`, `address` (from the Donor doc).
   - Agreement: `agreement_number`, `annual_amount`, `agreement_type`,
     `start_date`/`end_date`.
   - Issue date (`today()`).
   - Deductibility statement (ANBI periodic-gift full deductibility).
   - All user-facing strings wrapped in `_()`.
2. **Convert** to PDF via `frappe.utils.pdf.get_pdf(html)`.
3. **Attach** as a private File to the agreement:
   `attached_to_doctype="Periodic Donation Agreement"`,
   `attached_to_name=agreement.name`, `is_private=1`, deterministic
   `file_name=f"ANBI_Tax_Receipt_{agreement_number}.pdf"`.
4. **Idempotent replace:** before attaching, query for an existing File with that
   `file_name` attached to the agreement; if found, delete it first.
5. **Audit comment** ("Tax receipt generated for <date>") is added **only after**
   the File is successfully saved.
6. `generated_count` increments **only on real success**. Per-agreement
   exceptions are logged (as today) and collected into the returned result;
   they do NOT count as generated.

Return shape stays `OperationResult.ok({"generated_count": N, "failed": [...]})`
so existing callers/tests keep working; message unchanged
(`"{0} tax receipts generated"`).

### Base filter

Keep the existing hardcoded selection `{"status": "Active", "anbi_eligible": 1}`
— only active, ANBI-eligible agreements receive a receipt (correct). Extra
report filters passed in are not required for this pass; the `filters` arg is
still parsed (JSON-string tolerant) for API compatibility.

### Renderer helper

Replace `generate_tax_receipt_content()` (placeholder) with a real helper that
builds the render context and returns rendered HTML (kept as a separate,
unit-testable function). PDF conversion + File attach live in the endpoint (or a
small private helper) so the HTML builder stays pure and testable.

### Template

New `verenigingen/templates/donation/anbi_tax_receipt.html` — self-contained
Jinja (inline styles; no external assets). Chosen over a Frappe Print Format so
the compliance text stays in version control, translatable and unit-testable,
with no dependency on admin-configured Print Format fixtures.

### Fix the broken button

`anbi_periodic_agreements.js:188` → change method to
`verenigingen.api.periodic_donation_operations.generate_tax_receipts`. One line.
(Endpoint stays where its working siblings already live.)

## Files touched

| File | Change |
|------|--------|
| `verenigingen/api/periodic_donation_operations.py` | Real `generate_tax_receipts` + HTML renderer helper; drop placeholder |
| `verenigingen/templates/donation/anbi_tax_receipt.html` | **New** receipt Jinja template |
| `verenigingen/verenigingen/report/anbi_periodic_agreements/anbi_periodic_agreements.js` | One-line method path fix |
| `verenigingen/tests/api/test_periodic_donation_operations.py` | Replace 3 stub-pinning receipt tests with real-DB mutation-verified tests |

## Testing

Real-DB, mutation-verified (mirror existing test file conventions; run on
`test_site_2`, not veg11):

- Active + ANBI-eligible agreement → a File named `ANBI_Tax_Receipt_<num>.pdf` is
  attached to that agreement; its content is non-empty PDF bytes.
- Rendered HTML (via the pure helper) contains the agreement number and donor
  name and the deductibility statement.
- **Idempotent replace:** running twice leaves exactly ONE receipt File attached
  (not two).
- **Selection:** inactive agreement and non-`anbi_eligible` agreement receive NO
  receipt File; `generated_count` reflects only eligible ones.
- `generated_count` counts only real successes.

## Known risk

PDF rendering depends on wkhtmltopdf (same dependency the existing
`api/payment_dashboard.py` PDF path already relies on). Verify availability early
in implementation. If unavailable in the dev/test env, fall back to attaching the
rendered HTML (still closes the "nothing is produced/saved" gap) and note it.

## Out of scope

- Annual tax-year donation statements (amounts actually received per year).
- Emailing receipts to donors.
- The A1 "Generate PDF" agreement-form stub (`periodic_donation_agreement.js`) —
  a separate finding for the agreement document itself, not the receipt.
- Admin-editable Print Format.
