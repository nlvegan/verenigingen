import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { AlertTriangle, Users, FileText, CheckCircle, XCircle, Clock, TrendingUp } from 'lucide-react';

const TerminationDashboard = () => {
  const [stats, setStats] = useState(null);
  const [pendingRequests, setPendingRequests] = useState([]);
  const [recentActivity, setRecentActivity] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDashboardData();
  }, []);

  const fetchDashboardData = async () => {
    try {
      // Simulate API calls that would be made to Frappe
      const statsResponse = await frappe.call({
        method: 'verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request.get_termination_statistics'
      });

      const pendingResponse = await frappe.call({
        method: 'frappe.client.get_list',
        args: {
          doctype: 'Membership Termination Request',
          filters: { status: 'Pending Approval' },
          fields: ['name', 'member_name', 'termination_type', 'request_date', 'requested_by'],
          limit: 10,
          order_by: 'request_date desc'
        }
      });

      const recentResponse = await frappe.call({
        method: 'frappe.client.get_list',
        args: {
          doctype: 'Membership Termination Request',
          filters: { status: 'Executed' },
          fields: ['name', 'member_name', 'termination_type', 'execution_date', 'executed_by'],
          limit: 5,
          order_by: 'execution_date desc'
        }
      });

      setStats(statsResponse.message);
      setPendingRequests(pendingResponse.message || []);
      setRecentActivity(recentResponse.message || []);
    } catch (error) {
      console.error('Error fetching dashboard data:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  const getStatusColor = (status) => {
    const colors = {
      'Draft': 'bg-blue-100 text-blue-800',
      'Pending Approval': 'bg-yellow-100 text-yellow-800',
      'Approved': 'bg-green-100 text-green-800',
      'Rejected': 'bg-red-100 text-red-800',
      'Executed': 'bg-gray-100 text-gray-800'
    };
    return colors[status] || 'bg-gray-100 text-gray-800';
  };

  const getTypeColor = (type) => {
    const disciplinaryTypes = ['Policy Violation', 'Disciplinary Action', 'Expulsion'];
    return disciplinaryTypes.includes(type)
      ? 'bg-red-100 text-red-800'
      : 'bg-blue-100 text-blue-800';
  };

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold text-gray-900">Membership Termination Dashboard</h1>
        <div className="flex space-x-2">
          <button
            onClick={() => frappe.set_route('List', 'Membership Termination Request')}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
          >
            View All Requests
          </button>
          <button
            onClick={() => frappe.set_route('Form', 'Membership Termination Request', 'new')}
            className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700"
          >
            New Termination
          </button>
        </div>
      </div>

      {/* Statistics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pending Approvals</CardTitle>
            <AlertTriangle className="h-4 w-4 text-yellow-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-yellow-600">
              {stats?.pending_approvals || 0}
            </div>
            <p className="text-xs text-gray-600">
              Requiring immediate attention
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Requests</CardTitle>
            <FileText className="h-4 w-4 text-blue-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-blue-600">
              {stats?.total_requests || 0}
            </div>
            <p className="text-xs text-gray-600">
              All time
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Recent Activity</CardTitle>
            <TrendingUp className="h-4 w-4 text-green-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">
              {stats?.recent_activity?.requests || 0}
            </div>
            <p className="text-xs text-gray-600">
              Last 30 days
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Executions</CardTitle>
            <CheckCircle className="h-4 w-4 text-gray-600" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-gray-600">
              {stats?.recent_activity?.executions || 0}
            </div>
            <p className="text-xs text-gray-600">
              Last 30 days
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Status Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Requests by Status</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {stats?.status_counts && Object.entries(stats.status_counts).map(([status, count]) => (
                <div key={status} className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <Badge className={getStatusColor(status)}>
                      {status}
                    </Badge>
                  </div>
                  <span className="font-semibold">{count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Requests by Type</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {stats?.type_counts && Object.entries(stats.type_counts)
                .filter(([_, count]) => count > 0)
                .map(([type, count]) => (
                <div key={type} className="flex items-center justify-between">
                  <div className="flex items-center space-x-2">
                    <Badge className={getTypeColor(type)}>
                      {type}
                    </Badge>
                  </div>
                  <span className="font-semibold">{count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Pending Approvals */}
      {pendingRequests.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center space-x-2">
              <AlertTriangle className="h-5 w-5 text-yellow-600" />
              <span>Pending Approvals ({pendingRequests.length})</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {pendingRequests.map((request) => (
                <div key={request.name} className="flex items-center justify-between p-4 border rounded-lg hover:bg-gray-50">
                  <div className="flex-1">
                    <div className="flex items-center space-x-3">
                      <h4 className="font-medium">{request.member_name}</h4>
                      <Badge className={getTypeColor(request.termination_type)}>
                        {request.termination_type}
                      </Badge>
                    </div>
                    <p className="text-sm text-gray-600 mt-1">
                      Requested by {request.requested_by} on {new Date(request.request_date).toLocaleDateString()}
                    </p>
                  </div>
                  <div className="flex space-x-2">
                    <button
                      onClick={() => frappe.set_route('Form', 'Membership Termination Request', request.name)}
                      className="px-3 py-1 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
                    >
                      Review
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent Activity */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Executions</CardTitle>
        </CardHeader>
        <CardContent>
          {recentActivity.length > 0 ? (
            <div className="space-y-4">
              {recentActivity.map((activity) => (
                <div key={activity.name} className="flex items-center justify-between p-3 border-l-4 border-gray-300 bg-gray-50">
                  <div>
                    <h4 className="font-medium">{activity.member_name}</h4>
                    <div className="flex items-center space-x-2 mt-1">
                      <Badge className={getTypeColor(activity.termination_type)}>
                        {activity.termination_type}
                      </Badge>
                      <span className="text-sm text-gray-600">
                        Executed by {activity.executed_by} on {new Date(activity.execution_date).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={() => frappe.set_route('Form', 'Membership Termination Request', activity.name)}
                    className="text-blue-600 hover:text-blue-800 text-sm"
                  >
                    View Details
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-600 italic">No recent executions</p>
          )}
        </CardContent>
      </Card>

      {/* Quick Actions */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <button
              onClick={() => frappe.set_route('query-report', 'Termination Audit Report')}
              className="p-4 border rounded-lg hover:bg-gray-50 text-left"
            >
              <FileText className="h-6 w-6 text-blue-600 mb-2" />
              <h3 className="font-medium">Audit Report</h3>
              <p className="text-sm text-gray-600">Generate comprehensive audit trail</p>
            </button>

            <button
              onClick={() => frappe.set_route('query-report', 'Expulsion Governance Report')}
              className="p-4 border rounded-lg hover:bg-gray-50 text-left"
            >
              <AlertTriangle className="h-6 w-6 text-red-600 mb-2" />
              <h3 className="font-medium">Expulsion Report</h3>
              <p className="text-sm text-gray-600">Review disciplinary actions</p>
            </button>

            <button
              onClick={() => frappe.msgprint('Bulk processing functionality coming soon')}
              className="p-4 border rounded-lg hover:bg-gray-50 text-left"
            >
              <Users className="h-6 w-6 text-green-600 mb-2" />
              <h3 className="font-medium">Bulk Operations</h3>
              <p className="text-sm text-gray-600">Process multiple requests</p>
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default TerminationDashboard;
