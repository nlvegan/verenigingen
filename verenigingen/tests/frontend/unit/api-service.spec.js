describe('API Service', () => {
	let mockFrappe;

	beforeEach(() => {
		// Mock frappe.call
		mockFrappe = {
			call: jest.fn(),
			show_alert: jest.fn(),
			msgprint: jest.fn(),
			throw: jest.fn()
		};
		global.frappe = mockFrappe;
		global.__ = (str) => str;
	});

	// Mock API service functions
	const apiService = {
		async callAPI(method, args = {}) {
			try {
				const response = await frappe.call({
					method: method,
					args: args,
					freeze: true,
					freeze_message: __('Loading...')
				});
				return response.message;
			} catch (error) {
				frappe.msgprint({
					title: __('Error'),
					indicator: 'red',
					message: error.message || __('An error occurred')
				});
				throw error;
			}
		},

		async submitMembershipApplication(data) {
			return this.callAPI('verenigingen.api.membership_application.submit_application', { data });
		},

		async updateMemberStatus(memberName, status) {
			return this.callAPI('verenigingen.api.member.update_status', {
				member: memberName,
				status: status
			});
		},

		async createVolunteerExpense(expenseData) {
			return this.callAPI('verenigingen.api.volunteer.create_expense', {
				expense_data: expenseData
			});
		}
	};

	describe('callAPI', () => {
		it('should make successful API calls', async () => {
			const mockResponse = { message: { success: true, id: 'TEST-001' } };
			mockFrappe.call.mockResolvedValue(mockResponse);

			const result = await apiService.callAPI('test.method', { param: 'value' });

			expect(mockFrappe.call).toHaveBeenCalledWith({
				method: 'test.method',
				args: { param: 'value' },
				freeze: true,
				freeze_message: 'Loading...'
			});
			expect(result).toEqual(mockResponse.message);
		});

		it('should handle API errors', async () => {
			const error = new Error('API Error');
			mockFrappe.call.mockRejectedValue(error);

			await expect(apiService.callAPI('test.method')).rejects.toThrow('API Error');

			expect(mockFrappe.msgprint).toHaveBeenCalledWith({
				title: 'Error',
				indicator: 'red',
				message: 'API Error'
			});
		});

		it('should use default error message when none provided', async () => {
			const error = new Error();
			mockFrappe.call.mockRejectedValue(error);

			await expect(apiService.callAPI('test.method')).rejects.toThrow();

			expect(mockFrappe.msgprint).toHaveBeenCalledWith({
				title: 'Error',
				indicator: 'red',
				message: 'An error occurred'
			});
		});
	});

	describe('submitMembershipApplication', () => {
		it('should submit application with correct parameters', async () => {
			const applicationData = {
				first_name: 'John',
				last_name: 'Doe',
				email: 'john.doe@example.com'
			};

			mockFrappe.call.mockResolvedValue({ message: { success: true, member_id: 'MEM-001' } });

			const result = await apiService.submitMembershipApplication(applicationData);

			expect(mockFrappe.call).toHaveBeenCalledWith({
				method: 'verenigingen.api.membership_application.submit_application',
				args: { data: applicationData },
				freeze: true,
				freeze_message: 'Loading...'
			});
			expect(result.member_id).toBe('MEM-001');
		});
	});

	describe('updateMemberStatus', () => {
		it('should update member status', async () => {
			mockFrappe.call.mockResolvedValue({ message: { success: true } });

			await apiService.updateMemberStatus('MEM-001', 'Active');

			expect(mockFrappe.call).toHaveBeenCalledWith({
				method: 'verenigingen.api.member.update_status',
				args: {
					member: 'MEM-001',
					status: 'Active'
				},
				freeze: true,
				freeze_message: 'Loading...'
			});
		});
	});

	describe('createVolunteerExpense', () => {
		it('should create volunteer expense', async () => {
			const expenseData = {
				amount: 50.00,
				description: 'Travel expense',
				date: '2024-01-15'
			};

			mockFrappe.call.mockResolvedValue({
				message: { success: true, expense_id: 'EXP-001' }
			});

			const result = await apiService.createVolunteerExpense(expenseData);

			expect(mockFrappe.call).toHaveBeenCalledWith({
				method: 'verenigingen.api.volunteer.create_expense',
				args: { expense_data: expenseData },
				freeze: true,
				freeze_message: 'Loading...'
			});
			expect(result.expense_id).toBe('EXP-001');
		});
	});
});
