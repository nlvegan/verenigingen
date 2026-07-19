"""
SEPA sequence-type (SeqTp) compliance tests.

Covers two banking-compliance bugs in the SEPA Direct Debit pipeline:

BUG 1 -- pain.008 XML cannot represent a mixed FRST/RCUR batch.
    The adapter (``SEPAXMLAdapter.generate_xml_for_batch``) built ONE
    ``SEPAPaymentInfo`` for the whole batch, with the batch-level SeqTp, while
    ``_build_transaction`` set EACH transaction's own ``sequence_type`` from the
    per-row value. The enhanced generator enforces SeqTp homogeneity per PmtInf
    (``_validate_sequence_type_consistency``), so a batch mixing a FRST row and
    an RCUR row crashed XML generation. The EPC scheme requires one PmtInf per
    sequence type. The adapter now GROUPS transactions by sequence_type and emits
    one PmtInf per group.

    A single-sequence batch must still produce exactly ONE PmtInf with the
    ORIGINAL (un-suffixed) payment_info_id so existing batches / duplicate-upload
    detection stay byte-stable.

BUG 2 -- mandate usage never advances FRST -> RCUR.
    ``SEPAMandateUsage.mark_as_collected`` was never called in live code, so
    every usage row stayed "Pending" and ``get_mandate_sequence_type`` returned
    FRST forever. The confirmed-collection path
    (``BatchProcessingService.mark_batch_invoices_as_paid``) now marks the
    invoice's Pending usage row "Collected", so the NEXT collection is RCUR.
    The failure/returns branch must NOT mark Collected (a returned FRST stays
    FRST).

Real-DB integration tests (no mocks). Submitted batches / payment entries commit
past the FrappeTestCase rollback, so committed docs are tracked and force-deleted.
"""

import xml.etree.ElementTree as ET
from decimal import Decimal

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
    create_mandate_usage_record,
    get_mandate_sequence_type,
)
from verenigingen.verenigingen_payments.services.batch_processing_service import (
    batch_processing_service,
)
from verenigingen.verenigingen_payments.services.sepa_xml_generation_service import (
    SEPAXMLGenerationService,
)

NS = "urn:iso:std:iso:20022:tech:xsd:pain.008.001.08"


def _q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


class _SEPASeqBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eur_company = get_eur_test_company()
        cls._setup_sepa_settings()

    @classmethod
    def _setup_sepa_settings(cls):
        """Point Verenigingen Settings at a SEPA-clean EUR company so the creditor
        / initiating-party names pass the pain.008 character-set validation, and
        ensure valid IBAN/BIC/creditor credentials are present.

        The default test company name (``_Test Company``) contains an underscore,
        which the SEPA character set forbids -- so the live XML path would fail
        creditor-name validation. This is environment config, not part of the bug
        under test."""
        settings = frappe.get_single("Verenigingen Settings")
        if settings.company != cls.eur_company:
            settings.company = cls.eur_company
            settings.save(ignore_permissions=True)
        from verenigingen.utils.settings_utils import get_payments_settings

        ps = get_payments_settings()
        changed = False
        if not ps.get("company_iban"):
            ps.company_iban = "NL91ABNA0417164300"
            changed = True
        if not ps.get("company_bic"):
            ps.company_bic = "ABNANL2A"
            changed = True
        if not ps.get("creditor_id"):
            ps.creditor_id = "NL12ZZZ123456789"
            changed = True
        if changed:
            ps.save(ignore_permissions=True)
        frappe.db.commit()
        # Drop any cached settings so the adapter re-reads the SEPA-clean company.
        from verenigingen.verenigingen_payments.services.sepa_configuration_service import (
            sepa_config_service,
        )

        sepa_config_service.get_sepa_settings(force_refresh=True)

    def setUp(self):
        super().setUp()
        self._sepa = SEPATestDataFactory(seed=9001, use_faker=True)
        self._committed = []
        # Submitting dated invoices triggers eBoekhouden's benign FY auto-create
        # log on the shared test DB (a known test-artifact, not a SEPA bug).
        self.expectErrorLog("Fiscal Year Auto-Creation Error")

    def tearDown(self):
        for doctype, name in reversed(self._committed):
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _track(self, doctype, name):
        self._committed.append((doctype, name))


