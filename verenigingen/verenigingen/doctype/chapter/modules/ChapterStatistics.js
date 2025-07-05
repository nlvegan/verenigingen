// verenigingen/verenigingen/doctype/chapter/modules/ChapterStatistics.js

import { ChapterAPI } from '../utils/ChapterAPI.js';

export class ChapterStatistics {
    constructor(frm, state) {
        this.frm = frm;
        this.state = state;
        this.api = new ChapterAPI();
        this.charts = new Map();
    }

    addButtons() {
        this.frm.add_custom_button(__('Chapter Statistics'), () => this.showStatisticsDialog(), __('View'));
        this.frm.add_custom_button(__('Growth Report'), () => this.showGrowthReport(), __('View'));
        this.frm.add_custom_button(__('Activity Dashboard'), () => this.showActivityDashboard(), __('View'));
        this.frm.add_custom_button(__('Export Analytics'), () => this.exportAnalytics(), __('Actions'));
    }

    async showStatisticsDialog() {
        try {
            this.state.setLoading('statistics', true);

            // Fetch statistics data
            const stats = await this.fetchChapterStatistics();

            const dialog = new frappe.ui.Dialog({
                title: __('Chapter Statistics - {0}', [this.frm.doc.name]),
                size: 'extra-large',
                fields: [{
                    fieldtype: 'HTML',
                    options: this.generateStatisticsHTML(stats)
                }],
                primary_action_label: __('Refresh'),
                primary_action: async () => {
                    await this.refreshStatistics(dialog);
                }
            });

            dialog.show();

            // Initialize charts after dialog is shown
            setTimeout(() => this.initializeCharts(dialog, stats), 100);

        } catch (error) {
            frappe.msgprint(__('Error loading statistics: {0}', [error.message]));
        } finally {
            this.state.setLoading('statistics', false);
        }
    }

    async fetchChapterStatistics() {
        const [basicStats, membershipStats, activityStats, boardStats] = await Promise.all([
            this.getBasicStatistics(),
            this.getMembershipStatistics(),
            this.getActivityStatistics(),
            this.getBoardStatistics()
        ]);

        return {
            ...basicStats,
            ...membershipStats,
            ...activityStats,
            ...boardStats,
            lastUpdated: frappe.datetime.now_datetime()
        };
    }

    async getBasicStatistics() {
        // Get member counts from Chapter Member table
        const chapterMemberIds = await this.getChapterMemberIds();
        const totalMembers = chapterMemberIds.length;

        const activeMembers = await this.api.getCount('Member', {
            name: ['in', chapterMemberIds],
            status: 'Active'
        });

        // Get board member count
        const boardMemberCount = this.frm.doc.board_members?.filter(m => m.is_active).length || 0;

        // Get recent members (last 30 days) - need to query Chapter Members added recently
        const thirtyDaysAgo = frappe.datetime.add_days(frappe.datetime.nowdate(), -30);
        const recentMembers = await this.api.getCount('Member', {
            name: ['in', chapterMemberIds],
            creation: ['>=', thirtyDaysAgo]
        });

        return {
            totalMembers,
            activeMembers,
            inactiveMembers: totalMembers - activeMembers,
            boardMemberCount,
            recentMembers,
            memberRetentionRate: totalMembers > 0 ? ((activeMembers / totalMembers) * 100).toFixed(1) : 0
        };
    }

    async getMembershipStatistics() {
        // Get membership type distribution
        const membershipTypes = await this.api.call(
            'frappe.desk.reportview.get_list',
            {
                doctype: 'Membership',
                fields: ['membership_type', 'count(name) as count'],
                filters: {
                    member: ['in', await this.getChapterMemberIds()],
                    status: 'Active'
                },
                group_by: 'membership_type'
            }
        );

        // Get membership status distribution
        const membershipStatuses = await this.api.call(
            'frappe.desk.reportview.get_list',
            {
                doctype: 'Membership',
                fields: ['status', 'count(name) as count'],
                filters: {
                    member: ['in', await this.getChapterMemberIds()]
                },
                group_by: 'status'
            }
        );

        return {
            membershipTypes: membershipTypes || [],
            membershipStatuses: membershipStatuses || []
        };
    }

