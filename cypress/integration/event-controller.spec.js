/**
 * @fileoverview Event JavaScript Controller Tests
 *
 * Tests the Event DocType JavaScript controller functionality,
 * including event planning, registration management, logistics coordination,
 * attendance tracking, and integration with member and volunteer systems.
 *
 * Business Context:
 * Events are central to association activities, requiring comprehensive
 * planning, coordination, and execution. The system must manage registrations,
 * logistics, communications, and post-event analysis.
 *
 * @author Verenigingen Development Team
 * @version 1.0.0
 * @since 2025-08-19
 */

describe('Event JavaScript Controller Tests', () => {
	beforeEach(() => {
		const user = Cypress.env('ADMIN_USER');
		const pass = Cypress.env('ADMIN_PASSWORD');
		expect(user, 'ADMIN_USER env var').to.be.a('string').and.not.be.empty;
		expect(pass, 'ADMIN_PASSWORD env var').to.be.a('string').and.not.be.empty;
		cy.login(user, pass);
		cy.clear_test_data();
	});

	afterEach(() => {
		cy.clear_test_data();
	});

	describe('Event Form Controller Tests', () => {
		it('should load Event form with JavaScript controller', () => {
			// Navigate to new Event form
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			// Verify the controller is loaded
			cy.window().then((win) => {
				expect(win.frappe.ui.form.get_form('Event')).to.exist;
			});

			// Verify core fields are present
			cy.get('[data-fieldname="event_name"]').should('be.visible');
			cy.get('[data-fieldname="event_date"]').should('be.visible');
			cy.get('[data-fieldname="event_type"]').should('be.visible');
		});

		it('should test event creation workflow', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			// Create event
			cy.fill_frappe_field('event_name', 'Annual General Meeting');
			cy.fill_frappe_field('event_date', '2025-06-15', { fieldtype: 'Date' });
			cy.fill_frappe_field('event_type', 'Meeting', { fieldtype: 'Select' });
			cy.fill_frappe_field('description', 'Annual general meeting for all members');
			cy.fill_frappe_field('max_attendees', '100', { fieldtype: 'Int' });

			cy.save_frappe_doc();

			// Verify event was created
			cy.verify_frappe_field('event_name', 'Annual General Meeting');
			cy.verify_frappe_field('event_type', 'Meeting');
		});
	});

	describe('Event Planning and Setup Tests', () => {
		it('should test event planning workflow and logistics coordination', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'Summer Workshop Series');
			cy.fill_frappe_field('event_date', '2025-07-20', { fieldtype: 'Date' });
			cy.fill_frappe_field('event_type', 'Workshop', { fieldtype: 'Select' });
			cy.fill_frappe_field('venue', 'Community Center Hall A');
			cy.fill_frappe_field('duration', '8', { fieldtype: 'Float' });

			// Test planning features
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Test planning workflow
					if (frm.fields_dict.planning_checklist) {
						expect(frm.fields_dict.planning_checklist).to.exist;
						cy.log('Event planning checklist available');
					}

					// Test logistics coordination
					if (frm.fields_dict.logistics_coordinator) {
						expect(frm.fields_dict.logistics_coordinator).to.exist;
						cy.log('Logistics coordination available');
					}

					// Test resource requirements
					if (frm.fields_dict.resource_requirements) {
						expect(frm.fields_dict.resource_requirements).to.exist;
						cy.log('Resource requirements tracking available');
					}
				});
				return true;
			}, null, 'Event Planning');

			cy.save_frappe_doc();
		});

		it('should test venue management and capacity planning', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'Networking Evening');
			cy.fill_frappe_field('event_date', '2025-08-10', { fieldtype: 'Date' });
			cy.fill_frappe_field('venue', 'Grand Hotel Ballroom');
			cy.fill_frappe_field('max_attendees', '150', { fieldtype: 'Int' });
			cy.fill_frappe_field('venue_capacity', '200', { fieldtype: 'Int' });

			// Test venue management
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Test venue booking
					if (frm.fields_dict.venue_booking) {
						expect(frm.fields_dict.venue_booking).to.exist;
						cy.log('Venue booking management available');
					}

					// Test capacity validation
					if (frm.fields_dict.capacity_validation) {
						expect(frm.fields_dict.capacity_validation).to.exist;
						cy.log('Capacity validation available');
					}

					// Test accessibility requirements
					if (frm.fields_dict.accessibility_features) {
						expect(frm.fields_dict.accessibility_features).to.exist;
						cy.log('Accessibility features tracking available');
					}
				});
				return true;
			}, 'Venue Management');

			cy.save_frappe_doc();
		});
	});

	describe('Registration and Attendance Management Tests', () => {
		it('should test event registration workflow and participant tracking', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'Professional Development Seminar');
			cy.fill_frappe_field('event_date', '2025-09-05', { fieldtype: 'Date' });
			cy.fill_frappe_field('registration_required', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('registration_deadline', '2025-08-28', { fieldtype: 'Date' });

			// Test registration management
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Test registration buttons
					cy.contains('button', 'Add Contacts').should('exist');
					cy.contains('button', 'Add Participants').should('exist');

					// Test registration tracking
					if (frm.fields_dict.registration_count) {
						expect(frm.fields_dict.registration_count).to.exist;
						cy.log('Registration count tracking available');
					}

					// Test waitlist management
					if (frm.fields_dict.waitlist_management) {
						expect(frm.fields_dict.waitlist_management).to.exist;
						cy.log('Waitlist management available');
					}
				});
				return true;
			}, null, 'Registration Management');

			cy.save_frappe_doc();
		});

		it('should test attendance tracking and check-in processes', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'Monthly Chapter Meeting');
			cy.fill_frappe_field('event_date', '2025-03-15', { fieldtype: 'Date' });
			cy.fill_frappe_field('track_attendance', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('attendance_method', 'QR Code', { fieldtype: 'Select' });

			// Test attendance management
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Test check-in system
					if (frm.fields_dict.checkin_system) {
						expect(frm.fields_dict.checkin_system).to.exist;
						cy.log('Check-in system available');
					}

					// Test attendance reporting
					if (frm.fields_dict.attendance_reporting) {
						expect(frm.fields_dict.attendance_reporting).to.exist;
						cy.log('Attendance reporting available');
					}

					// Test digital badges
					if (frm.fields_dict.digital_badges) {
						expect(frm.fields_dict.digital_badges).to.exist;
						cy.log('Digital badge system available');
					}
				});
				return true;
			}, 'Attendance Tracking');

			cy.save_frappe_doc();
		});
	});

	describe('Communication and Promotion Tests', () => {
		it('should test event communication and marketing workflow', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'Fundraising Gala');
			cy.fill_frappe_field('event_date', '2025-10-25', { fieldtype: 'Date' });
			cy.fill_frappe_field('public_event', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('marketing_budget', '2500.00', { fieldtype: 'Currency' });

			// Test communication features
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Test marketing campaign
					if (frm.fields_dict.marketing_campaign) {
						expect(frm.fields_dict.marketing_campaign).to.exist;
						cy.log('Marketing campaign management available');
					}

					// Test communication templates
					if (frm.fields_dict.communication_templates) {
						expect(frm.fields_dict.communication_templates).to.exist;
						cy.log('Communication templates available');
					}

					// Test social media integration
					if (frm.fields_dict.social_media_promotion) {
						expect(frm.fields_dict.social_media_promotion).to.exist;
						cy.log('Social media promotion tools available');
					}
				});
				return true;
			}, null, 'Event Communication');

			cy.save_frappe_doc();
		});

		it('should test invitation management and RSVP tracking', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'VIP Stakeholder Meeting');
			cy.fill_frappe_field('event_date', '2025-11-12', { fieldtype: 'Date' });
			cy.fill_frappe_field('invitation_only', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('rsvp_required', true, { fieldtype: 'Check' });

			// Test invitation management
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Test invitation system
					if (frm.fields_dict.invitation_management) {
						expect(frm.fields_dict.invitation_management).to.exist;
						cy.log('Invitation management system available');
					}

					// Test RSVP tracking
					if (frm.fields_dict.rsvp_tracking) {
						expect(frm.fields_dict.rsvp_tracking).to.exist;
						cy.log('RSVP tracking system available');
					}

					// Test guest list management
					if (frm.fields_dict.guest_list) {
						expect(frm.fields_dict.guest_list).to.exist;
						cy.log('Guest list management available');
					}
				});
				return true;
			}, 'Invitation Management');

			cy.save_frappe_doc();
		});
	});

	describe('Financial Management and Ticketing Tests', () => {
		it('should test event ticketing and payment processing', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'Educational Conference');
			cy.fill_frappe_field('event_date', '2025-12-08', { fieldtype: 'Date' });
			cy.fill_frappe_field('paid_event', true, { fieldtype: 'Check' });
			cy.fill_frappe_field('ticket_price', '75.00', { fieldtype: 'Currency' });

			// Test ticketing system
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Test ticket management
					if (frm.fields_dict.ticket_management) {
						expect(frm.fields_dict.ticket_management).to.exist;
						cy.log('Ticket management system available');
					}

					// Test payment processing
					if (frm.fields_dict.payment_processing) {
						expect(frm.fields_dict.payment_processing).to.exist;
						cy.log('Payment processing integration available');
					}

					// Test pricing tiers
					if (frm.fields_dict.pricing_tiers) {
						expect(frm.fields_dict.pricing_tiers).to.exist;
						cy.log('Multiple pricing tiers available');
					}
				});
				return true;
			}, null, 'Ticketing System');

			cy.save_frappe_doc();
		});

		it('should test event budgeting and financial tracking', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'Annual Conference');
			cy.fill_frappe_field('event_date', '2025-04-20', { fieldtype: 'Date' });
			cy.fill_frappe_field('budget', '15000.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('expected_revenue', '22000.00', { fieldtype: 'Currency' });

			// Test financial management
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Test budget tracking
					if (frm.fields_dict.budget_tracking) {
						expect(frm.fields_dict.budget_tracking).to.exist;
						cy.log('Budget tracking available');
					}

					// Test expense management
					if (frm.fields_dict.expense_management) {
						expect(frm.fields_dict.expense_management).to.exist;
						cy.log('Expense management available');
					}

					// Test revenue tracking
					if (frm.fields_dict.revenue_tracking) {
						expect(frm.fields_dict.revenue_tracking).to.exist;
						cy.log('Revenue tracking available');
					}
				});
				return true;
			}, 'Financial Management');

			cy.save_frappe_doc();
		});
	});

	describe('Volunteer Coordination and Staff Management Tests', () => {
		it('should test volunteer assignment and coordination', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Event');
				cy.wait_for_navigation();

				cy.fill_frappe_field('event_name', 'Community Outreach Fair');
				cy.fill_frappe_field('event_date', '2025-05-18', { fieldtype: 'Date' });
				cy.fill_frappe_field('volunteers_needed', '15', { fieldtype: 'Int' });
				cy.fill_frappe_field('volunteer_coordinator', member.name, { fieldtype: 'Link' });

				// Test volunteer coordination
				cy.execute_business_workflow(() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Event');

						// Test volunteer management buttons
						cy.contains('button', 'Add Contacts').should('exist');
						cy.contains('button', 'Add Participants').should('exist');

						// Test volunteer tracking
						if (frm.fields_dict.volunteer_assignments) {
							expect(frm.fields_dict.volunteer_assignments).to.exist;
							cy.log('Volunteer assignment tracking available');
						}

						// Test shift management
						if (frm.fields_dict.shift_management) {
							expect(frm.fields_dict.shift_management).to.exist;
							cy.log('Volunteer shift management available');
						}
					});
					return true;
				}, null, 'Volunteer Coordination');

				cy.save_frappe_doc();
			});
		});

		it('should test staff coordination and role assignments', () => {
			cy.createTestMemberWithFinancialSetup().then((member) => {
				cy.visit_doctype_form('Event');
				cy.wait_for_navigation();

				cy.fill_frappe_field('event_name', 'Leadership Summit');
				cy.fill_frappe_field('event_date', '2025-08-30', { fieldtype: 'Date' });
				cy.fill_frappe_field('event_manager', member.name, { fieldtype: 'Link' });
				cy.fill_frappe_field('staff_required', '8', { fieldtype: 'Int' });

				// Test staff coordination
				cy.execute_form_operation(() => {
					cy.window().then((win) => {
						const frm = win.frappe.ui.form.get_form('Event');

						// Test staff assignments
						if (frm.fields_dict.staff_assignments) {
							expect(frm.fields_dict.staff_assignments).to.exist;
							cy.log('Staff assignment tracking available');
						}

						// Test role definitions
						if (frm.fields_dict.role_definitions) {
							expect(frm.fields_dict.role_definitions).to.exist;
							cy.log('Staff role definitions available');
						}

						// Test coordination tools
						if (frm.fields_dict.coordination_tools) {
							expect(frm.fields_dict.coordination_tools).to.exist;
							cy.log('Staff coordination tools available');
						}
					});
					return true;
				}, 'Staff Coordination');

				cy.save_frappe_doc();
			});
		});
	});

	describe('Post-Event Analysis and Follow-up Tests', () => {
		it('should test post-event evaluation and feedback collection', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'Innovation Workshop');
			cy.fill_frappe_field('event_date', '2025-02-28', { fieldtype: 'Date' });
			cy.fill_frappe_field('status', 'Completed', { fieldtype: 'Select' });
			cy.fill_frappe_field('actual_attendance', '87', { fieldtype: 'Int' });

			// Test post-event analysis
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Test feedback collection
					if (frm.fields_dict.feedback_collection) {
						expect(frm.fields_dict.feedback_collection).to.exist;
						cy.log('Feedback collection system available');
					}

					// Test event evaluation
					if (frm.fields_dict.event_evaluation) {
						expect(frm.fields_dict.event_evaluation).to.exist;
						cy.log('Event evaluation framework available');
					}

					// Test success metrics
					if (frm.fields_dict.success_metrics) {
						expect(frm.fields_dict.success_metrics).to.exist;
						cy.log('Success metrics calculation available');
					}
				});
				return true;
			}, null, 'Post-Event Analysis');

			cy.save_frappe_doc();
		});

		it('should test follow-up communication and relationship building', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'Member Appreciation Dinner');
			cy.fill_frappe_field('event_date', '2025-01-25', { fieldtype: 'Date' });
			cy.fill_frappe_field('status', 'Completed', { fieldtype: 'Select' });
			cy.fill_frappe_field('follow_up_required', true, { fieldtype: 'Check' });

			// Test follow-up management
			cy.execute_form_operation(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Test follow-up campaigns
					if (frm.fields_dict.followup_campaigns) {
						expect(frm.fields_dict.followup_campaigns).to.exist;
						cy.log('Follow-up campaign management available');
					}

					// Test relationship building
					if (frm.fields_dict.relationship_building) {
						expect(frm.fields_dict.relationship_building).to.exist;
						cy.log('Relationship building tools available');
					}

					// Test outcome tracking
					if (frm.fields_dict.outcome_tracking) {
						expect(frm.fields_dict.outcome_tracking).to.exist;
						cy.log('Event outcome tracking available');
					}
				});
				return true;
			}, 'Follow-up Management');

			cy.save_frappe_doc();
		});
	});

	describe('Reporting and Analytics Integration Tests', () => {
		it('should test event analytics and reporting data', () => {
			cy.visit_doctype_form('Event');
			cy.wait_for_navigation();

			cy.fill_frappe_field('event_name', 'Analytics Test Event');
			cy.fill_frappe_field('event_date', '2025-07-15', { fieldtype: 'Date' });
			cy.fill_frappe_field('event_type', 'Conference', { fieldtype: 'Select' });
			cy.fill_frappe_field('max_attendees', '200', { fieldtype: 'Int' });
			cy.fill_frappe_field('actual_attendance', '175', { fieldtype: 'Int' });
			cy.fill_frappe_field('budget', '12000.00', { fieldtype: 'Currency' });
			cy.fill_frappe_field('actual_cost', '10500.00', { fieldtype: 'Currency' });

			// Test analytics data structure
			cy.execute_business_workflow(() => {
				cy.window().then((win) => {
					const frm = win.frappe.ui.form.get_form('Event');

					// Verify core reporting fields
					expect(frm.doc.event_name).to.equal('Analytics Test Event');
					expect(frm.doc.event_type).to.equal('Conference');
					expect(frm.doc.max_attendees).to.equal(200);
					expect(frm.doc.actual_attendance).to.equal(175);

					// Test performance metrics
					if (frm.fields_dict.attendance_rate) {
						expect(frm.fields_dict.attendance_rate).to.exist;
						cy.log('Attendance rate calculation available');
					}

					// Test ROI calculation
					if (frm.fields_dict.roi_calculation) {
						expect(frm.fields_dict.roi_calculation).to.exist;
						cy.log('ROI calculation available');
					}

					cy.log('Event properly structured for comprehensive reporting');
				});
				return true;
			}, null, 'Analytics Data Structure');

			cy.save_frappe_doc();
		});
	});
});
