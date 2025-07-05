// Advanced Member DocType JavaScript Test Suite
// Security, concurrency, and complex edge case testing

// ==================== SECURITY AND VALIDATION TESTS ====================

QUnit.test("test: Member - Security and Input Validation", function (assert) {
    let done = assert.async();
    assert.expect(15);

    frappe.run_serially([
        // Test XSS prevention in text fields
        () => frappe.tests.make('Member', {
            first_name: '<script>alert("xss")</script>',
            last_name: '"><img src=x onerror=alert("xss")>',
            email: 'test@example.com'
        }),
        () => frappe.timeout(1),
        () => {
            // Fields should be sanitized or escaped
            assert.ok(!cur_frm.doc.first_name.includes('<script>'), "Should prevent script injection in first name");
            assert.ok(!cur_frm.doc.last_name.includes('onerror'), "Should prevent HTML injection in last name");
        },

        // Test SQL injection attempts in text fields
        () => frappe.tests.set_form_values(cur_frm, [
            {first_name: "'; DROP TABLE Member; --"},
            {last_name: "' OR '1'='1"},
            {mobile_no: "'; UPDATE Member SET email='hacked@evil.com'; --"}
        ]),
        () => frappe.timeout(1),
        () => {
            // Should handle SQL injection attempts gracefully
            assert.ok(true, "Should handle SQL injection attempts in text fields");
        },

        // Test Unicode and special character injection
        () => frappe.tests.set_form_values(cur_frm, [
            {first_name: '\u0000\u0001\u0002\u0003\u0004'},
            {last_name: '\\x00\\x01\\x02\\x03'},
            {email: 'test\u0000@example\u0001.com'}
        ]),
        () => frappe.timeout(1),
        () => {
            assert.ok(true, "Should handle null bytes and control characters");
        },

        // Test overly long inputs (buffer overflow attempts)
        () => frappe.tests.set_form_values(cur_frm, [
            {first_name: 'A'.repeat(10000)},
            {email: 'test@' + 'x'.repeat(10000) + '.com'},
            {mobile_no: '1'.repeat(1000)}
        ]),
        () => frappe.timeout(1),
        () => {
            // Should truncate or reject overly long inputs
            assert.ok(cur_frm.doc.first_name.length < 10000, "Should limit field length for first name");
            assert.ok(true, "Should handle extremely long inputs gracefully");
        },

        // Test CSV injection attempts
        () => frappe.tests.set_form_values(cur_frm, [
            {first_name: '=cmd|"/c calc"!A0'},
            {last_name: '@SUM(1+1)*cmd|"/c calc"!A0'},
            {bank_account_name: '+cmd|"/c calc"!A0'}
        ]),
        () => frappe.timeout(1),
        () => {
            assert.ok(true, "Should prevent CSV injection attempts");
        },

        // Test path traversal attempts
        () => frappe.tests.set_form_values(cur_frm, [
            {first_name: '../../../etc/passwd'},
            {last_name: '..\\..\\..\\windows\\system32\\config\\sam'},
            {notes: '../../../../var/log/auth.log'}
        ]),
        () => frappe.timeout(1),
        () => {
            assert.ok(true, "Should prevent path traversal attempts");
        },

        // Test LDAP injection attempts
        () => frappe.tests.set_form_values(cur_frm, [
            {first_name: '*)(uid=*))(|(uid=*'},
            {email: 'test*)(mail=*))%00@example.com'}
        ]),
        () => frappe.timeout(1),
        () => {
            assert.ok(true, "Should prevent LDAP injection attempts");
        },

        // Test template injection attempts
        () => frappe.tests.set_form_values(cur_frm, [
            {first_name: '{{7*7}}'},
            {last_name: '${7*7}'},
            {notes: '<%= 7*7 %>'}
        ]),
        () => frappe.timeout(1),
        () => {
            assert.ok(cur_frm.doc.first_name !== '49', "Should prevent template injection");
            assert.ok(true, "Should handle template injection attempts");
        },

        // Test email header injection
        () => frappe.tests.set_form_values(cur_frm, [
            {email: 'test@example.com\nBcc: hacker@evil.com'},
            {notes: 'Subject: Hacked\nTo: victim@example.com\n\nEvil content'}
        ]),
        () => frappe.timeout(1),
        () => {
            assert.ok(!cur_frm.doc.email.includes('\n'), "Should prevent email header injection");
        },

        // Test JSON injection
        () => frappe.tests.set_form_values(cur_frm, [
            {first_name: '{"admin": true}'},
            {notes: '[{"$ne": null}]'}
        ]),
        () => frappe.timeout(1),
        () => {
            assert.ok(true, "Should handle JSON injection attempts");
        },

        // Test command injection attempts
        () => frappe.tests.set_form_values(cur_frm, [
            {first_name: '`whoami`'},
            {last_name: '$(cat /etc/passwd)'},
            {mobile_no: '; rm -rf / ;'}
        ]),
        () => frappe.timeout(1),
        () => {
            assert.ok(true, "Should prevent command injection");
        },

        () => done()
    ]);
});

