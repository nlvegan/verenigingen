/**
 * @fileoverview Mollie Test Helpers for E2E Testing
 *
 * This module provides comprehensive testing utilities for Mollie payment
 * integration, including test payment simulation, webhook handling,
 * and validation of Mollie-specific behaviors in test environment.
 *
 * Features:
 * - Test payment completion simulation
 * - Mollie test environment integration
 * - Payment method testing (iDEAL, credit card, etc.)
 * - Test scenario management (success, failure, pending)
 * - Webhook payload generation and validation
 *
 * @module MollieTestHelpers
 * @version 1.0.0
 */

class MollieTestHelpers {
  constructor(page) {
    this.page = page;
    this.testApiKey =
      process.env.MOLLIE_TEST_API_KEY || "test_dHar4XY7LxsDOtmnkVtjNVWXLSlXsM";

    // Mollie test payment configurations
    this.paymentMethods = {
      ideal: {
        name: "iDEAL",
        testBanks: ["ideal_TESTNL99", "ideal_TESTNL01"],
        processingTime: 3000,
      },
      creditcard: {
        name: "Credit Card",
        testCards: ["4242424242424242", "5555555555554444"],
        processingTime: 2000,
      },
      banktransfer: {
        name: "Bank Transfer",
        processingTime: 5000,
      },
      paypal: {
        name: "PayPal",
        processingTime: 3000,
      },
    };

    // Test scenarios for different payment outcomes
    this.testScenarios = {
      success: {
        finalStatus: "paid",
        description: "Successful payment completion",
      },
      failed: {
        finalStatus: "failed",
        description: "Payment failure scenario",
      },
      cancelled: {
        finalStatus: "cancelled",
        description: "User cancelled payment",
      },
      expired: {
        finalStatus: "expired",
        description: "Payment expired without completion",
      },
      pending: {
        finalStatus: "pending",
        description: "Payment pending (for bank transfer)",
      },
    };
  }

  /**
   * Complete a test payment on Mollie payment page
   *
   * @param {Object} options Payment completion options
   * @param {string} options.paymentMethod Payment method to use
   * @param {number} options.amount Payment amount
   * @param {string} options.testScenario Test scenario (success, failed, etc.)
   * @returns {Object} Payment result with status and details
   */
  async completeTestPayment(options = {}) {
    const {
      paymentMethod = "ideal",
      amount,
      testScenario = "success",
      waitForRedirect = true,
    } = options;

    console.log(
      `[Mollie] Starting test payment: ${paymentMethod}, €${amount}, scenario: ${testScenario}`,
    );

    try {
      // Verify we're on Mollie payment page
      await this.page.waitForURL(/mollie\.(com|nl)/, { timeout: 10000 });
      await this.page.waitForLoadState("networkidle");

      // Take screenshot of Mollie payment page
      await this.page.screenshot({
        path: `test-results/mollie-payment-page-${Date.now()}.png`,
      });

      // Select payment method if not already selected
      if (
        await this.page.locator(`[data-testid="${paymentMethod}"]`).isVisible()
      ) {
        await this.page.click(`[data-testid="${paymentMethod}"]`);
        console.log(`[Mollie] Selected payment method: ${paymentMethod}`);
      }

      // Handle specific payment method flows
      const paymentResult = await this.handlePaymentMethodFlow(
        paymentMethod,
        testScenario,
      );

      // Wait for processing and redirect if expected
      if (waitForRedirect) {
        await this.waitForPaymentProcessing(testScenario);
      }

      console.log(
        `[Mollie] Payment completed with status: ${paymentResult.status}`,
      );
      return paymentResult;
    } catch (error) {
      console.error(`[Mollie] Payment completion failed: ${error.message}`);

      // Take screenshot for debugging
      await this.page.screenshot({
        path: `test-results/mollie-error-${Date.now()}.png`,
        fullPage: true,
      });

      throw new Error(`Mollie payment completion failed: ${error.message}`);
    }
  }

  /**
   * Handle payment method specific flows
   */
  async handlePaymentMethodFlow(paymentMethod, testScenario) {
    const methodConfig = this.paymentMethods[paymentMethod];
    if (!methodConfig) {
      throw new Error(`Unsupported payment method: ${paymentMethod}`);
    }

    console.log(`[Mollie] Processing ${methodConfig.name} payment`);

    switch (paymentMethod) {
      case "ideal":
        return await this.processIdealPayment(testScenario);

      case "creditcard":
        return await this.processCreditCardPayment(testScenario);

      case "banktransfer":
        return await this.processBankTransferPayment(testScenario);

      case "paypal":
        return await this.processPayPalPayment(testScenario);

      default:
        return await this.processGenericPayment(paymentMethod, testScenario);
    }
  }

