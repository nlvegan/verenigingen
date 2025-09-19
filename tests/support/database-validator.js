/**
 * @fileoverview Database Validator for E2E Testing
 *
 * This module provides comprehensive database validation utilities for
 * verifying that E2E test operations have correctly updated the database
 * with expected records and field values.
 *
 * Features:
 * - Frappe/ERPNext database query integration
 * - DocType field validation against actual schemas
 * - Business rule verification (payment processing, donation lifecycle)
 * - Test data cleanup and isolation
 * - Comprehensive logging and error reporting
 *
 * @module DatabaseValidator
 * @version 1.0.0
 */

class DatabaseValidator {
  constructor(page) {
    this.page = page;
    this.testRecords = new Set(); // Track test records for cleanup

    // DocType field mappings for validation
    this.donationFields = [
      "donor",
      "donor_email",
      "donation_date",
      "amount",
      "mode_of_payment",
      "paid",
      "payment_id",
      "payment_status",
      "bank_reference",
      "status",
      "mollie_customer_id",
      "mollie_subscription_id",
      "mollie_mandate_id",
      "sales_invoice",
      "recurring_frequency",
      "next_collection_date",
    ];

    this.donorFields = [
      "donor_name",
      "donor_email",
      "phone",
      "address_line_1",
      "city",
      "postal_code",
      "country",
      "donor_type",
      "communication_preference",
    ];

    this.paymentEntryFields = [
      "payment_type",
      "party_type",
      "party",
      "paid_amount",
      "received_amount",
      "reference_no",
      "reference_date",
      "mode_of_payment",
      "status",
    ];
  }

  /**
   * Execute Frappe database query via page evaluation
   *
   * @param {string} query - SQL query or Frappe ORM query
   * @param {Object} params - Query parameters
   * @returns {Array} Query results
   */
  async executeQuery(query, params = {}) {
    try {
      const result = await this.page.evaluate(
        async ({ query, params }) => {
          // Execute query through Frappe's API
          const response = await fetch("/api/method/frappe.client.get_list", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Frappe-CSRF-Token": frappe.csrf_token,
            },
            body: JSON.stringify({
              doctype: params.doctype || "Donation",
              fields: params.fields || ["*"],
              filters: params.filters || {},
              limit: params.limit || 100,
              order_by: params.order_by || "modified desc",
            }),
          });

          if (!response.ok) {
            throw new Error(`Database query failed: ${response.statusText}`);
          }

          const data = await response.json();
          return data.message || [];
        },
        { query, params },
      );

