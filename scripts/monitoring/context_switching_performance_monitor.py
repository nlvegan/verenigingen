#!/usr/bin/env python3
"""
Context Switching Performance Monitor
====================================

Monitors and analyzes performance of system context switching operations
to ensure Phase 2 security improvements maintain acceptable performance
under production conditions.

This addresses QCE recommendations for production performance monitoring.

Usage:
    python scripts/monitoring/context_switching_performance_monitor.py --monitor --duration 3600
    python scripts/monitoring/context_switching_performance_monitor.py --analyze --report-file /path/to/report.json
    
Monitoring Capabilities:
1. Real-time context switching latency tracking
2. Context operation frequency analysis
3. Error rate monitoring for context switches
4. Resource usage correlation
5. Alert generation for performance degradation

Performance Thresholds:
- Context Switch Warning: >50ms
- Context Switch Critical: >100ms  
- Error Rate Warning: >1%
- Error Rate Critical: >5%
"""

import os
import sys
import time
import json
import argparse
import threading
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict, deque

# Add Frappe path
sys.path.insert(0, '/home/frappe/frappe-bench/apps/frappe')
sys.path.insert(0, '/home/frappe/frappe-bench/apps/erpnext')  
sys.path.insert(0, '/home/frappe/frappe-bench/apps/verenigingen')

import frappe
from frappe.utils import now_datetime


@dataclass
class ContextSwitchEvent:
    """Represents a single context switching event"""
    timestamp: float
    operation_id: str
    operation_type: str
    target_user: str
    source_user: str
    duration: float
    success: bool
    error_message: Optional[str] = None
    thread_id: Optional[str] = None


@dataclass
class PerformanceMetrics:
    """Performance metrics for context switching operations"""
    total_operations: int
    successful_operations: int
    failed_operations: int
    avg_duration: float
    median_duration: float
    p95_duration: float
    p99_duration: float
    max_duration: float
    error_rate: float
    operations_per_second: float