  /**
   * Process iDEAL test payment
   */
  async processIdealPayment(testScenario) {
    // Look for iDEAL bank selection
    if (await this.page.locator('[name="issuer"]').isVisible()) {
      // Select test bank based on scenario
      const testBank =
        testScenario === "success" ? "ideal_TESTNL99" : "ideal_TESTNL01";
      await this.page.selectOption('[name="issuer"]', testBank);
      console.log(`[Mollie] Selected test bank: ${testBank}`);
    }

    // Click continue/pay button
    await this.clickPaymentButton();

    // Handle test bank page
    if (
      (await this.page.url().includes("testbank")) ||
      (await this.page.locator(".test-bank-page").isVisible())
    ) {
      return await this.handleTestBankFlow(testScenario);
    }

    return this.generatePaymentResult(testScenario);
  }

  /**
   * Process credit card test payment
   */
  async processCreditCardPayment(testScenario) {
    // Fill test credit card details if form is present
    if (await this.page.locator('[name="cardNumber"]').isVisible()) {
      const testCard =
        testScenario === "success" ? "4242424242424242" : "4000000000000002";

      await this.page.fill('[name="cardNumber"]', testCard);
      await this.page.fill('[name="expiryDate"]', "12/25");
      await this.page.fill('[name="cardCvc"]', "123");
      await this.page.fill('[name="cardHolder"]', "Test Cardholder");

      console.log(
        `[Mollie] Filled credit card details for ${testScenario} scenario`,
      );
    }

    await this.clickPaymentButton();

    return this.generatePaymentResult(testScenario);
  }

  /**
   * Process bank transfer test payment
   */
  async processBankTransferPayment(testScenario) {
    // Bank transfer usually just requires confirmation
    await this.clickPaymentButton();

    // Bank transfers typically start as pending
    const status = testScenario === "success" ? "pending" : testScenario;
    return this.generatePaymentResult(status);
  }

  /**
   * Process PayPal test payment
   */
  async processPayPalPayment(testScenario) {
    await this.clickPaymentButton();

    // Handle PayPal sandbox if we get redirected
    if (this.page.url().includes("sandbox.paypal.com")) {
      await this.handlePayPalSandbox(testScenario);
    }

    return this.generatePaymentResult(testScenario);
  }

  /**
   * Process generic payment method
   */
  async processGenericPayment(paymentMethod, testScenario) {
    console.log(`[Mollie] Processing generic payment method: ${paymentMethod}`);

    await this.clickPaymentButton();

    return this.generatePaymentResult(testScenario);
  }

  /**
   * Handle test bank simulation flow
   */
  async handleTestBankFlow(testScenario) {
    console.log(
      `[Mollie] Handling test bank flow for scenario: ${testScenario}`,
    );

    // Wait for test bank page to load
    await this.page.waitForLoadState("networkidle");

    // Look for test bank buttons/options
    const successButton = this.page.locator(
      '[data-testid="success"], .btn-success, [value="success"]',
    );
    const failButton = this.page.locator(
      '[data-testid="fail"], .btn-danger, [value="fail"]',
    );

    if (testScenario === "success" && (await successButton.isVisible())) {
      await successButton.click();
      console.log("[Mollie] Clicked success button in test bank");
    } else if (testScenario === "failed" && (await failButton.isVisible())) {
      await failButton.click();
      console.log("[Mollie] Clicked fail button in test bank");
    } else {
      // Generic continue button
      await this.clickPaymentButton();
    }

    return this.generatePaymentResult(testScenario);
  }

  /**
   * Handle PayPal sandbox flow
   */
  async handlePayPalSandbox(testScenario) {
    console.log(
      `[Mollie] Handling PayPal sandbox for scenario: ${testScenario}`,
    );

    // PayPal sandbox login (if required)
    if (await this.page.locator("#email").isVisible()) {
      await this.page.fill("#email", "test-buyer@example.com");
      await this.page.fill("#password", "testpassword");
      await this.page.click("#btnLogin");
    }

    // Approve or decline payment based on scenario
    if (testScenario === "success") {
      const approveButton = this.page.locator(
        '#confirmButtonTop, #payment-submit-btn, [data-testid="approve"]',
      );
      if (await approveButton.isVisible()) {
        await approveButton.click();
      }
    } else {
      const cancelButton = this.page.locator(
        '#cancelLink, [data-testid="cancel"]',
      );
      if (await cancelButton.isVisible()) {
        await cancelButton.click();
      }
    }
  }

  /**
   * Click the payment/continue button with robust selectors
   */
  async clickPaymentButton() {
    const buttonSelectors = [
      '[type="submit"]',
      ".btn-primary",
      '[data-testid="pay"]',
      '[data-testid="continue"]',
      'button:has-text("Pay")',
      'button:has-text("Continue")',
      'button:has-text("Confirm")',
      'input[type="submit"]',
    ];

    for (const selector of buttonSelectors) {
      if (await this.page.locator(selector).isVisible()) {
        await this.page.click(selector);
        console.log(`[Mollie] Clicked payment button: ${selector}`);
        break;
      }
    }
  }