    async getActivityStatistics() {
        const memberIds = await this.getChapterMemberIds();

        // Get event attendance (if events module exists)
        let eventAttendance = 0;
        try {
            eventAttendance = await this.api.getCount('Event Participant', {
                participant: ['in', memberIds],
                participation_status: 'Present'
            });
        } catch (e) {
            // Events module might not exist
        }

        // Get volunteer hours (if volunteer module exists)
        let volunteerHours = 0;
        try {
            const volunteerData = await this.api.call(
                'frappe.desk.reportview.get_list',
                {
                    doctype: 'Volunteer Activity',
                    fields: ['sum(hours) as total_hours'],
                    filters: {
                        volunteer: ['in', await this.getChapterVolunteerIds()]
                    }
                }
            );
            volunteerHours = volunteerData?.[0]?.total_hours || 0;
        } catch (e) {
            // Volunteer module might not exist
        }

        // Get communication count
        const communicationCount = await this.api.getCount('Communication', {
            reference_doctype: 'Chapter',
            reference_name: this.frm.doc.name
        });

        return {
            eventAttendance,
            volunteerHours,
            communicationCount,
            engagementScore: this.calculateEngagementScore(eventAttendance, volunteerHours, communicationCount)
        };
    }

    async getBoardStatistics() {
        const boardMembers = this.frm.doc.board_members || [];

        // Role distribution
        const roleDistribution = {};
        boardMembers.forEach(member => {
            if (member.is_active && member.chapter_role) {
                roleDistribution[member.chapter_role] = (roleDistribution[member.chapter_role] || 0) + 1;
            }
        });

        // Average tenure
        let totalTenure = 0;
        let tenureCount = 0;

        boardMembers.forEach(member => {
            if (member.from_date) {
                const endDate = member.to_date || frappe.datetime.nowdate();
                const tenure = frappe.datetime.get_day_diff(endDate, member.from_date);
                totalTenure += tenure;
                tenureCount++;
            }
        });

        const averageTenure = tenureCount > 0 ? Math.round(totalTenure / tenureCount) : 0;

        return {
            roleDistribution,
            averageTenure,
            boardTurnoverRate: this.calculateBoardTurnoverRate(boardMembers)
        };
    }

    calculateEngagementScore(events, hours, communications) {
        // Simple engagement score calculation
        const eventPoints = events * 10;
        const hourPoints = hours * 5;
        const commPoints = communications * 2;

        const totalPoints = eventPoints + hourPoints + commPoints;
        const maxPoints = 1000; // Arbitrary max for scaling

        return Math.min(100, Math.round((totalPoints / maxPoints) * 100));
    }

    calculateBoardTurnoverRate(boardMembers) {
        const lastYear = frappe.datetime.add_days(frappe.datetime.nowdate(), -365);
        let changes = 0;

        boardMembers.forEach(member => {
            if ((member.from_date && member.from_date >= lastYear) ||
                (member.to_date && member.to_date >= lastYear)) {
                changes++;
            }
        });

        const totalPositions = boardMembers.filter(m => m.is_active).length || 1;
        return ((changes / totalPositions) * 100).toFixed(1);
    }