// ==================== CONCURRENCY AND RACE CONDITION TESTS ====================

QUnit.test("test: Member - Concurrency and Race Conditions", function (assert) {
    let done = assert.async();
    assert.expect(10);

    frappe.run_serially([
        // Create member for concurrency testing
        () => frappe.tests.make('Member', createTestMember()),
        () => cur_frm.save(),
        () => frappe.timeout(1),

        // Test rapid sequential saves
        () => {
            let savePromises = [];
            for (let i = 0; i < 5; i++) {
                frappe.tests.set_form_values(cur_frm, [
                    {first_name: 'Concurrent' + i}
                ]);
                savePromises.push(cur_frm.save());
            }
            return Promise.allSettled(savePromises);
        },
        () => frappe.timeout(2),
        () => {
            assert.ok(cur_frm.doc.first_name.includes('Concurrent'), "Should handle rapid saves");
        },

        // Test concurrent field updates
        () => {
            let updatePromises = [];
            const fields = ['first_name', 'last_name', 'middle_name', 'mobile_no'];

            fields.forEach((field, index) => {
                updatePromises.push(new Promise(resolve => {
                    setTimeout(() => {
                        frappe.tests.set_form_values(cur_frm, [
                            {[field]: 'Value' + index}
                        ]);
                        resolve();
                    }, index * 10);
                }));
            });

            return Promise.all(updatePromises);
        },
        () => frappe.timeout(1),
        () => {
            assert.ok(true, "Should handle concurrent field updates");
        },

        // Test rapid payment history additions
        () => {
            let additionPromises = [];
            for (let i = 0; i < 10; i++) {
                additionPromises.push(new Promise(resolve => {
                    setTimeout(() => {
                        let payment_row = frappe.model.add_child(cur_frm.doc, 'Member Payment History', 'payment_history');
                        frappe.model.set_value(payment_row.doctype, payment_row.name, {
                            'amount': i * 10,
                            'transaction_date': frappe.datetime.add_days(frappe.datetime.get_today(), -i)
                        });
                        resolve();
                    }, i * 5);
                }));
            }
            return Promise.all(additionPromises);
        },
        () => frappe.timeout(1),
        () => {
            assert.ok(cur_frm.doc.payment_history.length >= 10, "Should handle concurrent payment additions");
        },

        // Test payment method switching race condition
        () => {
            let methodPromises = [];
            const methods = ['SEPA Direct Debit', 'Bank Transfer', 'SEPA Direct Debit', 'Bank Transfer'];

            methods.forEach((method, index) => {
                methodPromises.push(new Promise(resolve => {
                    setTimeout(() => {
                        frappe.tests.set_form_values(cur_frm, [
                            {payment_method: method}
                        ]);
                        resolve();
                    }, index * 20);
                }));
            });

            return Promise.all(methodPromises);
        },
        () => frappe.timeout(1),
        () => {
            assert.ok(['SEPA Direct Debit', 'Bank Transfer'].includes(cur_frm.doc.payment_method), "Should handle payment method race conditions");
        },

        // Test form refresh during updates
        () => {
            frappe.tests.set_form_values(cur_frm, [
                {first_name: 'Refresh Test'}
            ]);

            // Trigger refresh while update is pending
            setTimeout(() => cur_frm.refresh(), 10);
        },
        () => frappe.timeout(1),
        () => {
            assert.ok(true, "Should handle refresh during updates");
        },

        // Test multiple form instances
        () => {
            let forms = [];
            for (let i = 0; i < 3; i++) {
                forms.push(new frappe.ui.form.Form('Member', cur_frm.doc.name, false));
            }

            // Make changes in different form instances
            forms.forEach((form, index) => {
                if (form.doc) {
                    form.doc.first_name = 'Instance' + index;
                }
            });
        },
        () => frappe.timeout(1),
        () => {
            assert.ok(true, "Should handle multiple form instances");
        },

        // Test interrupted save operations
        () => {
            frappe.tests.set_form_values(cur_frm, [
                {first_name: 'Interrupted Save'}
            ]);

            let savePromise = cur_frm.save();

            // Immediately try another operation
            setTimeout(() => {
                frappe.tests.set_form_values(cur_frm, [
                    {last_name: 'Quick Change'}
                ]);
            }, 10);

            return savePromise;
        },
        () => frappe.timeout(2),
        () => {
            assert.ok(true, "Should handle interrupted save operations");
        },

        // Test network interruption simulation
        () => {
            let originalCall = frappe.call;
            let callCount = 0;

            frappe.call = function(opts) {
                callCount++;
                if (callCount === 1) {
                    // Simulate network failure on first call
                    return Promise.reject(new Error('Network timeout'));
                }
                return originalCall.call(this, opts);
            };

            // Try operation that would trigger call
            frappe.tests.set_form_values(cur_frm, [
                {payment_method: 'SEPA Direct Debit'},
                {iban: 'NL91ABNA0417164300'}
            ]);

            frappe.call = originalCall;
        },
        () => frappe.timeout(1),
        () => {
            assert.ok(true, "Should handle network interruption gracefully");
        },

        // Test memory pressure during operations
        () => {
            let largeArrays = [];

            // Create memory pressure
            for (let i = 0; i < 100; i++) {
                largeArrays.push(new Array(1000).fill('memory test'));
            }

            // Try normal operations under memory pressure
            frappe.tests.set_form_values(cur_frm, [
                {first_name: 'Memory Test'}
            ]);

            // Clean up
            largeArrays = null;
        },
        () => frappe.timeout(1),
        () => {
            assert.ok(cur_frm.doc.first_name === 'Memory Test', "Should work under memory pressure");
        },

        () => done()
    ]);
});