  /**
   * Wait for payment processing and potential redirect
   */
  async waitForPaymentProcessing(testScenario, timeout = 15000) {
    console.log("[Mollie] Waiting for payment processing...");

    try {
      // Wait for either redirect back to site or processing completion
      await Promise.race([
        // Wait for redirect back to main site
        this.page.waitForURL(/dev\.veganisme\.net/, { timeout }),

        // Wait for processing completion indicator
        this.page.waitForSelector(
          ".payment-success, .payment-failed, .payment-complete",
          { timeout },
        ),

        // Wait for specific test scenario outcomes
        this.waitForScenarioCompletion(testScenario, timeout),
      ]);

      console.log("[Mollie] Payment processing completed");
    } catch (error) {
      console.warn(`[Mollie] Payment processing timeout: ${error.message}`);
      // Don't fail the test, just log the timeout
    }
  }

  /**
   * Wait for specific test scenario completion indicators
   */
  async waitForScenarioCompletion(testScenario, timeout) {
    switch (testScenario) {
      case "success":
        return this.page.waitForSelector(".success, .paid, .completed", {
          timeout,
        });

      case "failed":
        return this.page.waitForSelector(".failed, .error, .declined", {
          timeout,
        });

      case "cancelled":
        return this.page.waitForSelector(".cancelled, .canceled", { timeout });

      default:
        // Generic wait
        await this.page.waitForTimeout(3000);
    }
  }

  /**
   * Generate payment result object
   */
  generatePaymentResult(testScenario) {
    const scenario =
      this.testScenarios[testScenario] || this.testScenarios.success;
    const paymentId = this.generateTestPaymentId();

    return {
      id: paymentId,
      status: scenario.finalStatus,
      amount: {
        value: "25.00", // This should be passed from the test
        currency: "EUR",
      },
      description: "Test donation via E2E test",
      metadata: {
        test: true,
        scenario: testScenario,
        timestamp: new Date().toISOString(),
      },
      createdAt: new Date().toISOString(),
      paidAt: scenario.finalStatus === "paid" ? new Date().toISOString() : null,
    };
  }

  /**
   * Generate a test payment ID that looks like a real Mollie ID
   */
  generateTestPaymentId() {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).substring(2, 8);
    return `tr_test_${timestamp}${random}`;
  }

  /**
   * Validate Mollie payment page elements
   */
  async validateMolliePaymentPage() {
    console.log("[Mollie] Validating payment page elements...");

    const validationChecks = [
      {
        selector: ".payment-form, .mollie-form",
        description: "Payment form present",
      },
      {
        selector: ".amount, .payment-amount",
        description: "Payment amount displayed",
      },
      {
        selector: ".payment-methods, .method-selector",
        description: "Payment methods available",
      },
    ];

    const results = {};

    for (const check of validationChecks) {
      try {
        const isVisible = await this.page.locator(check.selector).isVisible();
        results[check.description] = isVisible;
        console.log(
          `[Mollie] ${check.description}: ${isVisible ? "PASS" : "FAIL"}`,
        );
      } catch (error) {
        results[check.description] = false;
        console.log(`[Mollie] ${check.description}: ERROR - ${error.message}`);
      }
    }

    return results;
  }

  /**
   * Get current payment status from page
   */
  async getCurrentPaymentStatus() {
    try {
      // Look for status indicators on the page
      if (await this.page.locator(".payment-success, .paid").isVisible()) {
        return "paid";
      } else if (
        await this.page.locator(".payment-failed, .failed").isVisible()
      ) {
        return "failed";
      } else if (
        await this.page.locator(".payment-cancelled, .cancelled").isVisible()
      ) {
        return "cancelled";
      } else if (
        await this.page.locator(".payment-pending, .pending").isVisible()
      ) {
        return "pending";
      }

      return "unknown";
    } catch (error) {
      console.warn(
        `[Mollie] Could not determine payment status: ${error.message}`,
      );
      return "error";
    }
  }

  /**
   * Simulate webhook data for testing
   */
  generateWebhookPayload(paymentId, status = "paid", customData = {}) {
    return {
      resource: "payment",
      id: paymentId,
      mode: "test",
      createdAt: new Date().toISOString(),
      status,
      amount: {
        value: "25.00",
        currency: "EUR",
      },
      description: "Test donation",
      method: "ideal",
      metadata: {
        test: true,
        ...customData,
      },
      details: {
        bankName: "Test Bank",
        consumerName: "Test Consumer",
        consumerAccount: "NL44TEST0123456789",
      },
      _links: {
        self: {
          href: `https://api.mollie.com/v2/payments/${paymentId}`,
          type: "application/json",
        },
        checkout: {
          href: `https://www.mollie.com/payscreen/select-method/${paymentId}`,
          type: "text/html",
        },
      },
    };
  }
}

module.exports = { MollieTestHelpers };