    generateStatisticsHTML(stats) {
        return `
            <div class="chapter-stats">
                <!-- Overview Section -->
                <div class="stats-section">
                    <h4>${__('Overview')}</h4>
                    <div class="row">
                        <div class="col-md-3 col-sm-6">
                            <div class="stat-item">
                                <div class="stat-number text-primary">${stats.totalMembers}</div>
                                <div class="stat-label">${__('Total Members')}</div>
                                <small class="text-muted">${stats.activeMembers} ${__('active')}</small>
                            </div>
                        </div>
                        <div class="col-md-3 col-sm-6">
                            <div class="stat-item">
                                <div class="stat-number text-success">${stats.recentMembers}</div>
                                <div class="stat-label">${__('New Members')}</div>
                                <small class="text-muted">${__('Last 30 days')}</small>
                            </div>
                        </div>
                        <div class="col-md-3 col-sm-6">
                            <div class="stat-item">
                                <div class="stat-number text-info">${stats.boardMemberCount}</div>
                                <div class="stat-label">${__('Board Members')}</div>
                                <small class="text-muted">${__('Currently active')}</small>
                            </div>
                        </div>
                        <div class="col-md-3 col-sm-6">
                            <div class="stat-item">
                                <div class="stat-number text-warning">${stats.memberRetentionRate}%</div>
                                <div class="stat-label">${__('Retention Rate')}</div>
                                <small class="text-muted">${__('Active/Total')}</small>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Charts Section -->
                <div class="stats-section mt-4">
                    <h4>${__('Analytics')}</h4>
                    <div class="row">
                        <div class="col-md-6">
                            <div class="chart-container">
                                <h5>${__('Member Status Distribution')}</h5>
                                <canvas id="member-status-chart" height="300"></canvas>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="chart-container">
                                <h5>${__('Membership Types')}</h5>
                                <canvas id="membership-type-chart" height="300"></canvas>
                            </div>
                        </div>
                    </div>
                    <div class="row mt-3">
                        <div class="col-md-6">
                            <div class="chart-container">
                                <h5>${__('Board Role Distribution')}</h5>
                                <canvas id="board-role-chart" height="300"></canvas>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="chart-container">
                                <h5>${__('Activity Metrics')}</h5>
                                <canvas id="activity-chart" height="300"></canvas>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Detailed Stats Section -->
                <div class="stats-section mt-4">
                    <h4>${__('Detailed Statistics')}</h4>
                    <div class="row">
                        <div class="col-md-6">
                            <table class="table table-bordered">
                                <tr>
                                    <td>${__('Average Board Tenure')}</td>
                                    <td class="text-right"><strong>${stats.averageTenure} ${__('days')}</strong></td>
                                </tr>
                                <tr>
                                    <td>${__('Board Turnover Rate')}</td>
                                    <td class="text-right"><strong>${stats.boardTurnoverRate}%</strong></td>
                                </tr>
                                <tr>
                                    <td>${__('Communications Sent')}</td>
                                    <td class="text-right"><strong>${stats.communicationCount}</strong></td>
                                </tr>
                                <tr>
                                    <td>${__('Engagement Score')}</td>
                                    <td class="text-right"><strong>${stats.engagementScore}/100</strong></td>
                                </tr>
                            </table>
                        </div>
                        <div class="col-md-6">
                            <table class="table table-bordered">
                                <tr>
                                    <td>${__('Event Attendance')}</td>
                                    <td class="text-right"><strong>${stats.eventAttendance}</strong></td>
                                </tr>
                                <tr>
                                    <td>${__('Volunteer Hours')}</td>
                                    <td class="text-right"><strong>${stats.volunteerHours}</strong></td>
                                </tr>
                                <tr>
                                    <td>${__('Active Members')}</td>
                                    <td class="text-right"><strong>${stats.activeMembers}</strong></td>
                                </tr>
                                <tr>
                                    <td>${__('Inactive Members')}</td>
                                    <td class="text-right"><strong>${stats.inactiveMembers}</strong></td>
                                </tr>
                            </table>
                        </div>
                    </div>
                </div>

                <div class="text-muted text-right mt-3">
                    <small>${__('Last updated')}: ${frappe.datetime.str_to_user(stats.lastUpdated)}</small>
                </div>
            </div>

            <style>
                .chapter-stats .stat-item {
                    text-align: center;
                    padding: 20px;
                    background: white;
                    border-radius: 4px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    margin-bottom: 15px;
                }
                .chapter-stats .stat-number {
                    font-size: 2.5em;
                    font-weight: bold;
                    line-height: 1;
                }
                .chapter-stats .stat-label {
                    color: #6c757d;
                    margin-top: 10px;
                    font-size: 0.9em;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                .chapter-stats .chart-container {
                    background: white;
                    padding: 20px;
                    border-radius: 4px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                    margin-bottom: 15px;
                }
                .chapter-stats .stats-section {
                    margin-bottom: 30px;
                }
                .chapter-stats h4 {
                    color: #333;
                    margin-bottom: 20px;
                    font-weight: 600;
                }
                .chapter-stats h5 {
                    color: #555;
                    margin-bottom: 15px;
                    font-size: 1.1em;
                }
            </style>
        `;
    }

