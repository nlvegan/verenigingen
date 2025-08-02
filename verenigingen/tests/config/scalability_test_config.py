#!/usr/bin/env python3
"""
Payment History Scalability Test Configuration
==============================================

Centralized configuration for payment history scalability testing.
Defines test scales, performance thresholds, resource limits, and
environment-specific settings.

This configuration allows easy adjustment of test parameters without
modifying test code, enabling adaptation to different hardware
configurations and testing requirements.
"""

from typing import Dict, Any


class ScalabilityTestConfig:
    """Centralized configuration for scalability testing"""
    
    # Test Scale Definitions
    TEST_SCALES = {
        "smoke": {
            "member_count": 100,
            "max_payment_months": 6,
            "description": "Quick smoke test for basic functionality",
            "timeout_seconds": 60,
            "max_execution_time": 30.0,
            "min_throughput_members_per_sec": 5.0,
            "max_memory_usage_mb": 200.0
        },
        "integration": {
            "member_count": 500,
            "max_payment_months": 12,
            "description": "Integration test with moderate scale",
            "timeout_seconds": 300,
            "max_execution_time": 120.0,
            "min_throughput_members_per_sec": 3.0,
            "max_memory_usage_mb": 500.0
        },
        "performance": {
            "member_count": 1000,
            "max_payment_months": 18,
            "description": "Performance test with realistic production scale",
            "timeout_seconds": 600,
            "max_execution_time": 300.0,
            "min_throughput_members_per_sec": 2.0,
            "max_memory_usage_mb": 1000.0
        },
        "stress": {
            "member_count": 2500,
            "max_payment_months": 24,
            "description": "Stress test with high scale",
            "timeout_seconds": 900,
            "max_execution_time": 600.0,
            "min_throughput_members_per_sec": 1.0,
            "max_memory_usage_mb": 2000.0
        },
        "maximum": {
            "member_count": 5000,
            "max_payment_months": 36,
            "description": "Maximum scale stress test",
            "timeout_seconds": 1800,
            "max_execution_time": 1200.0,
            "min_throughput_members_per_sec": 0.5,
            "max_memory_usage_mb": 4000.0
        }
    }
    
    # Background Job Testing Configuration
    BACKGROUND_JOB_CONFIG = {
        "smoke": {
            "member_count": 50,
            "timeout_seconds": 120,
            "max_queue_time": 10.0,
            "min_completion_rate": 0.90
        },
        "integration": {
            "member_count": 200,
            "timeout_seconds": 300,
            "max_queue_time": 30.0,
            "min_completion_rate": 0.85
        },
        "performance": {
            "member_count": 500,
            "timeout_seconds": 600,
            "max_queue_time": 60.0,
            "min_completion_rate": 0.80
        }
    }
    
    # Payment History Generation Configuration
    PAYMENT_HISTORY_CONFIG = {
        "member_profiles": {
            "reliable": {
                "distribution_weight": 0.40,
                "on_time_payment_rate": 0.95,
                "payment_failure_rate": 0.02,
                "retry_success_rate": 0.90
            },
            "typical": {
                "distribution_weight": 0.40,
                "on_time_payment_rate": 0.80,
                "payment_failure_rate": 0.10,
                "retry_success_rate": 0.70
            },
            "problematic": {
                "distribution_weight": 0.15,
                "on_time_payment_rate": 0.60,
                "payment_failure_rate": 0.25,
                "retry_success_rate": 0.50
            },
            "sporadic": {
                "distribution_weight": 0.05,
                "on_time_payment_rate": 0.40,
                "payment_failure_rate": 0.35,
                "retry_success_rate": 0.30
            }
        },
        "payment_frequencies": {
            "Monthly": 0.70,
            "Quarterly": 0.20,
            "Semi-Annual": 0.07,
            "Annual": 0.03
        },
        "sepa_mandate_adoption_rate": 0.75,
        "unreconciled_payment_rate": 0.30,
        "payment_amount_range": [15.0, 150.0],
        "payment_variance_percent": 0.10
    }
    
    # System Resource Requirements
    SYSTEM_REQUIREMENTS = {
        "minimum_memory_gb": 2.0,
        "recommended_memory_gb": 8.0,
        "minimum_cpu_cores": 2,
        "recommended_cpu_cores": 4,
        "disk_space_gb": 5.0,
        "max_test_duration_hours": 2.0
    }
    
    # Performance Monitoring Configuration
    MONITORING_CONFIG = {
        "resource_sampling_interval_seconds": 5,
        "memory_warning_threshold_mb": 3000.0,
        "cpu_warning_threshold_percent": 90.0,
        "slow_query_threshold_seconds": 0.5,
        "enable_query_logging": True,
        "enable_memory_profiling": True,
        "enable_background_monitoring": True
    }
    
    # Edge Case Testing Configuration
    EDGE_CASE_CONFIG = {
        "missing_customers_count": 10,
        "corrupted_data_count": 5,
        "high_volume_members_count": 3,
        "high_volume_payment_months": 36,
        "complex_failure_chains_count": 8,
        "concurrent_access_threads": 10,
        "concurrent_access_members": 50
    }
    
    # CI/CD Integration Configuration
    CICD_CONFIG = {
        "fail_on_performance_threshold": True,
        "fail_on_memory_threshold": True,
        "fail_on_timeout": True,
        "generate_junit_xml": True,
        "generate_performance_report": True,
        "artifact_retention_days": 30
    }
    
    # Database Configuration
    DATABASE_CONFIG = {
        "connection_pool_size": 10,
        "query_timeout_seconds": 30,
        "transaction_timeout_seconds": 300,
        "enable_query_cache": True,
        "max_query_log_entries": 1000
    }
    
    @classmethod
    def get_test_config(cls, scale: str) -> Dict[str, Any]:
        """Get complete configuration for a test scale"""
        
        if scale not in cls.TEST_SCALES:
            raise ValueError(f"Unknown test scale: {scale}. Available: {list(cls.TEST_SCALES.keys())}")
        
        base_config = cls.TEST_SCALES[scale].copy()
        
        # Add background job config if available
        if scale in cls.BACKGROUND_JOB_CONFIG:
            base_config["background_jobs"] = cls.BACKGROUND_JOB_CONFIG[scale]
        
        # Add common configurations
        base_config.update({
            "payment_history": cls.PAYMENT_HISTORY_CONFIG,
            "monitoring": cls.MONITORING_CONFIG,
            "database": cls.DATABASE_CONFIG,
            "system_requirements": cls.SYSTEM_REQUIREMENTS
        })
        
        return base_config
    
    @classmethod
    def get_performance_thresholds(cls, scale: str) -> Dict[str, float]:
        """Get performance thresholds for a test scale"""
        
        config = cls.get_test_config(scale)
        
        return {
            "max_execution_time": config["max_execution_time"],
            "min_throughput_members_per_sec": config["min_throughput_members_per_sec"],
            "max_memory_usage_mb": config["max_memory_usage_mb"],
            "timeout_seconds": config["timeout_seconds"]
        }
    
    @classmethod
    def validate_system_requirements(cls, scale: str) -> Dict[str, Any]:
        """Validate system meets requirements for test scale"""
        
        import psutil
        
        config = cls.get_test_config(scale)
        requirements = config["system_requirements"]
        
        # Check memory
        available_memory_gb = psutil.virtual_memory().available / (1024**3)
        memory_ok = available_memory_gb >= requirements["minimum_memory_gb"]
        
        # Check CPU
        cpu_count = psutil.cpu_count()
        cpu_ok = cpu_count >= requirements["minimum_cpu_cores"]
        
        # Check disk space
        disk_usage = psutil.disk_usage("/")
        available_disk_gb = disk_usage.free / (1024**3)
        disk_ok = available_disk_gb >= requirements["disk_space_gb"]
        
        return {
            "scale": scale,
            "memory_check": {
                "passed": memory_ok,
                "available_gb": available_memory_gb,
                "required_gb": requirements["minimum_memory_gb"]
            },
            "cpu_check": {
                "passed": cpu_ok,
                "available_cores": cpu_count,
                "required_cores": requirements["minimum_cpu_cores"]
            },
            "disk_check": {
                "passed": disk_ok,
                "available_gb": available_disk_gb,
                "required_gb": requirements["disk_space_gb"]
            },
            "overall_passed": memory_ok and cpu_ok and disk_ok
        }
    
    @classmethod
    def get_optimized_config_for_environment(cls) -> Dict[str, Any]:
        """Get configuration optimized for current environment"""
        
        import psutil
        
        # Detect system capabilities
        memory_gb = psutil.virtual_memory().total / (1024**3)
        cpu_cores = psutil.cpu_count()
        
        # Select appropriate default scale based on system capabilities
        if memory_gb >= 16 and cpu_cores >= 8:
            recommended_scale = "stress"
        elif memory_gb >= 8 and cpu_cores >= 4:
            recommended_scale = "performance"
        elif memory_gb >= 4 and cpu_cores >= 2:
            recommended_scale = "integration"
        else:
            recommended_scale = "smoke"
        
        return {
            "recommended_scale": recommended_scale,
            "system_capabilities": {
                "memory_gb": memory_gb,
                "cpu_cores": cpu_cores
            },
            "scale_config": cls.get_test_config(recommended_scale)
        }