class TestMixedSequenceBatchXML(_SEPASeqBase):
    """BUG 1: a batch with both FRST and RCUR rows must generate valid XML with
    one PmtInf per sequence type."""

    def _read_generated_xml(self, file_url: str) -> str:
        """Read the XML content the live generation service wrote to a File."""
        file_doc = frappe.get_doc("File", {"file_url": file_url})
        self._track("File", file_doc.name)
        content = file_doc.get_content()
        return content.decode("utf-8") if isinstance(content, bytes) else content

    def _seed_collected_usage(self, mandate_name, amount):
        """Seed a prior Collected usage row so get_mandate_sequence_type returns
        RCUR for this mandate -- i.e. this is a legitimately-recurring mandate.

        The batch's own validate_sequence_types() rejects RCUR-on-first-use, so a
        genuine mixed batch needs at least one mandate with prior collections."""
        usage_name = create_mandate_usage_record(
            mandate_name=mandate_name,
            reference_doctype="Sales Invoice",
            reference_name=f"PRIOR-{frappe.generate_hash(length=8)}",
            amount=amount,
            sequence_type="FRST",
        )
        usage = frappe.get_doc("SEPA Mandate", mandate_name)
        for row in usage.usage_history:
            if row.name == usage_name:
                row.db_set("status", "Collected", update_modified=False)
                row.db_set("processing_date", today(), update_modified=False)
                break

    def _batch_with_sequence_types(self, seq_types):
        """Build a draft Direct Debit Batch whose i-th invoice row carries
        seq_types[i] as its sequence_type (and a matching mandate). RCUR rows get
        a mandate with a prior Collected usage so the batch's own validation
        (which forbids RCUR-on-first-use) accepts them."""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.update(
            {
                "batch_date": today(),
                "batch_description": f"SeqMix {self._sepa.get_next_sequence('batch')}",
                "currency": "EUR",
                "status": "Draft",
                "batch_type": "CORE",
                # Batch-level SeqTp is now only a fallback; per-row values drive
                # the grouping. Use RCUR as the (legacy) batch default.
                "sequence_type": "RCUR",
            }
        )

        total = 0.0
        for i, seq in enumerate(seq_types):
            member = self._sepa.create_test_member(first_name=f"SeqMix{i}")
            customer = self._sepa.create_test_customer(customer_name=f"Cust {member.full_name}")
            member.db_set("customer", customer.name)
            mandate = self._sepa.create_test_sepa_mandate(member=member.name)
            if seq == "RCUR":
                self._seed_collected_usage(mandate.name, 25.0 + (i * 5))
            membership = self._sepa.create_test_membership(member=member.name)
            invoice = self._sepa.create_test_sales_invoice(
                customer=customer.name, member=member.name, membership=membership.name, submit=True
            )
            amount = 25.0 + (i * 5)
            batch.append(
                "invoices",
                {
                    "invoice": invoice.name,
                    "membership": membership.name,
                    "member": member.name,
                    "member_name": member.full_name,
                    "amount": amount,
                    "currency": "EUR",
                    "iban": mandate.iban,
                    "mandate_reference": mandate.mandate_id,
                    "status": "Pending",
                    "sequence_type": seq,
                },
            )
            total += amount

        batch.total_amount = total
        batch.entry_count = len(seq_types)
        batch.insert()
        self._track("Direct Debit Batch", batch.name)
        return batch

    def test_mixed_frst_rcur_batch_generates_two_pmtinf(self):
        # One FRST row, one RCUR row in the same batch.
        batch = self._batch_with_sequence_types(["FRST", "RCUR"])

        service = SEPAXMLGenerationService()
        # Must NOT raise (previously crashed on SeqTp consistency validation).
        # The live service writes the XML to a File and returns its URL.
        with self.assertNoErrorLog(ignore=["Fiscal Year Auto-Creation Error"]):
            file_url = service.generate_sepa_xml_for_batch(batch)

        xml_string = self._read_generated_xml(file_url)
        root = ET.fromstring(xml_string)
        pmt_infs = root.findall(f".//{_q('PmtInf')}")
        self.assertEqual(len(pmt_infs), 2, "A mixed FRST/RCUR batch must emit exactly two PmtInf blocks")

        # Map SeqTp -> PmtInf for assertions.
        by_seq = {}
        for pi in pmt_infs:
            seqtp = pi.find(f".//{_q('SeqTp')}")
            self.assertIsNotNone(seqtp, "Each PmtInf must carry a SeqTp")
            by_seq[seqtp.text] = pi

        self.assertIn("FRST", by_seq, "One PmtInf must be FRST")
        self.assertIn("RCUR", by_seq, "One PmtInf must be RCUR")

        # Each PmtInf's NbOfTxs / CtrlSum reflect its OWN group (one txn each).
        for seqtp, expected_amount in (("FRST", Decimal("25.00")), ("RCUR", Decimal("30.00"))):
            pi = by_seq[seqtp]
            nb = pi.find(f"{_q('NbOfTxs')}")
            ctrl = pi.find(f"{_q('CtrlSum')}")
            self.assertEqual(nb.text, "1", f"{seqtp} PmtInf should have 1 transaction")
            self.assertEqual(Decimal(ctrl.text), expected_amount, f"{seqtp} CtrlSum should match its row")
            txns = pi.findall(f".//{_q('DrctDbtTxInf')}")
            self.assertEqual(len(txns), 1, f"{seqtp} PmtInf should contain exactly its own transaction")

        # Message-level totals equal the sum across groups.
        grp_nb = root.find(f".//{_q('GrpHdr')}/{_q('NbOfTxs')}")
        grp_ctrl = root.find(f".//{_q('GrpHdr')}/{_q('CtrlSum')}")
        self.assertEqual(grp_nb.text, "2", "Group header NbOfTxs must equal total transactions")
        self.assertEqual(
            Decimal(grp_ctrl.text), Decimal("55.00"), "Group header CtrlSum must equal grand total"
        )

        # The two PmtInf must have DISTINCT ids (homogeneous-per-PmtInf scheme).
        ids = [pi.find(f"{_q('PmtInfId')}").text for pi in pmt_infs]
        self.assertEqual(len(set(ids)), 2, "Each PmtInf must have a unique PmtInfId")

    def test_single_sequence_batch_keeps_original_payment_info_id(self):
        # All-RCUR batch -> exactly ONE PmtInf with the un-suffixed id.
        batch = self._batch_with_sequence_types(["RCUR", "RCUR"])

        from verenigingen.verenigingen_payments.services.sepa_xml_adapter import get_sepa_xml_adapter

        adapter = get_sepa_xml_adapter()
        adapter.clear_cache()
        xml_string = adapter.generate_xml_for_batch(
            batch_doc=batch,
            message_id="MSG-SINGLE-SEQ",
            payment_info_id="PMT-SINGLE-SEQ",
        )

        root = ET.fromstring(xml_string)
        pmt_infs = root.findall(f".//{_q('PmtInf')}")
        self.assertEqual(len(pmt_infs), 1, "A single-sequence batch must emit exactly one PmtInf")

        # Byte-stable behaviour: the original payment_info_id is unchanged (no
        # -RCUR suffix) for single-group batches.
        self.assertEqual(
            pmt_infs[0].find(f"{_q('PmtInfId')}").text,
            "PMT-SINGLE-SEQ",
            "Single-group batches must preserve the original (un-suffixed) PmtInfId",
        )
        seqtp = pmt_infs[0].find(f".//{_q('SeqTp')}")
        self.assertEqual(seqtp.text, "RCUR")

    def test_multigroup_payment_info_ids_stay_within_sepa_length_limit(self):
        # A long base id + a mixed batch must not push the suffixed multi-group
        # PmtInfId past the SEPA 35-char limit, which would crash XML generation
        # in the generator's length check. The base is truncated as needed while
        # each group's 1-char suffix keeps the ids unique.
        from verenigingen.verenigingen_payments.services.sepa_xml_adapter import get_sepa_xml_adapter
        from verenigingen.verenigingen_payments.utils.sepa_constants import MAX_PAYMENT_INFO_ID_LENGTH

        batch = self._batch_with_sequence_types(["FRST", "RCUR"])
        long_id = "PMT-" + "X" * 40  # over the 35-char limit even before suffixing

        adapter = get_sepa_xml_adapter()
        adapter.clear_cache()
        xml_string = adapter.generate_xml_for_batch(
            batch_doc=batch, message_id="MSG-LONG-ID", payment_info_id=long_id
        )

        root = ET.fromstring(xml_string)
        ids = [pi.find(f"{_q('PmtInfId')}").text for pi in root.findall(f".//{_q('PmtInf')}")]
        self.assertEqual(len(ids), 2)
        for pi_id in ids:
            self.assertLessEqual(
                len(pi_id),
                MAX_PAYMENT_INFO_ID_LENGTH,
                f"PmtInfId {pi_id!r} exceeds the SEPA {MAX_PAYMENT_INFO_ID_LENGTH}-char limit",
            )
        self.assertEqual(len(set(ids)), 2, "Suffixed ids must stay unique even after truncation")