    initializeCharts(dialog, stats) {
        // Member Status Chart
        this.createPieChart(
            dialog.$wrapper.find('#member-status-chart')[0],
            'memberStatus',
            {
                labels: [__('Active'), __('Inactive')],
                datasets: [{
                    data: [stats.activeMembers, stats.inactiveMembers],
                    backgroundColor: ['#28a745', '#dc3545']
                }]
            }
        );

        // Membership Type Chart
        if (stats.membershipTypes && stats.membershipTypes.length > 0) {
            this.createPieChart(
                dialog.$wrapper.find('#membership-type-chart')[0],
                'membershipType',
                {
                    labels: stats.membershipTypes.map(t => t.membership_type),
                    datasets: [{
                        data: stats.membershipTypes.map(t => t.count),
                        backgroundColor: this.generateColors(stats.membershipTypes.length)
                    }]
                }
            );
        }

        // Board Role Chart
        const roleLabels = Object.keys(stats.roleDistribution);
        if (roleLabels.length > 0) {
            this.createPieChart(
                dialog.$wrapper.find('#board-role-chart')[0],
                'boardRole',
                {
                    labels: roleLabels,
                    datasets: [{
                        data: roleLabels.map(role => stats.roleDistribution[role]),
                        backgroundColor: this.generateColors(roleLabels.length)
                    }]
                }
            );
        }

        // Activity Chart
        this.createBarChart(
            dialog.$wrapper.find('#activity-chart')[0],
            'activity',
            {
                labels: [__('Events'), __('Volunteer Hours'), __('Communications')],
                datasets: [{
                    label: __('Activity Metrics'),
                    data: [stats.eventAttendance, stats.volunteerHours, stats.communicationCount],
                    backgroundColor: ['#007bff', '#28a745', '#ffc107']
                }]
            }
        );
    }