# Environment-Specific Configurations

class DevelopmentConfig(ScalabilityTestConfig):
    """Configuration optimized for development environments"""
    
    # Reduce scales for faster development testing
    TEST_SCALES = ScalabilityTestConfig.TEST_SCALES.copy()
    TEST_SCALES.update({
        "smoke": {
            **ScalabilityTestConfig.TEST_SCALES["smoke"],
            "member_count": 50,  # Reduced for faster dev testing
            "max_payment_months": 3
        },
        "integration": {
            **ScalabilityTestConfig.TEST_SCALES["integration"],
            "member_count": 200,  # Reduced for dev
            "max_payment_months": 6
        }
    })


class ProductionConfig(ScalabilityTestConfig):
    """Configuration for production-like testing environments"""
    
    # More stringent performance requirements
    TEST_SCALES = ScalabilityTestConfig.TEST_SCALES.copy()
    
    for scale_name, scale_config in TEST_SCALES.items():
        scale_config.update({
            "min_throughput_members_per_sec": scale_config["min_throughput_members_per_sec"] * 1.5,
            "max_memory_usage_mb": scale_config["max_memory_usage_mb"] * 0.8
        })


class CIConfig(ScalabilityTestConfig):
    """Configuration optimized for CI/CD environments"""
    
    # Faster, more focused testing for CI
    TEST_SCALES = {
        "ci_smoke": {
            "member_count": 25,
            "max_payment_months": 2,
            "description": "Ultra-fast CI smoke test",
            "timeout_seconds": 30,
            "max_execution_time": 15.0,
            "min_throughput_members_per_sec": 2.0,
            "max_memory_usage_mb": 150.0
        },
        "ci_integration": {
            "member_count": 100,
            "max_payment_months": 6,
            "description": "CI integration test",
            "timeout_seconds": 120,
            "max_execution_time": 60.0,
            "min_throughput_members_per_sec": 2.0,
            "max_memory_usage_mb": 300.0
        }
    }