class TestMandateUsageLifecycle(_SEPASeqBase):
    """BUG 2: a confirmed collection advances the mandate FRST -> RCUR; a
    returned/failed collection does not."""

    def _submitted_batch(self, invoice_count=1):
        batch = self._sepa.create_test_direct_debit_batch(invoice_count=invoice_count)
        self._track("Direct Debit Batch", batch.name)
        batch.sepa_file_generated = 1
        batch.save()
        batch.submit()
        return batch

    def _pending_usage_for_invoice(self, mandate_name, invoice_name, amount):
        """Create a Pending SEPA Mandate Usage row linking the mandate to the invoice."""
        return create_mandate_usage_record(
            mandate_name=mandate_name,
            reference_doctype="Sales Invoice",
            reference_name=invoice_name,
            amount=amount,
        )

    def test_confirmed_collection_marks_usage_collected_and_next_is_rcur(self):
        batch = self._submitted_batch(invoice_count=1)
        row = batch.invoices[0]

        # The batch row references a mandate (by mandate_id) and an invoice.
        mandate_name = frappe.db.get_value("SEPA Mandate", {"mandate_id": row.mandate_reference}, "name")
        self.assertTrue(mandate_name, "Test batch row must reference a real mandate")

        # Seed a Pending usage row for this invoice.
        self._pending_usage_for_invoice(mandate_name, row.invoice, row.amount)

        # Before collection: no Collected row -> FRST.
        before = get_mandate_sequence_type(mandate_name)
        self.assertEqual(before["sequence_type"], "FRST", "First collection must be FRST")

        usage_name = frappe.db.get_value(
            "SEPA Mandate Usage",
            {"reference_name": row.invoice, "status": "Pending"},
            "name",
        )
        self.assertTrue(usage_name, "A Pending usage row should exist before collection")

        # Confirmed collection (the live "Process Payments" path).
        batch_processing_service.mark_batch_invoices_as_paid(batch)

        # The usage row is now Collected with a processing_date.
        usage = frappe.db.get_value(
            "SEPA Mandate Usage", usage_name, ["status", "processing_date"], as_dict=True
        )
        self.assertEqual(usage.status, "Collected", "A confirmed collection must mark the usage Collected")
        self.assertEqual(str(usage.processing_date), str(today()))

        # The NEXT collection for this mandate is therefore RCUR.
        after = get_mandate_sequence_type(mandate_name)
        self.assertEqual(after["sequence_type"], "RCUR", "After a confirmed collection the next must be RCUR")

    def test_failed_collection_does_not_mark_usage_collected(self):
        # Use a mandate whose invoice payment will FAIL: point the batch row at a
        # nonexistent invoice so _create_payment_entry_for_invoice raises and the
        # failure branch runs (the row is marked Failed, NOT paid).
        batch = self._submitted_batch(invoice_count=1)
        row = batch.invoices[0]
        mandate_name = frappe.db.get_value("SEPA Mandate", {"mandate_id": row.mandate_reference}, "name")

        # Seed a Pending usage row referencing the REAL invoice...
        self._pending_usage_for_invoice(mandate_name, row.invoice, row.amount)
        usage_name = frappe.db.get_value(
            "SEPA Mandate Usage", {"reference_name": row.invoice, "status": "Pending"}, "name"
        )

        # ...but break the collection: repoint the batch row at a missing invoice
        # so the per-invoice handler hits the failure branch.
        row.db_set("invoice", "SINV-DOES-NOT-EXIST", update_modified=False)
        batch.reload()

        # The failure branch logs an error per invoice; tolerate it.
        self.expectErrorLog("SEPA Direct Debit Payment Error")
        batch_processing_service.mark_batch_invoices_as_paid(batch)

        # The usage row must STILL be Pending (a non-collected attempt must not
        # advance FRST -> RCUR).
        self.assertEqual(
            frappe.db.get_value("SEPA Mandate Usage", usage_name, "status"),
            "Pending",
            "A failed collection must NOT mark the usage Collected",
        )
        self.assertEqual(
            get_mandate_sequence_type(mandate_name)["sequence_type"],
            "FRST",
            "After a failed collection the next collection must still be FRST",
        )


