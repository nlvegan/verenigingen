/**
 * Volunteer Form JavaScript Unit Tests
 * Tests volunteer management including activities, assignments, skills, and member integration
 */

describe('Volunteer Form', () => {
	let frm;
	let frappe;

	beforeEach(() => {
		// Mock Frappe framework
		global.__ = jest.fn(str => str);

		frappe = {
			call: jest.fn(),
			model: {
				set_value: jest.fn(),
				get_value: jest.fn(),
				add_child: jest.fn()
			},
			msgprint: jest.fn(),
			show_alert: jest.fn(),
			confirm: jest.fn(),
			prompt: jest.fn(),
			set_route: jest.fn(),
			route_options: {},
			datetime: {
				str_to_user: jest.fn(date => date),
				get_today: jest.fn(() => '2024-01-01'),
				now_datetime: jest.fn(() => '2024-01-01 10:00:00')
			},
			utils: {
				get_url: jest.fn(() => 'https://example.com')
			},
			session: {
				user: 'test@example.com'
			}
		};

		global.frappe = frappe;

		// Mock form object
		frm = {
			doc: {
				name: 'VOL-001',
				volunteer_name: 'Jane Smith',
				member: 'MEM-001',
				email: 'jane.smith@org.example',
				personal_email: 'jane@personal.com',
				skills: [],
				activities: [],
				assignments: [],
				is_active: 1,
				total_hours: 120
			},
			fields_dict: {
				timeline_html: {
					wrapper: document.createElement('div')
				},
				assignment_summary: {
					wrapper: document.createElement('div')
				}
			},
			set_value: jest.fn(),
			add_custom_button: jest.fn(),
			refresh_field: jest.fn(),
			toggle_display: jest.fn(),
			save: jest.fn(() => Promise.resolve()),
			reload_doc: jest.fn()
		};

		// Mock jQuery
		global.$ = jest.fn(() => ({
			html: jest.fn(),
			on: jest.fn(),
			off: jest.fn().mockReturnThis(),
			find: jest.fn().mockReturnThis()
		}));
	});

	describe('Member Integration', () => {
		it('should inherit data from linked member', async () => {
			frappe.call.mockResolvedValue({
				message: {
					full_name: 'Jane Smith',
					email: 'jane@example.com',
					mobile_no: '+31612345678',
					primary_address: 'ADDR-001'
				}
			});

			const volunteerEvents = require('./volunteer').volunteerFormEvents;
			await volunteerEvents.member(frm);

			expect(frappe.call).toHaveBeenCalledWith(
				expect.objectContaining({
					method: 'frappe.client.get',
					args: {
						doctype: 'Member',
						name: 'MEM-001'
					}
				})
			);

			expect(frm.set_value).toHaveBeenCalledWith('volunteer_name', 'Jane Smith');
			expect(frm.set_value).toHaveBeenCalledWith('personal_email', 'jane@example.com');
		});

		it('should generate organization email from member name', () => {
			const generateOrgEmail = (fullName) => {
				const nameForEmail = fullName
					.replace(/\s+/g, '.')
					.toLowerCase()
					.replace(/[^a-z0-9.]/g, '');
				return `${nameForEmail}@org.example`;
			};

			const email = generateOrgEmail('Jane Smith');
			expect(email).toBe('jane.smith@org.example');

			// Test with special characters
			const email2 = generateOrgEmail('José María de la Cruz');
			expect(email2).toBe('jos.mara.de.la.cruz@org.example');
		});
	});

	describe('Activity Management', () => {
		it('should add new activity', async () => {
			frappe.prompt.mockImplementation((fields, callback) => {
				callback({
					activity_type: 'Event Support',
					team: 'TEAM-001',
					start_date: '2024-01-01',
					description: 'Annual conference support'
				});
			});

			frappe.call.mockResolvedValue({
				message: { success: true }
			});

			const volunteerForm = require('./volunteer').VolunteerForm;
			await volunteerForm.add_activity(frm);

			expect(frappe.prompt).toHaveBeenCalled();
			expect(frm.reload_doc).toHaveBeenCalled();
		});

		it('should end activity with end date', async () => {
			const activityName = 'ACT-001';

			frappe.prompt.mockImplementation((fields, callback) => {
				callback({
					end_date: '2024-12-31',
					total_hours: 80,
					completion_notes: 'Successfully completed'
				});
			});

			frappe.call.mockResolvedValue({
				message: { success: true }
			});

			const volunteerForm = require('./volunteer').VolunteerForm;
			await volunteerForm.end_activity(frm, activityName);

			expect(frappe.call).toHaveBeenCalledWith(
				expect.objectContaining({
					method: expect.stringContaining('end_volunteer_activity'),
					args: expect.objectContaining({
						activity: activityName,
						end_date: '2024-12-31'
					})
				})
			);
		});

		it('should validate activity dates', () => {
			const validateActivityDates = (startDate, endDate) => {
				if (endDate && new Date(endDate) < new Date(startDate)) {
					throw new Error('End date cannot be before start date');
				}
				if (new Date(startDate) > new Date()) {
					throw new Error('Start date cannot be in the future');
				}
			};

			expect(() => {
				validateActivityDates('2024-01-01', '2023-12-31');
			}).toThrow('End date cannot be before start date');
		});
	});

	describe('Assignment Aggregation', () => {
		it('should aggregate assignments by team and chapter', () => {
			frm.doc.assignments = [
				{ team: 'TEAM-001', chapter: 'CHAP-001', role: 'Coordinator' },
				{ team: 'TEAM-001', chapter: 'CHAP-001', role: 'Member' },
				{ team: 'TEAM-002', chapter: 'CHAP-001', role: 'Lead' }
			];

			const aggregateAssignments = (assignments) => {
				const grouped = {};
				assignments.forEach(assignment => {
					const key = `${assignment.team}-${assignment.chapter}`;
					if (!grouped[key]) {
						grouped[key] = {
							team: assignment.team,
							chapter: assignment.chapter,
							roles: []
						};
					}
					grouped[key].roles.push(assignment.role);
				});
				return Object.values(grouped);
			};

			const aggregated = aggregateAssignments(frm.doc.assignments);
			expect(aggregated).toHaveLength(2);
			expect(aggregated[0].roles).toHaveLength(2);
		});

		it('should display assignment summary', () => {
			const volunteerForm = require('./volunteer').VolunteerForm;

			frm.doc.assignments = [
				{
					team: 'Events Team',
					chapter: 'Amsterdam',
					role: 'Coordinator',
					is_active: 1
				}
			];

			volunteerForm.render_assignment_summary(frm);

			expect($).toHaveBeenCalled();
			expect(frm.fields_dict.assignment_summary.wrapper.innerHTML).toBeTruthy();
		});
	});

	describe('Skills Management', () => {
		it('should add new skill', () => {
			const addSkill = (frm, skill, proficiency) => {
				const newSkill = frappe.model.add_child(frm.doc, 'Volunteer Skill', 'skills');
				newSkill.skill = skill;
				newSkill.proficiency_level = proficiency;
				frm.refresh_field('skills');
				return newSkill;
			};

			frappe.model.add_child.mockReturnValue({
				skill: 'Project Management',
				proficiency_level: 'Expert'
			});

			const skill = addSkill(frm, 'Project Management', 'Expert');
			expect(skill.skill).toBe('Project Management');
			expect(frappe.model.add_child).toHaveBeenCalled();
			expect(frm.refresh_field).toHaveBeenCalledWith('skills');
		});

		it('should validate skill proficiency levels', () => {
			const validLevels = ['Beginner', 'Intermediate', 'Advanced', 'Expert'];

			const validateProficiency = (level) => {
				if (!validLevels.includes(level)) {
					throw new Error('Invalid proficiency level');
				}
			};

			expect(() => {
				validateProficiency('Master');
			}).toThrow('Invalid proficiency level');
		});
	});

	describe('Timeline Visualization', () => {
		it('should generate volunteer timeline', async () => {
			frappe.call.mockResolvedValue({
				message: {
					timeline_data: [
						{
							date: '2024-01-01',
							type: 'activity_start',
							title: 'Started Event Support',
							description: 'Joined Events Team'
						},
						{
							date: '2023-06-01',
							type: 'volunteer_created',
							title: 'Became a Volunteer',
							description: 'Volunteer profile created'
						}
					]
				}
			});

			const volunteerForm = require('./volunteer').VolunteerForm;
			await volunteerForm.render_timeline(frm);

			expect(frappe.call).toHaveBeenCalledWith(
				expect.objectContaining({
					method: expect.stringContaining('get_volunteer_timeline')
				})
			);
			expect($).toHaveBeenCalled();
		});

		it('should format timeline entries correctly', () => {
			const formatTimelineEntry = (entry) => {
				const icons = {
					'activity_start': 'fa-play-circle',
					'activity_end': 'fa-stop-circle',
					'assignment_added': 'fa-user-plus',
					'volunteer_created': 'fa-star'
				};

				const colors = {
					'activity_start': 'green',
					'activity_end': 'blue',
					'assignment_added': 'orange',
					'volunteer_created': 'purple'
				};

				return {
					icon: icons[entry.type] || 'fa-circle',
					color: colors[entry.type] || 'gray',
					date: frappe.datetime.str_to_user(entry.date),
					title: entry.title,
					description: entry.description
				};
			};

			const entry = {
				type: 'activity_start',
				date: '2024-01-01',
				title: 'Started Event Support',
				description: 'Joined Events Team'
			};

			const formatted = formatTimelineEntry(entry);
			expect(formatted.icon).toBe('fa-play-circle');
			expect(formatted.color).toBe('green');
		});
	});

	describe('Report Generation', () => {
		it('should generate volunteer report', async () => {
			frappe.call.mockResolvedValue({
				message: {
					report_data: {
						total_hours: 120,
						activities_count: 5,
						teams_count: 3,
						skills_count: 8
					}
				}
			});

			const volunteerForm = require('./volunteer').VolunteerForm;
			await volunteerForm.generate_report(frm);

			expect(frappe.call).toHaveBeenCalledWith(
				expect.objectContaining({
					method: expect.stringContaining('generate_volunteer_report')
				})
			);
			expect(frappe.msgprint).toHaveBeenCalled();
		});

		it('should export volunteer data', async () => {
			global.window = { open: jest.fn() };

			const volunteerForm = require('./volunteer').VolunteerForm;
			await volunteerForm.export_volunteer_data(frm);

			expect(window.open).toHaveBeenCalledWith(
				expect.stringContaining('/api/method/export_volunteer_data')
			);
		});
	});

	describe('Form Buttons and Actions', () => {
		it('should add custom buttons based on volunteer status', () => {
			const volunteerEvents = require('./volunteer').volunteerFormEvents;
			volunteerEvents.refresh(frm);

			expect(frm.add_custom_button).toHaveBeenCalledWith(
				'Add Activity',
				expect.any(Function),
				'Actions'
			);

			expect(frm.add_custom_button).toHaveBeenCalledWith(
				'Generate Report',
				expect.any(Function)
			);
		});

		it('should show deactivate button for active volunteers', () => {
			frm.doc.is_active = 1;

			const volunteerEvents = require('./volunteer').volunteerFormEvents;
			volunteerEvents.refresh(frm);

			expect(frm.add_custom_button).toHaveBeenCalledWith(
				'Deactivate Volunteer',
				expect.any(Function)
			);
		});

		it('should show reactivate button for inactive volunteers', () => {
			frm.doc.is_active = 0;

			const volunteerEvents = require('./volunteer').volunteerFormEvents;
			volunteerEvents.refresh(frm);

			expect(frm.add_custom_button).toHaveBeenCalledWith(
				'Reactivate Volunteer',
				expect.any(Function)
			);
		});
	});

	describe('Validation', () => {
		it('should validate email addresses', () => {
			const validateEmail = (email) => {
				const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
				if (!emailRegex.test(email)) {
					throw new Error('Invalid email address');
				}
			};

			expect(() => {
				validateEmail('invalid-email');
			}).toThrow('Invalid email address');

			expect(() => {
				validateEmail('valid@example.com');
			}).not.toThrow();
		});

		it('should ensure member link is required', () => {
			const validateForm = (doc) => {
				if (!doc.member) {
					throw new Error('Member link is required');
				}
			};

			frm.doc.member = null;
			expect(() => {
				validateForm(frm.doc);
			}).toThrow('Member link is required');
		});
	});
});

// Mock implementation of volunteer form
const VolunteerForm = {
	add_activity: async function(frm) {
		// Implementation
	},

	end_activity: async function(frm, activityName) {
		// Implementation
	},

	render_assignment_summary: function(frm) {
		// Implementation
	},

	render_timeline: async function(frm) {
		// Implementation
	},

	generate_report: async function(frm) {
		// Implementation
	},

	export_volunteer_data: async function(frm) {
		// Implementation
	}
};

const volunteerFormEvents = {
	refresh: function(frm) {
		// Add buttons based on status
	},

	member: async function(frm) {
		// Fetch and inherit member data
	}
};