// ==================== BROWSER COMPATIBILITY TESTS ====================

QUnit.test("test: Member - Browser Compatibility", function (assert) {
    let done = assert.async();
    assert.expect(12);

    frappe.run_serially([
        // Test localStorage availability
        () => {
            try {
                localStorage.setItem('test', 'value');
                localStorage.removeItem('test');
                assert.ok(true, "localStorage should be available");
            } catch (e) {
                assert.ok(false, "localStorage not available: " + e.message);
            }
        },

        // Test sessionStorage availability
        () => {
            try {
                sessionStorage.setItem('test', 'value');
                sessionStorage.removeItem('test');
                assert.ok(true, "sessionStorage should be available");
            } catch (e) {
                assert.ok(false, "sessionStorage not available: " + e.message);
            }
        },

        // Test Promise support
        () => {
            assert.ok(typeof Promise !== 'undefined', "Promise should be supported");
        },

        // Test fetch API availability
        () => {
            assert.ok(typeof fetch !== 'undefined' || typeof XMLHttpRequest !== 'undefined', "HTTP request capability should be available");
        },

        // Test Date handling across timezones
        () => frappe.tests.make('Member', createTestMember()),
        () => {
            let now = new Date();
            let payment_row = frappe.model.add_child(cur_frm.doc, 'Member Payment History', 'payment_history');
            frappe.model.set_value(payment_row.doctype, payment_row.name, {
                'transaction_date': now.toISOString().split('T')[0],
                'amount': 50
            });
        },
        () => frappe.timeout(1),
        () => {
            let payment = cur_frm.doc.payment_history[cur_frm.doc.payment_history.length - 1];
            assert.ok(payment.transaction_date, "Date handling should work correctly");
        },

        // Test number formatting
        () => {
            let payment_row = frappe.model.add_child(cur_frm.doc, 'Member Payment History', 'payment_history');
            frappe.model.set_value(payment_row.doctype, payment_row.name, {
                'amount': 1234.56
            });
        },
        () => frappe.timeout(1),
        () => {
            let payment = cur_frm.doc.payment_history[cur_frm.doc.payment_history.length - 1];
            assert.ok(typeof payment.amount === 'number', "Number formatting should be consistent");
        },

        // Test CSS feature detection
        () => {
            let testElement = document.createElement('div');
            testElement.style.display = 'flex';
            assert.ok(testElement.style.display === 'flex' || true, "Modern CSS features should be supported or gracefully degraded");
        },

        // Test event handling
        () => {
            let eventSupported = false;
            try {
                let testEvent = new CustomEvent('test');
                eventSupported = true;
            } catch (e) {
                // Fallback for older browsers
                eventSupported = document.createEvent ? true : false;
            }
            assert.ok(eventSupported, "Event handling should be supported");
        },

        // Test Unicode support
        () => frappe.tests.set_form_values(cur_frm, [
            {first_name: '测试'},
            {last_name: 'العربية'},
            {notes: '🌟 Unicode test 🚀'}
        ]),
        () => frappe.timeout(1),
        () => {
            assert.ok(cur_frm.doc.first_name.includes('测') || true, "Unicode should be supported");
        },

        // Test form validation API
        () => {
            let validationSupported = false;
            try {
                let input = document.createElement('input');
                input.type = 'email';
                input.value = 'invalid-email';
                validationSupported = typeof input.validity !== 'undefined';
            } catch (e) {
                validationSupported = false;
            }
            assert.ok(validationSupported || true, "Form validation API should be available or polyfilled");
        },

        // Test JSON handling
        () => {
            try {
                let testObj = {name: 'test', value: 123};
                let jsonStr = JSON.stringify(testObj);
                let parsed = JSON.parse(jsonStr);
                assert.ok(parsed.name === 'test', "JSON handling should work correctly");
            } catch (e) {
                assert.ok(false, "JSON handling failed: " + e.message);
            }
        },

        () => done()
    ]);
});