class TestSequenceTypeDerivationBranches(_SEPASeqBase):
    """Behavioral coverage for the FRST/RCUR derivation branches that are NOT
    exercised by the base FRST->RCUR happy path (TestMandateUsageLifecycle) nor by
    the mixed-batch XML tests.

    Branches under test (SEPAMandateUsage.determine_sequence_type /
    get_mandate_sequence_type):
      - RENEWAL RESET: prior Collected usage exists BUT mandate.sign_date is later
        than the last usage -> FRST ("Mandate was renewed after last usage").
      - PENDING-ONLY: prior usage rows exist but none are Collected -> still FRST
        (the history filter is status == "Collected").
      - CHILD HOOK -> RCUR: the child-table determine_sequence_type() (not the API)
        must derive RCUR when a genuine prior Collected usage exists.
      - BATCH VALIDATION: a real new-mandate batch declaring RCUR-on-first-use must
        be flagged Critical by DirectDebitBatch.validate_sequence_types().

    All rows whose sequence_type is under assertion are DERIVED by production code
    (sequence_type left unset); prior seed rows only set status/dates, never the
    derived value under test.
    """

    def _seed_collected_usage(self, mandate_name, amount, usage_date):
        """Seed a prior COLLECTED usage row dated `usage_date`.

        The row is created through production `create_mandate_usage_record` (its own
        sequence_type is derived, not asserted), then transitioned to Collected and
        back-dated so the renewal / recurring rules have real history to read."""
        usage_name = create_mandate_usage_record(
            mandate_name=mandate_name,
            reference_doctype="Sales Invoice",
            reference_name=f"PRIOR-{frappe.generate_hash(length=8)}",
            amount=amount,
        )
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)
        for row in mandate.usage_history:
            if row.name == usage_name:
                row.db_set("status", "Collected", update_modified=False)
                row.db_set("processing_date", today(), update_modified=False)
                row.db_set("usage_date", usage_date, update_modified=False)
                break
        return usage_name

    def _pending_usage(self, mandate_name, amount):
        """Create a usage row that stays Pending (create_mandate_usage_record never
        marks Collected). Its sequence_type is derived by prod, not asserted here."""
        return create_mandate_usage_record(
            mandate_name=mandate_name,
            reference_doctype="Sales Invoice",
            reference_name=f"PEND-{frappe.generate_hash(length=8)}",
            amount=amount,
        )

    def _derive_via_child_hook(self, mandate_name, amount=10.0):
        """Append a NEW usage row with sequence_type UNSET and return the value the
        child-table hook derived. This exercises SEPAMandateUsage.determine_sequence_type
        (invoked by create_mandate_usage_record when sequence_type is None) -- the
        derivation path, NOT the get_mandate_sequence_type API."""
        usage_name = create_mandate_usage_record(
            mandate_name=mandate_name,
            reference_doctype="Sales Invoice",
            reference_name=f"CHILD-{frappe.generate_hash(length=8)}",
            amount=amount,
        )
        return frappe.db.get_value("SEPA Mandate Usage", usage_name, "sequence_type")

    # ---- S1: RENEWAL RESET (RCUR -> FRST) ------------------------------------

    def test_renewal_after_last_usage_resets_to_frst(self):
        member = self._sepa.create_test_member(first_name="RenewReset")
        # sign_date BEFORE the collection so the mandate is a normal recurring one.
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, sign_date=add_days(today(), -90))
        self._seed_collected_usage(mandate.name, 25.0, usage_date=add_days(today(), -60))

        # Baseline: sign_date (-90) is before the last collection (-60) -> RCUR.
        baseline = get_mandate_sequence_type(mandate.name)
        self.assertEqual(baseline["sequence_type"], "RCUR", "Un-renewed recurring mandate must be RCUR")

        # RENEW: move sign_date to today (after the last usage). The renewal-reset
        # rule must now return FRST with the renewal reason.
        mandate.db_set("sign_date", today(), update_modified=False)

        result = get_mandate_sequence_type(mandate.name)
        self.assertEqual(
            result["sequence_type"], "FRST", "A mandate renewed after its last usage must reset to FRST"
        )
        self.assertEqual(result["reason"], "Mandate was renewed after last usage")

        # The child-table derivation path must reach the same FRST conclusion.
        self.assertEqual(
            self._derive_via_child_hook(mandate.name),
            "FRST",
            "determine_sequence_type() must also reset to FRST after a renewal",
        )

    # ---- S2: PENDING-ONLY HISTORY STAYS FRST ---------------------------------

    def test_pending_usage_never_advances_to_rcur(self):
        member = self._sepa.create_test_member(first_name="PendingOnly")
        mandate = self._sepa.create_test_sepa_mandate(member=member.name)

        # One Pending (never Collected) usage row -> history filter ignores it -> FRST.
        self._pending_usage(mandate.name, 25.0)
        first = get_mandate_sequence_type(mandate.name)
        self.assertEqual(first["sequence_type"], "FRST", "A Pending-only mandate must still be FRST")
        self.assertIn("First usage", first["reason"])

        # A SECOND Pending usage must still not count as prior usage.
        self._pending_usage(mandate.name, 30.0)
        self.assertEqual(
            get_mandate_sequence_type(mandate.name)["sequence_type"],
            "FRST",
            "Multiple Pending usages must not advance the mandate to RCUR",
        )

        # The child-table derivation path agrees (no Collected history -> FRST).
        self.assertEqual(self._derive_via_child_hook(mandate.name), "FRST")

    # ---- S3: CHILD-HOOK DERIVES RCUR DIRECTLY --------------------------------

    def test_child_hook_derives_rcur_for_recurring_mandate(self):
        member = self._sepa.create_test_member(first_name="ChildHookRcur")
        # sign_date well before the collection so no renewal reset applies.
        mandate = self._sepa.create_test_sepa_mandate(member=member.name, sign_date=add_days(today(), -90))
        self._seed_collected_usage(mandate.name, 25.0, usage_date=add_days(today(), -30))

        # A freshly appended usage row with sequence_type UNSET must be DERIVED to
        # RCUR by the child-table hook (this is the RCUR return of
        # SEPAMandateUsage.determine_sequence_type, which the API tests never touch).
        derived = self._derive_via_child_hook(mandate.name)
        self.assertEqual(
            derived,
            "RCUR",
            "determine_sequence_type() must derive RCUR for a mandate with a prior collection",
        )

    # ---- S4: NEW-MANDATE BATCH FLAGS RCUR-ON-FIRST-USE AS CRITICAL ------------

    def test_new_mandate_batch_flags_rcur_first_use_as_critical(self):
        """A real Direct Debit Batch row declaring RCUR for a brand-new mandate must
        be flagged Critical by validate_sequence_types (expected FRST, actual RCUR).

        NOTE: batch generation sets the batch-level sequence_type to RCUR but leaves
        each invoice ROW's sequence_type UNSET, so validate_sequence_types auto-assigns
        the derived FRST per row and never flags a critical error via that entry point.
        This test therefore drives validate_sequence_types directly with an explicit
        (wrong) RCUR row, which is the branch that actually guards SEPA compliance."""
        member = self._sepa.create_test_member(first_name="RcurFirstUse")
        customer = self._sepa.create_test_customer(customer_name=f"Cust {member.full_name}")
        member.db_set("customer", customer.name)
        mandate = self._sepa.create_test_sepa_mandate(member=member.name)  # no prior usage
        membership = self._sepa.create_test_membership(member=member.name)
        invoice = self._sepa.create_test_sales_invoice(
            customer=customer.name, member=member.name, membership=membership.name, submit=True
        )

        batch = frappe.new_doc("Direct Debit Batch")
        batch.update(
            {
                "batch_date": today(),
                "batch_description": f"RcurFirst {self._sepa.get_next_sequence('batch')}",
                "currency": "EUR",
                "status": "Draft",
                "batch_type": "CORE",
                "sequence_type": "RCUR",
            }
        )
        # Automated flag: record the validation result instead of throwing so we can
        # assert on validation_status / validation_errors.
        batch._automated_processing = True
        batch.append(
            "invoices",
            {
                "invoice": invoice.name,
                "membership": membership.name,
                "member": member.name,
                "member_name": member.full_name,
                "amount": 25.0,
                "currency": "EUR",
                "iban": mandate.iban,
                "mandate_reference": mandate.mandate_id,
                "status": "Pending",
                # WRONG: first use of a brand-new mandate must be FRST, not RCUR.
                "sequence_type": "RCUR",
            },
        )
        batch.total_amount = 25.0
        batch.entry_count = 1
        batch.insert()
        self._track("Direct Debit Batch", batch.name)

        self.assertEqual(
            batch.validation_status,
            "Critical Errors",
            "RCUR declared for a first-use mandate must be a Critical validation error",
        )
        errors = frappe.parse_json(batch.validation_errors)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["invoice"], invoice.name)
        self.assertIn("RCUR used for first mandate usage", errors[0]["issue"])
        self.assertEqual(errors[0]["expected"], "FRST")
        self.assertEqual(errors[0]["actual"], "RCUR")