class ContextPerformanceMonitor:
    """Monitors context switching performance in real-time"""
    
    def __init__(self, max_events: int = 10000):
        self.max_events = max_events
        self.events = deque(maxlen=max_events)
        self.running = False
        self.monitor_thread = None
        self.lock = threading.RLock()
        
        # Performance thresholds
        self.warning_duration_ms = 50
        self.critical_duration_ms = 100
        self.warning_error_rate = 0.01  # 1%
        self.critical_error_rate = 0.05  # 5%
        
        # Alerting
        self.alerts = []
        self.last_alert_time = defaultdict(float)
        self.alert_cooldown = 300  # 5 minutes
        
    def start_monitoring(self):
        """Start performance monitoring"""
        if self.running:
            return
            
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        print(f"Context switching performance monitor started")
        print(f"Warning threshold: {self.warning_duration_ms}ms")
        print(f"Critical threshold: {self.critical_duration_ms}ms")
        
    def stop_monitoring(self):
        """Stop performance monitoring"""
        self.running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        print("Performance monitoring stopped")
        
    def record_context_switch(self, event: ContextSwitchEvent):
        """Record a context switching event"""
        with self.lock:
            self.events.append(event)
            
        # Check for performance issues
        self._check_performance_thresholds(event)
        
    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                # Periodic analysis and alerting
                if len(self.events) > 0:
                    self._analyze_recent_performance()
                    
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                print(f"Error in monitoring loop: {str(e)}")
                
    def _check_performance_thresholds(self, event: ContextSwitchEvent):
        """Check if event exceeds performance thresholds"""
        duration_ms = event.duration * 1000
        
        if duration_ms > self.critical_duration_ms:
            self._generate_alert(
                "CRITICAL", 
                f"Context switch duration critical: {duration_ms:.1f}ms",
                event
            )
        elif duration_ms > self.warning_duration_ms:
            self._generate_alert(
                "WARNING",
                f"Context switch duration warning: {duration_ms:.1f}ms", 
                event
            )
            
        if not event.success:
            self._generate_alert(
                "ERROR",
                f"Context switch failed: {event.error_message}",
                event
            )
            
    def _analyze_recent_performance(self):
        """Analyze recent performance trends"""
        with self.lock:
            if len(self.events) < 10:
                return
                
            # Analyze last 5 minutes of data
            cutoff_time = time.time() - 300
            recent_events = [e for e in self.events if e.timestamp > cutoff_time]
            
            if not recent_events:
                return
                
            # Calculate error rate
            failed_events = [e for e in recent_events if not e.success]
            error_rate = len(failed_events) / len(recent_events)
            
            # Check error rate thresholds
            if error_rate > self.critical_error_rate:
                self._generate_alert(
                    "CRITICAL",
                    f"Context switch error rate critical: {error_rate*100:.1f}%",
                    None
                )
            elif error_rate > self.warning_error_rate:
                self._generate_alert(
                    "WARNING", 
                    f"Context switch error rate warning: {error_rate*100:.1f}%",
                    None
                )
                
    def _generate_alert(self, level: str, message: str, event: Optional[ContextSwitchEvent]):
        """Generate performance alert"""
        alert_key = f"{level}_{hash(message) % 1000}"
        current_time = time.time()
        
        # Apply cooldown to prevent spam
        if current_time - self.last_alert_time[alert_key] < self.alert_cooldown:
            return
            
        alert = {
            "timestamp": current_time,
            "level": level,
            "message": message,
            "event": asdict(event) if event else None
        }
        
        self.alerts.append(alert)
        self.last_alert_time[alert_key] = current_time
        
        # Log alert
        print(f"[{level}] {datetime.fromtimestamp(current_time).isoformat()} - {message}")
        
        if event:
            print(f"  Operation: {event.operation_type} ({event.operation_id})")
            print(f"  User Switch: {event.source_user} -> {event.target_user}")
            
    def get_performance_metrics(self, time_window_minutes: int = 60) -> PerformanceMetrics:
        """Get performance metrics for specified time window"""
        with self.lock:
            if not self.events:
                return PerformanceMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
                
            # Filter events by time window
            cutoff_time = time.time() - (time_window_minutes * 60)
            recent_events = [e for e in self.events if e.timestamp > cutoff_time]
            
            if not recent_events:
                return PerformanceMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
                
            # Calculate metrics
            total_ops = len(recent_events)
            successful_ops = len([e for e in recent_events if e.success])
            failed_ops = total_ops - successful_ops
            
            durations = [e.duration for e in recent_events if e.success]
            
            if durations:
                avg_duration = statistics.mean(durations)
                median_duration = statistics.median(durations)
                sorted_durations = sorted(durations)
                p95_duration = sorted_durations[int(len(sorted_durations) * 0.95)]
                p99_duration = sorted_durations[int(len(sorted_durations) * 0.99)]
                max_duration = max(durations)
            else:
                avg_duration = median_duration = p95_duration = p99_duration = max_duration = 0
                
            error_rate = failed_ops / total_ops if total_ops > 0 else 0
            
            # Calculate operations per second
            time_span = max(e.timestamp for e in recent_events) - min(e.timestamp for e in recent_events)
            ops_per_second = total_ops / time_span if time_span > 0 else 0
            
            return PerformanceMetrics(
                total_operations=total_ops,
                successful_operations=successful_ops,
                failed_operations=failed_ops,
                avg_duration=avg_duration,
                median_duration=median_duration,
                p95_duration=p95_duration,
                p99_duration=p99_duration,
                max_duration=max_duration,
                error_rate=error_rate,
                operations_per_second=ops_per_second
            )
            
    def generate_performance_report(self, output_file: str = None) -> Dict:
        """Generate comprehensive performance report"""
        report = {
            "generated_at": datetime.now().isoformat(),
            "monitoring_duration": len(self.events),
            "performance_metrics": {
                "1_hour": asdict(self.get_performance_metrics(60)),
                "24_hours": asdict(self.get_performance_metrics(1440)),
                "7_days": asdict(self.get_performance_metrics(10080))
            },
            "alerts_summary": {
                "total_alerts": len(self.alerts),
                "critical_alerts": len([a for a in self.alerts if a["level"] == "CRITICAL"]),
                "warning_alerts": len([a for a in self.alerts if a["level"] == "WARNING"]),
                "error_alerts": len([a for a in self.alerts if a["level"] == "ERROR"])
            },
            "recent_alerts": self.alerts[-20:] if len(self.alerts) > 20 else self.alerts,
            "operation_breakdown": self._analyze_operations_by_type(),
            "user_switching_patterns": self._analyze_user_switching_patterns(),
            "recommendations": self._generate_recommendations()
        }
        
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"Performance report saved to: {output_file}")
            
        return report
        
    def _analyze_operations_by_type(self) -> Dict:
        """Analyze performance by operation type"""
        with self.lock:
            operation_stats = defaultdict(lambda: {"count": 0, "durations": [], "errors": 0})
            
            for event in self.events:
                stats = operation_stats[event.operation_type]
                stats["count"] += 1
                if event.success:
                    stats["durations"].append(event.duration)
                else:
                    stats["errors"] += 1
                    
            # Calculate summary statistics
            result = {}
            for op_type, stats in operation_stats.items():
                durations = stats["durations"]
                result[op_type] = {
                    "total_operations": stats["count"],
                    "successful_operations": len(durations),
                    "failed_operations": stats["errors"],
                    "avg_duration": statistics.mean(durations) if durations else 0,
                    "max_duration": max(durations) if durations else 0,
                    "error_rate": stats["errors"] / stats["count"] if stats["count"] > 0 else 0
                }
                
            return result
            
    def _analyze_user_switching_patterns(self) -> Dict:
        """Analyze user switching patterns"""
        with self.lock:
            user_switches = defaultdict(int)
            target_users = defaultdict(int)
            
            for event in self.events:
                switch_pattern = f"{event.source_user} -> {event.target_user}"
                user_switches[switch_pattern] += 1
                target_users[event.target_user] += 1
                
            return {
                "most_common_switches": dict(sorted(user_switches.items(), 
                                                   key=lambda x: x[1], reverse=True)[:10]),
                "most_common_targets": dict(sorted(target_users.items(), 
                                                  key=lambda x: x[1], reverse=True)[:10])
            }
            
    def _generate_recommendations(self) -> List[str]:
        """Generate performance recommendations based on analysis"""
        recommendations = []
        
        metrics_1h = self.get_performance_metrics(60)
        
        # Duration-based recommendations
        if metrics_1h.avg_duration > 0.1:  # 100ms
            recommendations.append(
                f"Average context switch duration is high ({metrics_1h.avg_duration*1000:.1f}ms). "
                f"Consider optimizing user context operations."
            )
            
        if metrics_1h.p99_duration > 0.2:  # 200ms
            recommendations.append(
                f"99th percentile duration is very high ({metrics_1h.p99_duration*1000:.1f}ms). "
                f"Investigate worst-case performance scenarios."
            )
            
        # Error rate recommendations  
        if metrics_1h.error_rate > 0.05:  # 5%
            recommendations.append(
                f"Error rate is high ({metrics_1h.error_rate*100:.1f}%). "
                f"Review error handling and context validation."
            )
            
        # Throughput recommendations
        if metrics_1h.operations_per_second > 10:
            recommendations.append(
                f"High context switch frequency detected ({metrics_1h.operations_per_second:.1f} ops/sec). "
                f"Consider batching operations or caching context."
            )
            
        if not recommendations:
            recommendations.append("Performance metrics are within acceptable ranges.")
            
        return recommendations


