#!/usr/bin/env python3
"""
System Monitoring and Logging Framework
Comprehensive monitoring for edge cases and system performance
"""

import json
import time
import threading
import requests
from datetime import datetime, timedelta
from collections import defaultdict, deque
import logging
import os

class SystemMonitor:
    def __init__(self):
        self.financial_simulator_url = "http://localhost:8002"
        self.lesson_generator_url = "http://localhost:8000"
        
        # Monitoring data structures
        self.metrics = {
            "financial_simulator": {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "average_response_time": 0,
                "current_active_tasks": 0,
                "timeout_count": 0,
                "error_count": 0,
                "last_error": None,
                "uptime_percentage": 100.0
            },
            "lesson_generator": {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "average_response_time": 0,
                "current_active_tasks": 0,
                "timeout_count": 0,
                "error_count": 0,
                "last_error": None,
                "uptime_percentage": 100.0
            }
        }
        
        # Edge case tracking
        self.edge_cases = {
            "bursty_workloads": [],
            "high_latency_events": [],
            "network_failures": [],
            "circuit_breaker_events": [],
            "extended_wait_events": []
        }
        
        # Performance tracking
        self.response_times = {
            "financial_simulator": deque(maxlen=100),
            "lesson_generator": deque(maxlen=100)
        }
        
        # Alert thresholds
        self.thresholds = {
            "max_response_time": 30.0,  # seconds
            "min_success_rate": 0.8,    # 80%
            "max_concurrent_requests": 20,
            "max_error_rate": 0.2       # 20%
        }
        
        # Setup logging
        self.setup_logging()
        
        # Start monitoring thread
        self.monitoring_active = True
        self.monitor_thread = threading.Thread(target=self.continuous_monitoring, daemon=True)
        self.monitor_thread.start()
    
    def setup_logging(self):
        """Setup comprehensive logging system"""
        
        # Create logs directory if it doesn't exist
        os.makedirs("logs", exist_ok=True)
        
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/system_monitor.log'),
                logging.StreamHandler()
            ]
        )
        
        self.logger = logging.getLogger('SystemMonitor')
        
        # Create separate loggers for different components
        self.financial_logger = logging.getLogger('FinancialSimulator')
        self.lesson_logger = logging.getLogger('LessonGenerator')
        self.edge_case_logger = logging.getLogger('EdgeCases')
        
        # Add file handlers for each component
        financial_handler = logging.FileHandler('logs/financial_simulator.log')
        lesson_handler = logging.FileHandler('logs/lesson_generator.log')
        edge_case_handler = logging.FileHandler('logs/edge_cases.log')
        
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        financial_handler.setFormatter(formatter)
        lesson_handler.setFormatter(formatter)
        edge_case_handler.setFormatter(formatter)
        
        self.financial_logger.addHandler(financial_handler)
        self.lesson_logger.addHandler(lesson_handler)
        self.edge_case_logger.addHandler(edge_case_handler)
    
    def log_request(self, service, request_type, response_time, success, error_message=None):
        """Log a request with comprehensive details"""
        
        timestamp = datetime.now().isoformat()
        
        # Update metrics
        service_metrics = self.metrics[service]
        service_metrics["total_requests"] += 1
        
        if success:
            service_metrics["successful_requests"] += 1
        else:
            service_metrics["failed_requests"] += 1
            service_metrics["last_error"] = error_message
            service_metrics["error_count"] += 1
        
        # Update response times
        self.response_times[service].append(response_time)
        if self.response_times[service]:
            service_metrics["average_response_time"] = sum(self.response_times[service]) / len(self.response_times[service])
        
        # Update success rate
        if service_metrics["total_requests"] > 0:
            success_rate = service_metrics["successful_requests"] / service_metrics["total_requests"]
            service_metrics["uptime_percentage"] = success_rate * 100
        
        # Log the request
        logger = self.financial_logger if service == "financial_simulator" else self.lesson_logger
        
        if success:
            logger.info(f"{request_type} - SUCCESS - {response_time:.2f}s")
        else:
            logger.error(f"{request_type} - FAILED - {response_time:.2f}s - {error_message}")
        
        # Check for edge cases
        self.check_edge_cases(service, response_time, success, error_message)
    
    def check_edge_cases(self, service, response_time, success, error_message):
        """Check for edge case conditions and log them"""
        
        timestamp = datetime.now().isoformat()
        
        # High latency detection
        if response_time > self.thresholds["max_response_time"]:
            edge_case = {
                "type": "high_latency",
                "service": service,
                "response_time": response_time,
                "timestamp": timestamp
            }
            self.edge_cases["high_latency_events"].append(edge_case)
            self.edge_case_logger.warning(f"HIGH LATENCY: {service} took {response_time:.2f}s")
        
        # Network failure detection
        if not success and error_message and ("network" in error_message.lower() or "connection" in error_message.lower()):
            edge_case = {
                "type": "network_failure",
                "service": service,
                "error": error_message,
                "timestamp": timestamp
            }
            self.edge_cases["network_failures"].append(edge_case)
            self.edge_case_logger.error(f"NETWORK FAILURE: {service} - {error_message}")
        
        # Check success rate for circuit breaker conditions
        service_metrics = self.metrics[service]
        if service_metrics["total_requests"] >= 10:  # Only check after sufficient requests
            error_rate = service_metrics["failed_requests"] / service_metrics["total_requests"]
            if error_rate > self.thresholds["max_error_rate"]:
                edge_case = {
                    "type": "circuit_breaker_condition",
                    "service": service,
                    "error_rate": error_rate,
                    "timestamp": timestamp
                }
                self.edge_cases["circuit_breaker_events"].append(edge_case)
                self.edge_case_logger.critical(f"CIRCUIT BREAKER CONDITION: {service} error rate {error_rate:.2%}")
    
    def log_bursty_workload(self, concurrent_requests, service, success_rate):
        """Log bursty workload events"""
        
        edge_case = {
            "type": "bursty_workload",
            "service": service,
            "concurrent_requests": concurrent_requests,
            "success_rate": success_rate,
            "timestamp": datetime.now().isoformat()
        }
        self.edge_cases["bursty_workloads"].append(edge_case)
        self.edge_case_logger.info(f"BURSTY WORKLOAD: {service} - {concurrent_requests} concurrent requests, {success_rate:.2%} success rate")
    
    def log_extended_wait(self, service, task_id, wait_time_minutes):
        """Log extended wait events"""
        
        edge_case = {
            "type": "extended_wait",
            "service": service,
            "task_id": task_id,
            "wait_time_minutes": wait_time_minutes,
            "timestamp": datetime.now().isoformat()
        }
        self.edge_cases["extended_wait_events"].append(edge_case)
        self.edge_case_logger.warning(f"EXTENDED WAIT: {service} task {task_id} - {wait_time_minutes:.1f} minutes")
    
    def continuous_monitoring(self):
        """Continuous monitoring of system health"""
        
        while self.monitoring_active:
            try:
                # Check service health
                self.check_service_health()
                
                # Generate alerts if needed
                self.check_alerts()
                
                # Clean old data
                self.cleanup_old_data()
                
                # Wait before next check
                time.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                self.logger.error(f"Error in continuous monitoring: {e}")
                time.sleep(60)  # Wait longer on error
    
    def check_service_health(self):
        """Check the health of all services"""
        
        services = [
            ("financial_simulator", f"{self.financial_simulator_url}/docs"),
            ("lesson_generator", f"{self.lesson_generator_url}/docs")
        ]
        
        for service_name, health_url in services:
            try:
                start_time = time.time()
                response = requests.get(health_url, timeout=5)
                response_time = time.time() - start_time
                
                if response.status_code == 200:
                    self.log_request(service_name, "health_check", response_time, True)
                else:
                    self.log_request(service_name, "health_check", response_time, False, f"HTTP {response.status_code}")
                    
            except Exception as e:
                response_time = time.time() - start_time
                self.log_request(service_name, "health_check", response_time, False, str(e))
    
    def check_alerts(self):
        """Check for alert conditions"""
        
        for service, metrics in self.metrics.items():
            # Check success rate
            if metrics["total_requests"] > 0:
                success_rate = metrics["successful_requests"] / metrics["total_requests"]
                if success_rate < self.thresholds["min_success_rate"]:
                    self.logger.critical(f"ALERT: {service} success rate below threshold: {success_rate:.2%}")
            
            # Check average response time
            if metrics["average_response_time"] > self.thresholds["max_response_time"]:
                self.logger.warning(f"ALERT: {service} average response time high: {metrics['average_response_time']:.2f}s")
    
    def cleanup_old_data(self):
        """Clean up old monitoring data"""
        
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        for edge_case_type, events in self.edge_cases.items():
            # Remove events older than 24 hours
            self.edge_cases[edge_case_type] = [
                event for event in events 
                if datetime.fromisoformat(event["timestamp"]) > cutoff_time
            ]
    
    def get_dashboard_data(self):
        """Get comprehensive dashboard data"""
        
        dashboard = {
            "timestamp": datetime.now().isoformat(),
            "services": self.metrics,
            "edge_cases": {
                "summary": {
                    edge_case_type: len(events) 
                    for edge_case_type, events in self.edge_cases.items()
                },
                "recent_events": {
                    edge_case_type: events[-5:] if events else []
                    for edge_case_type, events in self.edge_cases.items()
                }
            },
            "alerts": self.get_current_alerts(),
            "performance": {
                "financial_simulator": {
                    "recent_response_times": list(self.response_times["financial_simulator"])[-10:],
                    "average_response_time": self.metrics["financial_simulator"]["average_response_time"]
                },
                "lesson_generator": {
                    "recent_response_times": list(self.response_times["lesson_generator"])[-10:],
                    "average_response_time": self.metrics["lesson_generator"]["average_response_time"]
                }
            }
        }
        
        return dashboard
    
    def get_current_alerts(self):
        """Get current alert conditions"""
        
        alerts = []
        
        for service, metrics in self.metrics.items():
            if metrics["total_requests"] > 0:
                success_rate = metrics["successful_requests"] / metrics["total_requests"]
                if success_rate < self.thresholds["min_success_rate"]:
                    alerts.append({
                        "type": "low_success_rate",
                        "service": service,
                        "value": success_rate,
                        "threshold": self.thresholds["min_success_rate"]
                    })
            
            if metrics["average_response_time"] > self.thresholds["max_response_time"]:
                alerts.append({
                    "type": "high_response_time",
                    "service": service,
                    "value": metrics["average_response_time"],
                    "threshold": self.thresholds["max_response_time"]
                })
        
        return alerts
    
    def save_dashboard_data(self, filename="dashboard_data.json"):
        """Save dashboard data to file"""
        
        dashboard_data = self.get_dashboard_data()
        
        with open(filename, "w") as f:
            json.dump(dashboard_data, f, indent=2)
        
        return dashboard_data
    
    def stop_monitoring(self):
        """Stop the monitoring system"""
        
        self.monitoring_active = False
        if self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        
        self.logger.info("System monitoring stopped")