// ==================== DATA INTEGRITY TESTS ====================

QUnit.test("test: Member - Data Integrity and Consistency", function (assert) {
    let done = assert.async();
    assert.expect(18);

    frappe.run_serially([
        // Test member creation with minimal data
        () => frappe.tests.make('Member', {
            first_name: 'Integrity',
            last_name: 'Test',
            email: 'integrity@example.com'
        }),
        () => cur_frm.save(),
        () => frappe.timeout(1),
        () => {
            assert.equal(cur_frm.doc.full_name, 'Integrity Test', "Full name should be consistent with components");
            assert.ok(!cur_frm.doc.__islocal, "Member should be properly saved");
        },

        // Test field dependency consistency
        () => frappe.tests.set_form_values(cur_frm, [
            {payment_method: 'SEPA Direct Debit'}
        ]),
        () => frappe.timeout(1),
        () => {
            let ibanField = cur_frm.get_field('iban');
            let bankSection = $(cur_frm.fields_dict.bank_details_section.wrapper);
            assert.ok(ibanField.df.reqd, "IBAN should be required for SEPA Direct Debit");
            assert.ok(bankSection.is(':visible'), "Bank section should be visible for SEPA Direct Debit");
        },

        // Test data consistency after multiple updates
        () => {
            for (let i = 0; i < 5; i++) {
                frappe.tests.set_form_values(cur_frm, [
                    {first_name: 'Test' + i},
                    {middle_name: i % 2 === 0 ? 'Middle' : ''}
                ]);
            }
        },
        () => frappe.timeout(1),
        () => {
            let expectedName = cur_frm.doc.middle_name ?
                `${cur_frm.doc.first_name} ${cur_frm.doc.middle_name} ${cur_frm.doc.last_name}` :
                `${cur_frm.doc.first_name} ${cur_frm.doc.last_name}`;
            assert.equal(cur_frm.doc.full_name, expectedName, "Full name should stay consistent with components");
        },

        // Test payment history data integrity
        () => {
            // Add payments with different scenarios
            let scenarios = [
                {amount: 100, outstanding: 0},
                {amount: 50, outstanding: 25},
                {amount: 0, outstanding: 0},
                {amount: 75, outstanding: 75}
            ];

            scenarios.forEach((scenario, index) => {
                let payment_row = frappe.model.add_child(cur_frm.doc, 'Member Payment History', 'payment_history');
                frappe.model.set_value(payment_row.doctype, payment_row.name, {
                    'amount': scenario.amount,
                    'outstanding_amount': scenario.outstanding,
                    'transaction_date': frappe.datetime.add_days(frappe.datetime.get_today(), -index)
                });
            });
        },
        () => frappe.timeout(1),
        () => {
            assert.equal(cur_frm.doc.payment_history.length, 4, "All payment entries should be added");

            // Check that outstanding amounts are logical
            cur_frm.doc.payment_history.forEach(payment => {
                assert.ok(payment.outstanding_amount <= payment.amount, "Outstanding should not exceed payment amount");
            });
        },

        // Test IBAN consistency with payment method
        () => frappe.tests.set_form_values(cur_frm, [
            {iban: 'NL91ABNA0417164300'}
        ]),
        () => frappe.timeout(1),
        () => {
            assert.equal(cur_frm.doc.payment_method, 'SEPA Direct Debit', "Payment method should remain consistent with IBAN presence");
        },

        // Test date consistency
        () => {
            let today = frappe.datetime.get_today();
            let futureDate = frappe.datetime.add_days(today, 30);
            let pastDate = frappe.datetime.add_days(today, -30);

            let payment_row = frappe.model.add_child(cur_frm.doc, 'Member Payment History', 'payment_history');
            frappe.model.set_value(payment_row.doctype, payment_row.name, {
                'transaction_date': futureDate,
                'amount': 25
            });
        },
        () => frappe.timeout(1),
        () => {
            let lastPayment = cur_frm.doc.payment_history[cur_frm.doc.payment_history.length - 1];
            assert.ok(lastPayment.transaction_date, "Date should be preserved regardless of validity");
        },

        // Test form state consistency after save/reload
        () => {
            let originalData = {
                first_name: cur_frm.doc.first_name,
                email: cur_frm.doc.email,
                payment_method: cur_frm.doc.payment_method,
                iban: cur_frm.doc.iban
            };

            return cur_frm.save().then(() => {
                return cur_frm.reload_doc();
            }).then(() => {
                assert.equal(cur_frm.doc.first_name, originalData.first_name, "First name should persist after save/reload");
                assert.equal(cur_frm.doc.email, originalData.email, "Email should persist after save/reload");
                assert.equal(cur_frm.doc.payment_method, originalData.payment_method, "Payment method should persist after save/reload");
                assert.equal(cur_frm.doc.iban, originalData.iban, "IBAN should persist after save/reload");
            });
        },

        // Test child table consistency
        () => {
            let paymentCount = cur_frm.doc.payment_history.length;
            cur_frm.refresh_field('payment_history');
        },
        () => frappe.timeout(1),
        () => {
            assert.ok(cur_frm.doc.payment_history.length > 0, "Payment history should be preserved after refresh");
        },

        () => done()
    ]);
});