def print_performance_report(report: Dict):
    """Print formatted performance report"""
    print("\n" + "="*80)
    print("CONTEXT SWITCHING PERFORMANCE REPORT")
    print("="*80)
    
    print(f"\n📊 REPORT SUMMARY:")
    print(f"  Generated: {report['generated_at']}")
    print(f"  Monitoring Duration: {report['monitoring_duration']} events")
    
    # 1 Hour Metrics
    metrics_1h = report['performance_metrics']['1_hour']
    print(f"\n⏱️  LAST HOUR PERFORMANCE:")
    print(f"  Total Operations: {metrics_1h['total_operations']}")
    print(f"  Success Rate: {(1-metrics_1h['error_rate'])*100:.1f}%")
    print(f"  Average Duration: {metrics_1h['avg_duration']*1000:.1f}ms")
    print(f"  95th Percentile: {metrics_1h['p95_duration']*1000:.1f}ms")
    print(f"  99th Percentile: {metrics_1h['p99_duration']*1000:.1f}ms")
    print(f"  Operations/Second: {metrics_1h['operations_per_second']:.2f}")
    
    # Alerts Summary
    alerts = report['alerts_summary']
    print(f"\n🚨 ALERTS SUMMARY:")
    print(f"  Total Alerts: {alerts['total_alerts']}")
    print(f"  Critical: {alerts['critical_alerts']}")
    print(f"  Warning: {alerts['warning_alerts']}")
    print(f"  Errors: {alerts['error_alerts']}")
    
    # Recent alerts
    if report['recent_alerts']:
        print(f"\n🔔 RECENT ALERTS:")
        for alert in report['recent_alerts'][-5:]:  # Last 5 alerts
            timestamp = datetime.fromtimestamp(alert['timestamp']).strftime('%H:%M:%S')
            print(f"  [{alert['level']}] {timestamp} - {alert['message']}")
    
    # Operation breakdown
    if report['operation_breakdown']:
        print(f"\n📋 OPERATIONS BY TYPE:")
        for op_type, stats in report['operation_breakdown'].items():
            print(f"  {op_type}:")
            print(f"    Total: {stats['total_operations']}")
            print(f"    Avg Duration: {stats['avg_duration']*1000:.1f}ms")
            print(f"    Error Rate: {stats['error_rate']*100:.1f}%")
    
    # Recommendations
    print(f"\n💡 RECOMMENDATIONS:")
    for i, rec in enumerate(report['recommendations'], 1):
        print(f"  {i}. {rec}")