# Global monitor instance
system_monitor = SystemMonitor()

def get_monitor():
    """Get the global system monitor instance"""
    return system_monitor

if __name__ == "__main__":
    print("🔍 System Monitor Started")
    print("=" * 50)
    
    try:
        # Keep the monitor running
        while True:
            time.sleep(10)
            
            # Print dashboard summary every 60 seconds
            dashboard = system_monitor.get_dashboard_data()
            print(f"\n📊 Dashboard Summary ({datetime.now().strftime('%H:%M:%S')})")
            print(f"Financial Simulator: {dashboard['services']['financial_simulator']['total_requests']} requests, {dashboard['services']['financial_simulator']['uptime_percentage']:.1f}% uptime")
            print(f"Lesson Generator: {dashboard['services']['lesson_generator']['total_requests']} requests, {dashboard['services']['lesson_generator']['uptime_percentage']:.1f}% uptime")
            
            alerts = dashboard['alerts']
            if alerts:
                print(f"🚨 Active Alerts: {len(alerts)}")
                for alert in alerts:
                    print(f"   - {alert['type']}: {alert['service']} ({alert['value']:.2f})")
            
            time.sleep(50)  # Total 60 seconds between summaries
            
    except KeyboardInterrupt:
        print("\n🛑 Stopping system monitor...")
        system_monitor.stop_monitoring()
        print("✅ System monitor stopped")