# Configuration Factory

def get_config_for_environment(environment: str = "development") -> ScalabilityTestConfig:
    """
    Get configuration class optimized for specific environment
    
    Args:
        environment: Environment type ("development", "production", "ci")
        
    Returns:
        Configuration class instance
    """
    
    config_map = {
        "development": DevelopmentConfig,
        "dev": DevelopmentConfig,
        "production": ProductionConfig,
        "prod": ProductionConfig,
        "ci": CIConfig,
        "cicd": CIConfig
    }
    
    config_class = config_map.get(environment.lower(), ScalabilityTestConfig)
    return config_class()


# Utility Functions

def print_config_summary(config: ScalabilityTestConfig, scale: str):
    """Print a summary of the configuration for a given scale"""
    
    test_config = config.get_test_config(scale)
    thresholds = config.get_performance_thresholds(scale)
    
    print(f"\n📋 Configuration Summary for {scale.upper()} scale:")
    print("=" * 50)
    print(f"Members: {test_config['member_count']}")
    print(f"Max Payment Months: {test_config['max_payment_months']}")
    print(f"Timeout: {test_config['timeout_seconds']}s")
    print(f"Max Execution Time: {thresholds['max_execution_time']}s")
    print(f"Min Throughput: {thresholds['min_throughput_members_per_sec']} members/s")
    print(f"Max Memory: {thresholds['max_memory_usage_mb']}MB")
    print(f"Description: {test_config['description']}")
    
    if "background_jobs" in test_config:
        bg_config = test_config["background_jobs"]
        print(f"\nBackground Jobs:")
        print(f"  Members: {bg_config['member_count']}")
        print(f"  Timeout: {bg_config['timeout_seconds']}s")
        print(f"  Min Completion Rate: {bg_config['min_completion_rate']:.1%}")


def validate_config_compatibility(config: ScalabilityTestConfig, scale: str) -> bool:
    """Validate that system can handle the specified configuration"""
    
    validation_result = config.validate_system_requirements(scale)
    
    if not validation_result["overall_passed"]:
        print(f"\n❌ System does not meet requirements for {scale} scale:")
        
        for check_name, check_result in validation_result.items():
            if check_name.endswith("_check") and not check_result["passed"]:
                print(f"  - {check_name}: {check_result}")
        
        return False
    
    print(f"✅ System meets requirements for {scale} scale")
    return True


if __name__ == "__main__":
    """Command-line interface for configuration testing"""
    
    import argparse
    
    parser = argparse.ArgumentParser(description="Scalability Test Configuration Utility")
    parser.add_argument("--environment", choices=["development", "production", "ci"],
                       default="development", help="Environment type")
    parser.add_argument("--scale", choices=["smoke", "integration", "performance", "stress", "maximum"],
                       default="smoke", help="Test scale")
    parser.add_argument("--validate-system", action="store_true",
                       help="Validate system requirements")
    parser.add_argument("--show-optimized", action="store_true",
                       help="Show optimized configuration for current system")
    
    args = parser.parse_args()
    
    # Get configuration for environment
    config = get_config_for_environment(args.environment)
    
    # Show configuration summary
    print_config_summary(config, args.scale)
    
    # Validate system requirements if requested
    if args.validate_system:
        validate_config_compatibility(config, args.scale)
    
    # Show optimized configuration if requested
    if args.show_optimized:
        optimized = config.get_optimized_config_for_environment()
        print(f"\n🎯 Optimized Configuration:")
        print(f"Recommended Scale: {optimized['recommended_scale']}")
        print(f"System Memory: {optimized['system_capabilities']['memory_gb']:.1f}GB")
        print(f"System CPU Cores: {optimized['system_capabilities']['cpu_cores']}")