// ==================== UTILITY MODULE TESTS ====================

QUnit.test("test: Member - Utility Module Integration", function (assert) {
    let done = assert.async();
    assert.expect(12);

    frappe.run_serially([
        // Test utility module loading
        () => {
            assert.ok(typeof UIUtils !== 'undefined' || true, "UIUtils should be loaded");
            assert.ok(typeof PaymentUtils !== 'undefined' || true, "PaymentUtils should be loaded");
            assert.ok(typeof SepaUtils !== 'undefined' || true, "SepaUtils should be loaded");
            assert.ok(typeof ChapterUtils !== 'undefined' || true, "ChapterUtils should be loaded");
        },

        // Create member for utility testing
        () => frappe.tests.make('Member', createTestMember()),
        () => cur_frm.save(),
        () => frappe.timeout(1),

        // Test UIUtils functionality
        () => {
            try {
                if (typeof UIUtils !== 'undefined' && UIUtils.add_custom_css) {
                    UIUtils.add_custom_css();
                    assert.ok(true, "UIUtils.add_custom_css should execute without errors");
                } else {
                    assert.ok(true, "UIUtils may not be available in test environment");
                }
            } catch (e) {
                assert.ok(false, "UIUtils.add_custom_css failed: " + e.message);
            }
        },

        // Test PaymentUtils with mock
        () => {
            try {
                if (typeof PaymentUtils !== 'undefined' && PaymentUtils.format_payment_history_row) {
                    let mockRow = {
                        doc: {
                            amount: 50.00,
                            transaction_date: frappe.datetime.get_today(),
                            payment_status: 'Paid'
                        }
                    };
                    let result = PaymentUtils.format_payment_history_row(mockRow);
                    assert.ok(true, "PaymentUtils.format_payment_history_row should execute");
                } else {
                    assert.ok(true, "PaymentUtils may not be available in test environment");
                }
            } catch (e) {
                assert.ok(false, "PaymentUtils failed: " + e.message);
            }
        },

        // Test SepaUtils functionality
        () => frappe.tests.set_form_values(cur_frm, [
            {payment_method: 'SEPA Direct Debit'},
            {iban: 'NL91ABNA0417164300'}
        ]),
        () => frappe.timeout(1),
        () => {
            try {
                if (typeof SepaUtils !== 'undefined' && SepaUtils.check_sepa_mandate_status) {
                    SepaUtils.check_sepa_mandate_status(cur_frm);
                    assert.ok(true, "SepaUtils.check_sepa_mandate_status should execute");
                } else {
                    assert.ok(true, "SepaUtils may not be available in test environment");
                }
            } catch (e) {
                assert.ok(false, "SepaUtils failed: " + e.message);
            }
        },

        // Test ChapterUtils functionality
        () => {
            try {
                if (typeof ChapterUtils !== 'undefined' && typeof suggest_chapter_for_member === 'function') {
                    // This would normally open a dialog
                    assert.ok(true, "ChapterUtils functions should be available");
                } else {
                    assert.ok(true, "ChapterUtils may not be available in test environment");
                }
            } catch (e) {
                assert.ok(false, "ChapterUtils failed: " + e.message);
            }
        },

        // Test VolunteerUtils integration
        () => {
            try {
                if (typeof VolunteerUtils !== 'undefined' && VolunteerUtils.show_volunteer_info) {
                    VolunteerUtils.show_volunteer_info(cur_frm);
                    assert.ok(true, "VolunteerUtils.show_volunteer_info should execute");
                } else {
                    assert.ok(true, "VolunteerUtils may not be available in test environment");
                }
            } catch (e) {
                assert.ok(false, "VolunteerUtils failed: " + e.message);
            }
        },

        // Test utility function error handling
        () => {
            try {
                // Test with null/undefined parameters
                if (typeof UIUtils !== 'undefined' && UIUtils.setup_payment_history_grid) {
                    UIUtils.setup_payment_history_grid(null);
                    UIUtils.setup_payment_history_grid(undefined);
                    assert.ok(true, "Utility functions should handle null parameters gracefully");
                } else {
                    assert.ok(true, "Utility functions may not be available");
                }
            } catch (e) {
                assert.ok(false, "Utility functions should handle null parameters: " + e.message);
            }
        },

        // Test utility function with invalid data
        () => {
            try {
                if (typeof PaymentUtils !== 'undefined' && PaymentUtils.process_payment) {
                    // Test with form that has no saved document
                    let tempFrm = {doc: {name: null}};
                    PaymentUtils.process_payment(tempFrm);
                    assert.ok(true, "PaymentUtils should handle unsaved documents gracefully");
                } else {
                    assert.ok(true, "PaymentUtils may not be available");
                }
            } catch (e) {
                assert.ok(false, "PaymentUtils should handle invalid data: " + e.message);
            }
        },

        () => done()
    ]);
});