def setup_monitoring_integration():
    """Set up integration with secure context manager"""
    try:
        # Patch the secure context manager to send events to monitor
        from verenigingen.utils.secure_context_manager import SecureContextManager
        
        # Store original methods
        original_enter = SecureContextManager.__enter__
        original_exit = SecureContextManager.__exit__
        
        def monitored_enter(self):
            self._monitor_start_time = time.time()
            return original_enter(self)
            
        def monitored_exit(self, exc_type, exc_val, exc_tb):
            try:
                duration = time.time() - getattr(self, '_monitor_start_time', time.time())
                success = exc_type is None
                
                event = ContextSwitchEvent(
                    timestamp=time.time(),
                    operation_id=self.context_id,
                    operation_type=self.operation_description,
                    target_user=self.target_user,
                    source_user=self.original_user,
                    duration=duration,
                    success=success,
                    error_message=str(exc_val) if exc_val else None,
                    thread_id=threading.current_thread().name
                )
                
                # Send to global monitor if available
                if hasattr(setup_monitoring_integration, 'monitor'):
                    setup_monitoring_integration.monitor.record_context_switch(event)
                    
            except Exception as monitor_error:
                print(f"Monitoring error: {monitor_error}")
                
            return original_exit(self, exc_type, exc_val, exc_tb)
            
        # Apply patches
        SecureContextManager.__enter__ = monitored_enter
        SecureContextManager.__exit__ = monitored_exit
        
        print("Context switching monitoring integration installed")
        return True
        
    except Exception as e:
        print(f"Failed to set up monitoring integration: {str(e)}")
        return False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Monitor context switching performance"
    )
    parser.add_argument(
        '--monitor',
        action='store_true',
        help='Start real-time monitoring'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=3600,
        help='Monitoring duration in seconds (default: 3600)'
    )
    parser.add_argument(
        '--analyze',
        action='store_true',
        help='Analyze existing monitoring data'
    )
    parser.add_argument(
        '--report-file',
        type=str,
        help='Output file for performance report'
    )
    
    args = parser.parse_args()
    
    if args.monitor:
        try:
            # Set up Frappe environment
            frappe.init(site='dev.veganisme.net')
            frappe.connect()
            
            # Create monitor
            monitor = ContextPerformanceMonitor()
            
            # Set up monitoring integration
            setup_monitoring_integration.monitor = monitor
            if setup_monitoring_integration():
                print("Monitoring integration successful")
            else:
                print("Warning: Monitoring integration failed")
            
            # Start monitoring
            monitor.start_monitoring()
            
            print(f"Monitoring context switching performance for {args.duration} seconds...")
            print("Press Ctrl+C to stop monitoring early")
            
            try:
                time.sleep(args.duration)
            except KeyboardInterrupt:
                print("\nMonitoring stopped by user")
            
            # Generate final report
            monitor.stop_monitoring()
            report = monitor.generate_performance_report(args.report_file)
            print_performance_report(report)
            
        except Exception as e:
            print(f"Monitoring failed: {str(e)}")
            sys.exit(1)
            
        finally:
            try:
                frappe.destroy()
            except:
                pass
                
    elif args.analyze:
        if not args.report_file or not os.path.exists(args.report_file):
            print("Error: Report file required for analysis")
            sys.exit(1)
            
        try:
            with open(args.report_file, 'r') as f:
                report = json.load(f)
            print_performance_report(report)
            
        except Exception as e:
            print(f"Analysis failed: {str(e)}")
            sys.exit(1)
            
    else:
        parser.print_help()


if __name__ == "__main__":
    main()