    createPieChart(canvas, chartId, data) {
        if (!canvas || !window.Chart) return;

        const ctx = canvas.getContext('2d');
        const chart = new Chart(ctx, {
            type: 'pie',
            data: data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 15,
                            font: {
                                size: 12
                            }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((value / total) * 100).toFixed(1);
                                return `${label}: ${value} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });

        this.charts.set(chartId, chart);
    }

    createBarChart(canvas, chartId, data) {
        if (!canvas || !window.Chart) return;

        const ctx = canvas.getContext('2d');
        const chart = new Chart(ctx, {
            type: 'bar',
            data: data,
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });

        this.charts.set(chartId, chart);
    }

    generateColors(count) {
        const colors = [
            '#007bff', '#28a745', '#dc3545', '#ffc107', '#17a2b8',
            '#6610f2', '#e83e8c', '#fd7e14', '#20c997', '#6c757d'
        ];

        if (count <= colors.length) {
            return colors.slice(0, count);
        }

        // Generate additional random colors if needed
        const additionalColors = [];
        for (let i = colors.length; i < count; i++) {
            additionalColors.push(this.getRandomColor());
        }

        return [...colors, ...additionalColors];
    }

    getRandomColor() {
        const letters = '0123456789ABCDEF';
        let color = '#';
        for (let i = 0; i < 6; i++) {
            color += letters[Math.floor(Math.random() * 16)];
        }
        return color;
    }

    async refreshStatistics(dialog) {
        try {
            this.state.setLoading('refreshStats', true);

            // Clear existing charts
            this.charts.forEach(chart => chart.destroy());
            this.charts.clear();

            // Fetch fresh data
            const stats = await this.fetchChapterStatistics();

            // Update HTML
            dialog.fields[0].df.options = this.generateStatisticsHTML(stats);
            dialog.refresh();

            // Reinitialize charts
            setTimeout(() => this.initializeCharts(dialog, stats), 100);

            frappe.show_alert({
                message: __('Statistics refreshed'),
                indicator: 'green'
            }, 3);

        } catch (error) {
            frappe.msgprint(__('Error refreshing statistics: {0}', [error.message]));
        } finally {
            this.state.setLoading('refreshStats', false);
        }
    }

    async showGrowthReport() {
        try {
            this.state.setLoading('growthReport', true);

            const growthData = await this.fetchGrowthData();

            const dialog = new frappe.ui.Dialog({
                title: __('Chapter Growth Report - {0}', [this.frm.doc.name]),
                size: 'large',
                fields: [{
                    fieldtype: 'HTML',
                    options: this.generateGrowthReportHTML(growthData)
                }],
                primary_action_label: __('Export'),
                primary_action: () => {
                    this.exportGrowthReport(growthData);
                }
            });

            dialog.show();

            // Initialize growth chart
            setTimeout(() => this.initializeGrowthChart(dialog, growthData), 100);

        } catch (error) {
            frappe.msgprint(__('Error loading growth report: {0}', [error.message]));
        } finally {
            this.state.setLoading('growthReport', false);
        }
    }

    async fetchGrowthData() {
        const endDate = frappe.datetime.nowdate();
        const startDate = frappe.datetime.add_months(endDate, -12);

        // Get monthly member growth
        const monthlyGrowth = await this.api.call(
            'frappe.desk.reportview.get_list',
            {
                doctype: 'Member',
                fields: [
                    'DATE_FORMAT(creation, "%Y-%m") as month',
                    'count(name) as new_members'
                ],
                filters: {
                    name: ['in', await this.getChapterMemberIds()],
                    creation: ['between', [startDate, endDate]]
                },
                group_by: 'month',
                order_by: 'month'
            }
        );

        // Get monthly membership data
        const monthlyMemberships = await this.api.call(
            'frappe.desk.reportview.get_list',
            {
                doctype: 'Membership',
                fields: [
                    'DATE_FORMAT(start_date, "%Y-%m") as month',
                    'count(name) as new_memberships',
                    'sum(amount) as revenue'
                ],
                filters: {
                    member: ['in', await this.getChapterMemberIds()],
                    start_date: ['between', [startDate, endDate]]
                },
                group_by: 'month',
                order_by: 'month'
            }
        );

        return {
            monthlyGrowth: monthlyGrowth || [],
            monthlyMemberships: monthlyMemberships || [],
            startDate,
            endDate
        };
    }

    generateGrowthReportHTML(data) {
        return `
            <div class="growth-report">
                <div class="report-header mb-4">
                    <p class="text-muted">${__('Period')}: ${frappe.datetime.str_to_user(data.startDate)} - ${frappe.datetime.str_to_user(data.endDate)}</p>
                </div>

                <div class="chart-container mb-4">
                    <canvas id="growth-chart" height="300"></canvas>
                </div>

                <h5>${__('Monthly Breakdown')}</h5>
                <table class="table table-bordered">
                    <thead>
                        <tr>
                            <th>${__('Month')}</th>
                            <th>${__('New Members')}</th>
                            <th>${__('New Memberships')}</th>
                            <th>${__('Revenue')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${this.generateGrowthTableRows(data)}
                    </tbody>
                    <tfoot>
                        <tr class="font-weight-bold">
                            <td>${__('Total')}</td>
                            <td>${this.sumValues(data.monthlyGrowth, 'new_members')}</td>
                            <td>${this.sumValues(data.monthlyMemberships, 'new_memberships')}</td>
                            <td>${frappe.format_currency(this.sumValues(data.monthlyMemberships, 'revenue'))}</td>
                        </tr>
                    </tfoot>
                </table>
            </div>
        `;
    }

    generateGrowthTableRows(data) {
        const months = new Set();
        data.monthlyGrowth.forEach(d => months.add(d.month));
        data.monthlyMemberships.forEach(d => months.add(d.month));

        const sortedMonths = Array.from(months).sort();

        return sortedMonths.map(month => {
            const growth = data.monthlyGrowth.find(g => g.month === month) || {};
            const membership = data.monthlyMemberships.find(m => m.month === month) || {};

            return `
                <tr>
                    <td>${month}</td>
                    <td>${growth.new_members || 0}</td>
                    <td>${membership.new_memberships || 0}</td>
                    <td>${frappe.format_currency(membership.revenue || 0)}</td>
                </tr>
            `;
        }).join('');
    }

    sumValues(array, field) {
        return array.reduce((sum, item) => sum + (parseFloat(item[field]) || 0), 0);
    }

    initializeGrowthChart(dialog, data) {
        const canvas = dialog.$wrapper.find('#growth-chart')[0];
        if (!canvas || !window.Chart) return;

        const months = new Set();
        data.monthlyGrowth.forEach(d => months.add(d.month));
        data.monthlyMemberships.forEach(d => months.add(d.month));

        const sortedMonths = Array.from(months).sort();

        const ctx = canvas.getContext('2d');
        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: sortedMonths,
                datasets: [
                    {
                        label: __('New Members'),
                        data: sortedMonths.map(month => {
                            const growth = data.monthlyGrowth.find(g => g.month === month);
                            return growth ? growth.new_members : 0;
                        }),
                        borderColor: '#007bff',
                        backgroundColor: 'rgba(0, 123, 255, 0.1)',
                        tension: 0.1
                    },
                    {
                        label: __('New Memberships'),
                        data: sortedMonths.map(month => {
                            const membership = data.monthlyMemberships.find(m => m.month === month);
                            return membership ? membership.new_memberships : 0;
                        }),
                        borderColor: '#28a745',
                        backgroundColor: 'rgba(40, 167, 69, 0.1)',
                        tension: 0.1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });

        this.charts.set('growth', chart);
    }

    async showActivityDashboard() {
        try {
            this.state.setLoading('activityDashboard', true);

            const activityData = await this.fetchActivityData();

            const dialog = new frappe.ui.Dialog({
                title: __('Activity Dashboard - {0}', [this.frm.doc.name]),
                size: 'extra-large',
                fields: [{
                    fieldtype: 'HTML',
                    options: this.generateActivityDashboardHTML(activityData)
                }]
            });

            dialog.show();

            // Initialize activity timeline
            setTimeout(() => this.initializeActivityTimeline(dialog, activityData), 100);

        } catch (error) {
            frappe.msgprint(__('Error loading activity dashboard: {0}', [error.message]));
        } finally {
            this.state.setLoading('activityDashboard', false);
        }
    }

    async fetchActivityData() {
        const endDate = frappe.datetime.nowdate();
        const startDate = frappe.datetime.add_days(endDate, -90); // Last 90 days

        // Get recent activities
        const recentActivities = await this.getRecentActivities(startDate, endDate);

        // Get top contributors
        const topContributors = await this.getTopContributors();

        // Get upcoming events
        const upcomingEvents = await this.getUpcomingEvents();

        return {
            recentActivities,
            topContributors,
            upcomingEvents,
            activitySummary: this.generateActivitySummary(recentActivities)
        };
    }

    async getRecentActivities(startDate, endDate) {
        const activities = [];

        // Get new members from Chapter Member table
        const chapterMemberIds = await this.getChapterMemberIds();
        const newMembers = await this.api.getList('Member', {
            filters: {
                name: ['in', chapterMemberIds],
                creation: ['between', [startDate, endDate]]
            },
            fields: ['name', 'full_name', 'creation'],
            limit: 10,
            order_by: 'creation desc'
        });

        newMembers.forEach(member => {
            activities.push({
                type: 'new_member',
                title: __('New member joined'),
                description: member.full_name,
                date: member.creation,
                icon: 'fa-user-plus',
                color: 'green'
            });
        });

        // Get board changes
        const boardChanges = this.frm.doc.board_members?.filter(member => {
            const fromDate = frappe.datetime.str_to_obj(member.from_date);
            const compareStart = frappe.datetime.str_to_obj(startDate);
            return fromDate >= compareStart;
        }) || [];

        boardChanges.forEach(change => {
            activities.push({
                type: 'board_change',
                title: __('Board member added'),
                description: `${change.volunteer_name} - ${change.chapter_role}`,
                date: change.from_date,
                icon: 'fa-users',
                color: 'blue'
            });
        });

        // Sort by date
        activities.sort((a, b) => new Date(b.date) - new Date(a.date));

        return activities.slice(0, 20); // Return top 20 activities
    }

    async getTopContributors() {
        // This would typically involve more complex queries
        // For now, return board members as top contributors
        return this.frm.doc.board_members
            ?.filter(m => m.is_active)
            .map(m => ({
                name: m.volunteer_name,
                role: m.chapter_role,
                contributions: Math.floor(Math.random() * 50) + 10 // Placeholder
            }))
            .sort((a, b) => b.contributions - a.contributions)
            .slice(0, 5) || [];
    }

    async getUpcomingEvents() {
        // Placeholder - would integrate with events module
        return [];
    }

    generateActivitySummary(activities) {
        const summary = {
            total: activities.length,
            byType: {}
        };

        activities.forEach(activity => {
            summary.byType[activity.type] = (summary.byType[activity.type] || 0) + 1;
        });

        return summary;
    }

    generateActivityDashboardHTML(data) {
        return `
            <div class="activity-dashboard">
                <div class="row">
                    <div class="col-md-8">
                        <h5>${__('Recent Activity')}</h5>
                        <div class="activity-timeline">
                            ${this.generateActivityTimelineHTML(data.recentActivities)}
                        </div>
                    </div>
                    <div class="col-md-4">
                        <h5>${__('Top Contributors')}</h5>
                        <div class="contributor-list">
                            ${this.generateContributorListHTML(data.topContributors)}
                        </div>

                        ${data.upcomingEvents.length > 0 ? `
                            <h5 class="mt-4">${__('Upcoming Events')}</h5>
                            <div class="event-list">
                                ${this.generateEventListHTML(data.upcomingEvents)}
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>

            <style>
                .activity-timeline {
                    position: relative;
                    padding-left: 30px;
                }
                .activity-timeline::before {
                    content: '';
                    position: absolute;
                    left: 9px;
                    top: 0;
                    bottom: 0;
                    width: 2px;
                    background: #e9ecef;
                }
                .activity-item {
                    position: relative;
                    padding-bottom: 30px;
                }
                .activity-icon {
                    position: absolute;
                    left: -21px;
                    width: 20px;
                    height: 20px;
                    border-radius: 50%;
                    background: white;
                    border: 2px solid #dee2e6;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 10px;
                }
                .activity-icon.green {
                    border-color: #28a745;
                    color: #28a745;
                }
                .activity-icon.blue {
                    border-color: #007bff;
                    color: #007bff;
                }
                .contributor-item {
                    padding: 10px;
                    border-bottom: 1px solid #e9ecef;
                }
                .contributor-item:last-child {
                    border-bottom: none;
                }
            </style>
        `;
    }

    generateActivityTimelineHTML(activities) {
        if (!activities || activities.length === 0) {
            return `<p class="text-muted">${__('No recent activity')}</p>`;
        }

        return activities.map(activity => `
            <div class="activity-item">
                <div class="activity-icon ${activity.color}">
                    <i class="fa ${activity.icon}"></i>
                </div>
                <div class="activity-content">
                    <strong>${activity.title}</strong><br>
                    <span>${activity.description}</span><br>
                    <small class="text-muted">${frappe.datetime.prettyDate(activity.date)}</small>
                </div>
            </div>
        `).join('');
    }

    generateContributorListHTML(contributors) {
        if (!contributors || contributors.length === 0) {
            return `<p class="text-muted">${__('No contributors data available')}</p>`;
        }

        return contributors.map(contributor => `
            <div class="contributor-item">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${contributor.name}</strong><br>
                        <small class="text-muted">${contributor.role}</small>
                    </div>
                    <div class="text-right">
                        <span class="badge badge-primary">${contributor.contributions}</span>
                    </div>
                </div>
            </div>
        `).join('');
    }

    generateEventListHTML(events) {
        // Placeholder implementation
        return `<p class="text-muted">${__('No upcoming events')}</p>`;
    }

    initializeActivityTimeline(dialog, data) {
        // Add any interactive features to the timeline
        dialog.$wrapper.find('.activity-item').on('click', function() {
            $(this).toggleClass('expanded');
        });
    }

    async exportAnalytics() {
        try {
            this.state.setLoading('exportAnalytics', true);

            const stats = await this.fetchChapterStatistics();
            const growthData = await this.fetchGrowthData();

            // Create CSV content
            const csvContent = this.generateAnalyticsCSV(stats, growthData);

            // Download CSV
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            const url = URL.createObjectURL(blob);

            link.setAttribute('href', url);
            link.setAttribute('download', `${this.frm.doc.name}_analytics_${frappe.datetime.nowdate()}.csv`);
            link.style.visibility = 'hidden';

            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            frappe.show_alert({
                message: __('Analytics exported successfully'),
                indicator: 'green'
            }, 3);

        } catch (error) {
            frappe.msgprint(__('Error exporting analytics: {0}', [error.message]));
        } finally {
            this.state.setLoading('exportAnalytics', false);
        }
    }

    generateAnalyticsCSV(stats, growthData) {
        const lines = [];

        // Header
        lines.push(`Chapter Analytics Report - ${this.frm.doc.name}`);
        lines.push(`Generated on: ${frappe.datetime.now_datetime()}`);
        lines.push('');

        // Overview Section
        lines.push('OVERVIEW');
        lines.push(`Total Members,${stats.totalMembers}`);
        lines.push(`Active Members,${stats.activeMembers}`);
        lines.push(`Inactive Members,${stats.inactiveMembers}`);
        lines.push(`Board Members,${stats.boardMemberCount}`);
        lines.push(`Recent Members (30 days),${stats.recentMembers}`);
        lines.push(`Retention Rate,${stats.memberRetentionRate}%`);
        lines.push('');

        // Activity Section
        lines.push('ACTIVITY METRICS');
        lines.push(`Event Attendance,${stats.eventAttendance}`);
        lines.push(`Volunteer Hours,${stats.volunteerHours}`);
        lines.push(`Communications Sent,${stats.communicationCount}`);
        lines.push(`Engagement Score,${stats.engagementScore}/100`);
        lines.push('');

        // Board Statistics
        lines.push('BOARD STATISTICS');
        lines.push(`Average Tenure,${stats.averageTenure} days`);
        lines.push(`Turnover Rate,${stats.boardTurnoverRate}%`);
        lines.push('');

        // Growth Data
        lines.push('MONTHLY GROWTH DATA');
        lines.push('Month,New Members,New Memberships,Revenue');

        const months = new Set();
        growthData.monthlyGrowth.forEach(d => months.add(d.month));
        growthData.monthlyMemberships.forEach(d => months.add(d.month));

        Array.from(months).sort().forEach(month => {
            const growth = growthData.monthlyGrowth.find(g => g.month === month) || {};
            const membership = growthData.monthlyMemberships.find(m => m.month === month) || {};

            lines.push(`${month},${growth.new_members || 0},${membership.new_memberships || 0},${membership.revenue || 0}`);
        });

        return lines.join('\n');
    }

    async getChapterMemberIds() {
        if (!this.frm.doc.members) return [];

        return this.frm.doc.members
            .filter(m => m.enabled)
            .map(m => m.member);
    }

    async getChapterVolunteerIds() {
        if (!this.frm.doc.board_members) return [];

        return this.frm.doc.board_members
            .filter(m => m.is_active && m.volunteer)
            .map(m => m.volunteer);
    }
    async refresh() {
        // Refresh statistics if dialog is open
        if (this.state.get('ui.activeDialog') === 'statistics') {
            // Find and refresh the statistics dialog
            const dialog = Array.from(document.querySelectorAll('.modal-dialog'))
                .find(d => d.querySelector('.modal-title')?.textContent.includes('Statistics'));

            if (dialog) {
                await this.refreshStatistics(dialog._frappe_dialog);
            }
        }

        // Clear cache to force fresh data
        this.state.update('cache.statistics', null);
        this.state.update('cache.lastUpdated', null);
    }
    destroy() {
        // Destroy all charts
        this.charts.forEach(chart => chart.destroy());
        this.charts.clear();

        // Clear references
        this.frm = null;
        this.state = null;
        this.api = null;
    }
}