      console.log(
        `[DB] Query executed successfully, found ${result.length} records`,
      );
      return result;
    } catch (error) {
      console.error(`[DB] Query execution failed: ${error.message}`);
      throw new Error(`Database query failed: ${error.message}`);
    }
  }

  /**
   * Verify that a donor record exists with expected data
   *
   * @param {Object} criteria - Search criteria for donor
   * @returns {Object|null} Donor record if found
   */
  async verifyDonorExists(criteria) {
    console.log(`[DB] Verifying donor exists: ${JSON.stringify(criteria)}`);

    const filters = {};
    if (criteria.email) filters.donor_email = criteria.email;
    if (criteria.firstName && criteria.lastName) {
      filters.donor_name = [
        "like",
        `%${criteria.firstName}%${criteria.lastName}%`,
      ];
    }

    const donors = await this.executeQuery("donor_list", {
      doctype: "Donor",
      fields: this.donorFields,
      filters: filters,
      limit: 1,
    });

    if (donors.length === 0) {
      console.warn(
        `[DB] No donor found matching criteria: ${JSON.stringify(criteria)}`,
      );
      return null;
    }

    const donor = donors[0];
    console.log(`[DB] Found donor: ${donor.name} (${donor.donor_email})`);

    // Track for cleanup
    this.testRecords.add({ doctype: "Donor", name: donor.name });

    // Validate expected fields
    if (criteria.email && donor.donor_email !== criteria.email) {
      throw new Error(
        `Donor email mismatch: expected ${criteria.email}, got ${donor.donor_email}`,
      );
    }

    return donor;
  }

  /**
   * Verify that a donation record exists with expected data
   *
   * @param {Object} criteria - Search criteria for donation
   * @returns {Object|null} Donation record if found
   */
  async verifyDonationExists(criteria) {
    console.log(`[DB] Verifying donation exists: ${JSON.stringify(criteria)}`);

    const filters = {};
    if (criteria.donorEmail) filters.donor_email = criteria.donorEmail;
    if (criteria.amount) filters.amount = criteria.amount;
    if (criteria.status) filters.status = criteria.status;
    if (criteria.molliePaymentId) filters.payment_id = criteria.molliePaymentId;

    const donations = await this.executeQuery("donation_list", {
      doctype: "Donation",
      fields: this.donationFields,
      filters: filters,
      limit: 1,
    });

    if (donations.length === 0) {
      console.warn(
        `[DB] No donation found matching criteria: ${JSON.stringify(criteria)}`,
      );
      return null;
    }

    const donation = donations[0];
    console.log(
      `[DB] Found donation: ${donation.name} - €${donation.amount} (${donation.status})`,
    );

    // Track for cleanup
    this.testRecords.add({ doctype: "Donation", name: donation.name });

    // Validate critical fields
    this.validateDonationFields(donation, criteria);

    return donation;
  }

  /**
   * Validate donation record fields against criteria
   */
  validateDonationFields(donation, criteria) {
    // Amount validation
    if (
      criteria.amount &&
      parseFloat(donation.amount) !== parseFloat(criteria.amount)
    ) {
      throw new Error(
        `Donation amount mismatch: expected ${criteria.amount}, got ${donation.amount}`,
      );
    }

    // Status validation
    if (criteria.status && donation.status !== criteria.status) {
      throw new Error(
        `Donation status mismatch: expected ${criteria.status}, got ${donation.status}`,
      );
    }

    // Mollie field validation
    if (criteria.requiresMollie) {
      if (!donation.mollie_customer_id) {
        throw new Error("Missing required Mollie Customer ID");
      }
      if (donation.status === "Recurring" && !donation.mollie_subscription_id) {
        throw new Error(
          "Missing required Mollie Subscription ID for recurring donation",
        );
      }
    }

    console.log("[DB] Donation field validation passed");
  }

  /**
   * Verify that a payment entry exists for the donation
   *
   * @param {Object} criteria - Search criteria for payment entry
   * @returns {Object|null} Payment Entry record if found
   */
  async verifyPaymentEntryExists(criteria) {
    console.log(
      `[DB] Verifying payment entry exists: ${JSON.stringify(criteria)}`,
    );

    const filters = {};
    if (criteria.paidAmount) filters.paid_amount = criteria.paidAmount;
    if (criteria.reference) filters.reference_no = criteria.reference;
    if (criteria.party) filters.party = criteria.party;

    const paymentEntries = await this.executeQuery("payment_entry_list", {
      doctype: "Payment Entry",
      fields: this.paymentEntryFields,
      filters: filters,
      limit: 1,
    });

    if (paymentEntries.length === 0) {
      console.warn(
        `[DB] No payment entry found matching criteria: ${JSON.stringify(criteria)}`,
      );
      return null;
    }

    const paymentEntry = paymentEntries[0];
    console.log(
      `[DB] Found payment entry: ${paymentEntry.name} - €${paymentEntry.paid_amount}`,
    );

    // Track for cleanup
    this.testRecords.add({ doctype: "Payment Entry", name: paymentEntry.name });

    // Validate payment entry fields
    if (
      criteria.paidAmount &&
      parseFloat(paymentEntry.paid_amount) !== parseFloat(criteria.paidAmount)
    ) {
      throw new Error(
        `Payment amount mismatch: expected ${criteria.paidAmount}, got ${paymentEntry.paid_amount}`,
      );
    }

    return paymentEntry;
  }

  /**
   * Verify payment history record exists
   *
   * @param {Object} criteria - Search criteria for payment history
   * @returns {Object|null} Payment History record if found
   */
  async verifyPaymentHistoryExists(criteria) {
    console.log(
      `[DB] Verifying payment history exists: ${JSON.stringify(criteria)}`,
    );

    const filters = {};
    if (criteria.donorName) filters.member = criteria.donorName;
    if (criteria.amount) filters.amount = criteria.amount;
    if (criteria.paymentMethod) filters.payment_method = criteria.paymentMethod;

    const paymentHistory = await this.executeQuery("payment_history_list", {
      doctype: "Member Payment History",
      fields: ["name", "amount"],
      filters: filters,
      limit: 1,
    });

    if (paymentHistory.length === 0) {
      console.warn(
        `[DB] No payment history found matching criteria: ${JSON.stringify(criteria)}`,
      );
      return null;
    }

    const history = paymentHistory[0];
    console.log(
      `[DB] Found payment history: ${history.name} - €${history.amount}`,
    );

    // Track for cleanup
    this.testRecords.add({
      doctype: "Member Payment History",
      name: history.name,
    });

    return history;
  }

  /**
   * Verify webhook processing log exists
   *
   * @param {Object} criteria - Search criteria for webhook log
   * @returns {Object|null} Webhook Processing Log record if found
   */
  async verifyWebhookProcessingLogExists(criteria) {
    console.log(
      `[DB] Verifying webhook processing log exists: ${JSON.stringify(criteria)}`,
    );

    const filters = {};
    if (criteria.webhookId) filters.webhook_id = criteria.webhookId;
    if (criteria.status) filters.status = criteria.status;

    const logs = await this.executeQuery("webhook_log_list", {
      doctype: "Webhook Processing Log",
      fields: ["name", "status"],
      filters: filters,
      limit: 1,
    });

    if (logs.length === 0) {
      console.warn(
        `[DB] No webhook processing log found matching criteria: ${JSON.stringify(criteria)}`,
      );
      return null;
    }

    const log = logs[0];
    console.log(
      `[DB] Found webhook processing log: ${log.name} (${log.status})`,
    );

    // Track for cleanup
    this.testRecords.add({ doctype: "Webhook Processing Log", name: log.name });

    return log;
  }

  /**
   * Verify sales invoice was created for donation
   *
   * @param {Object} criteria - Search criteria for sales invoice
   * @returns {Object|null} Sales Invoice record if found
   */
  async verifySalesInvoiceExists(criteria) {
    console.log(
      `[DB] Verifying sales invoice exists: ${JSON.stringify(criteria)}`,
    );

    const filters = {};
    if (criteria.customer) filters.customer = criteria.customer;
    if (criteria.grandTotal) filters.grand_total = criteria.grandTotal;
    if (criteria.status) filters.status = criteria.status;

    const invoices = await this.executeQuery("sales_invoice_list", {
      doctype: "Sales Invoice",
      fields: ["name", "grand_total"],
      filters: filters,
      limit: 1,
    });

    if (invoices.length === 0) {
      console.warn(
        `[DB] No sales invoice found matching criteria: ${JSON.stringify(criteria)}`,
      );
      return null;
    }

    const invoice = invoices[0];
    console.log(
      `[DB] Found sales invoice: ${invoice.name} - €${invoice.grand_total}`,
    );

    // Track for cleanup
    this.testRecords.add({ doctype: "Sales Invoice", name: invoice.name });

    return invoice;
  }

  /**
   * Verify complete donation processing chain
   *
   * @param {Object} donationData - Complete donation data to verify
   * @returns {Object} Validation results with all found records
   */
  async verifyCompleteDonationChain(donationData) {
    console.log(`[DB] Verifying complete donation processing chain`);

    const results = {
      donor: null,
      donation: null,
      paymentEntry: null,
      paymentHistory: null,
      salesInvoice: null,
      webhookLog: null,
      validationErrors: [],
    };

    try {
      // Step 1: Verify donor record
      results.donor = await this.verifyDonorExists({
        email: donationData.email,
        firstName: donationData.firstName,
        lastName: donationData.lastName,
      });

      if (!results.donor) {
        results.validationErrors.push("Donor record not found");
      }

      // Step 2: Verify donation record
      results.donation = await this.verifyDonationExists({
        donorEmail: donationData.email,
        amount: donationData.amount,
        status:
          donationData.donationType === "recurring" ? "Recurring" : "One-time",
        requiresMollie: true,
      });

      if (!results.donation) {
        results.validationErrors.push("Donation record not found");
      }

      // Step 3: Verify payment entry (if payment was completed)
      if (donationData.paymentCompleted) {
        results.paymentEntry = await this.verifyPaymentEntryExists({
          paidAmount: donationData.amount,
          reference: donationData.molliePaymentId,
        });

        if (!results.paymentEntry) {
          results.validationErrors.push("Payment Entry record not found");
        }
      }

      // Step 4: Verify payment history
      if (results.donor) {
        results.paymentHistory = await this.verifyPaymentHistoryExists({
          donorName: results.donor.name,
          amount: donationData.amount,
          paymentMethod: "Mollie",
        });

        if (!results.paymentHistory) {
          results.validationErrors.push("Payment History record not found");
        }
      }

      // Step 5: Verify sales invoice
      if (results.donor) {
        results.salesInvoice = await this.verifySalesInvoiceExists({
          customer: results.donor.name,
          grandTotal: donationData.amount,
        });

        if (!results.salesInvoice) {
          results.validationErrors.push("Sales Invoice record not found");
        }
      }

      // Step 6: Verify webhook processing log
      if (donationData.molliePaymentId) {
        results.webhookLog = await this.verifyWebhookProcessingLogExists({
          webhookId: donationData.molliePaymentId,
          status: "processed",
        });

        if (!results.webhookLog) {
          results.validationErrors.push("Webhook Processing Log not found");
        }
      }

      console.log(
        `[DB] Complete donation chain validation completed with ${results.validationErrors.length} errors`,
      );

      return results;
    } catch (error) {
      console.error(
        `[DB] Complete donation chain validation failed: ${error.message}`,
      );
      results.validationErrors.push(error.message);
      return results;
    }
  }

  /**
   * Clean up test records created during testing
   *
   * @param {Array} recordList - Optional specific list of records to clean up
   */
  async cleanupTestRecords(recordList = null) {
    const recordsToCleanup = recordList || Array.from(this.testRecords);

    if (recordsToCleanup.length === 0) {
      console.log("[DB] No test records to clean up");
      return;
    }

    console.log(`[DB] Cleaning up ${recordsToCleanup.length} test records`);

    for (const record of recordsToCleanup) {
      try {
        await this.page.evaluate(async (record) => {
          const response = await fetch("/api/method/frappe.client.delete", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Frappe-CSRF-Token": frappe.csrf_token,
            },
            body: JSON.stringify({
              doctype: record.doctype,
              name: record.name,
            }),
          });

          if (!response.ok) {
            console.warn(
              `Failed to delete ${record.doctype} ${record.name}: ${response.statusText}`,
            );
          }
        }, record);

        console.log(`[DB] Cleaned up ${record.doctype}: ${record.name}`);
      } catch (error) {
        console.warn(
          `[DB] Failed to cleanup ${record.doctype} ${record.name}: ${error.message}`,
        );
      }
    }

    // Clear the tracked records
    this.testRecords.clear();
    console.log("[DB] Test record cleanup completed");
  }

  /**
   * Get database statistics for monitoring test impact
   */
  async getDatabaseStats() {
    try {
      const stats = await this.page.evaluate(async () => {
        const doctypes = [
          "Donor",
          "Donation",
          "Payment Entry",
          "Member Payment History",
        ];
        const results = {};

        for (const doctype of doctypes) {
          const response = await fetch("/api/method/frappe.client.get_count", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Frappe-CSRF-Token": frappe.csrf_token,
            },
            body: JSON.stringify({ doctype }),
          });

          if (response.ok) {
            const data = await response.json();
            results[doctype] = data.message || 0;
          }
        }

        return results;
      });

      console.log("[DB] Database statistics:", stats);
      return stats;
    } catch (error) {
      console.error(`[DB] Failed to get database statistics: ${error.message}`);
      return {};
    }
  }
}

module.exports = { DatabaseValidator };