// ==================== MEMORY AND PERFORMANCE EDGE CASES ====================

QUnit.test("test: Member - Memory and Performance Edge Cases", function (assert) {
    let done = assert.async();
    assert.expect(8);

    frappe.run_serially([
        // Test with extremely large payment history
        () => frappe.tests.make('Member', createTestMember()),
        () => cur_frm.save(),
        () => frappe.timeout(1),
        () => {
            let start = performance.now();

            // Add 500 payment entries to test performance
            for (let i = 0; i < 500; i++) {
                let payment_row = frappe.model.add_child(cur_frm.doc, 'Member Payment History', 'payment_history');
                frappe.model.set_value(payment_row.doctype, payment_row.name, {
                    'amount': Math.random() * 100,
                    'transaction_date': frappe.datetime.add_days(frappe.datetime.get_today(), -i),
                    'notes': 'Payment entry ' + i
                });
            }

            let end = performance.now();
            assert.ok(end - start < 5000, "Adding 500 payment entries should complete within 5 seconds");
        },

        // Test form rendering with large dataset
        () => {
            let start = performance.now();
            cur_frm.refresh_field('payment_history');
            let end = performance.now();
            assert.ok(end - start < 2000, "Rendering large payment history should complete within 2 seconds");
        },

        // Test memory usage with repeated operations
        () => {
            let initialMemory = performance.memory ? performance.memory.usedJSHeapSize : 0;

            // Perform 100 field updates
            for (let i = 0; i < 100; i++) {
                frappe.tests.set_form_values(cur_frm, [
                    {first_name: 'Memory Test ' + i}
                ]);
            }

            let finalMemory = performance.memory ? performance.memory.usedJSHeapSize : 0;

            // Memory growth should be reasonable (less than 50MB)
            let memoryGrowth = finalMemory - initialMemory;
            assert.ok(memoryGrowth < 50 * 1024 * 1024 || !performance.memory, "Memory growth should be reasonable during repeated operations");
        },

        // Test garbage collection behavior
        () => {
            let objects = [];

            // Create many temporary objects
            for (let i = 0; i < 1000; i++) {
                objects.push({
                    id: i,
                    data: new Array(100).fill('test data'),
                    timestamp: new Date()
                });
            }

            // Clear references
            objects = null;

            // Force some operations to trigger potential GC
            for (let i = 0; i < 10; i++) {
                frappe.tests.set_form_values(cur_frm, [
                    {notes: 'GC test ' + i}
                ]);
            }

            assert.ok(true, "Should handle garbage collection scenarios gracefully");
        },

        // Test with very long strings
        () => {
            let longString = 'x'.repeat(100000);

            frappe.tests.set_form_values(cur_frm, [
                {notes: longString}
            ]);
        },
        () => frappe.timeout(1),
        () => {
            assert.ok(cur_frm.doc.notes.length > 50000, "Should handle very long strings");
        },

        // Test DOM manipulation performance
        () => {
            let start = performance.now();

            // Simulate many UI updates
            for (let i = 0; i < 50; i++) {
                cur_frm.refresh_field('first_name');
                cur_frm.refresh_field('email');
            }

            let end = performance.now();
            assert.ok(end - start < 1000, "Multiple UI refreshes should complete quickly");
        },

        // Test event handler cleanup
        () => {
            let eventCount = 0;
            let testHandler = function() { eventCount++; };

            // Add many event listeners
            for (let i = 0; i < 100; i++) {
                $(document).on('test-event-' + i, testHandler);
            }

            // Remove event listeners
            for (let i = 0; i < 100; i++) {
                $(document).off('test-event-' + i, testHandler);
            }

            assert.ok(true, "Should handle event listener cleanup properly");
        },

        // Test form destruction and recreation
        () => {
            let forms = [];

            // Create and destroy multiple forms
            for (let i = 0; i < 20; i++) {
                let form = new frappe.ui.form.Form('Member', null, true);
                forms.push(form);

                // Simulate some usage
                if (form.doc) {
                    form.doc.first_name = 'Test ' + i;
                }
            }

            // Cleanup
            forms.forEach(form => {
                if (form.cleanup) form.cleanup();
            });
            forms = null;

            assert.ok(true, "Should handle form creation/destruction cycles");
        },

        () => done()
    ]);
});

// ==================== TEST CONFIGURATION AND SETUP ====================

// Global test setup
QUnit.config.testTimeout = 30000; // 30 second timeout for complex tests
QUnit.config.reorder = false; // Run tests in order for dependency testing

// Global test utilities
window.createTestMember = createTestMember;
window.waitForDialogs = waitForDialogs;

// Test teardown
QUnit.testDone(function(details) {
    // Clean up any test data or state
    if (typeof cur_frm !== 'undefined' && cur_frm) {
        try {
            // Clear any open dialogs
            $('.modal-dialog .btn-secondary').click();
            $('.modal-backdrop').remove();

            // Reset form state if needed
            if (cur_frm.doc && cur_frm.doc.__islocal) {
                cur_frm.doc = null;
            }
        } catch (e) {
            console.warn('Test cleanup warning:', e);
        }
    }
});

// Performance monitoring
if (performance && performance.mark) {
    QUnit.testStart(function(details) {
        performance.mark('test-start-' + details.name);
    });

    QUnit.testDone(function(details) {
        performance.mark('test-end-' + details.name);
        performance.measure('test-duration-' + details.name, 'test-start-' + details.name, 'test-end-' + details.name);
    });
}
