#!/usr/bin/env python3
"""
Configuration Manager for Validation Scripts
Handles loading and management of validation configuration from YAML file
"""

import os
import yaml
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class EnvironmentConfig:
    """Environment configuration settings."""
    site: str = "dev.veganisme.net"
    bench_path: str = "/home/frappe/frappe-bench"
    app_name: str = "verenigingen"
    python_version: str = "3.12"
    
    @classmethod
    def from_dict(cls, data: dict) -> 'EnvironmentConfig':
        """Create from dictionary."""
        return cls(**data)
    
    def override_from_env(self):
        """Override settings from environment variables."""
        self.site = os.environ.get("FRAPPE_SITE", self.site)
        self.bench_path = os.environ.get("FRAPPE_BENCH_PATH", self.bench_path)
        self.app_name = os.environ.get("FRAPPE_APP", self.app_name)
        
    @property
    def app_path(self) -> str:
        """Get full application path."""
        return os.path.join(self.bench_path, "apps", self.app_name)
    
    @property
    def venv_path(self) -> str:
        """Get virtual environment path."""
        return os.path.join(self.bench_path, "env", "lib", f"python{self.python_version}", "site-packages")


@dataclass 
class ValidationConfig:
    """Validation configuration settings."""
    default_level: str = "balanced"
    exclude_patterns: List[str] = field(default_factory=list)
    preload_doctypes: List[str] = field(default_factory=list)
    field_validation: Dict[str, Any] = field(default_factory=dict)
    template_validation: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ValidationConfig':
        """Create from dictionary."""
        return cls(
            default_level=data.get("default_level", "balanced"),
            exclude_patterns=data.get("exclude_patterns", []),
            preload_doctypes=data.get("preload_doctypes", []),
            field_validation=data.get("field_validation", {}),
            template_validation=data.get("template_validation", {})
        )
    
    def should_exclude_file(self, file_path: str) -> bool:
        """Check if file should be excluded from validation."""
        from fnmatch import fnmatch
        
        for pattern in self.exclude_patterns:
            if fnmatch(str(file_path), pattern):
                return True
        return False
    
    def should_skip_doctype(self, doctype: str) -> bool:
        """Check if DocType should be skipped."""
        skip_list = self.field_validation.get("skip_doctypes", [])
        return doctype in skip_list
    
    def should_ignore_field(self, field_name: str) -> bool:
        """Check if field should be ignored."""
        from fnmatch import fnmatch
        
        ignore_patterns = self.field_validation.get("ignore_fields", [])
        for pattern in ignore_patterns:
            if fnmatch(field_name, pattern):
                return True
        return False


@dataclass
class ReportingConfig:
    """Reporting configuration settings."""
    default_format: str = "text"
    output_directory: str = "validation_reports"
    max_issues_per_file: int = 20
    group_by_type: bool = True
    include_snippets: bool = True
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ReportingConfig':
        """Create from dictionary."""
        return cls(**data)
    
    @property
    def output_path(self) -> Path:
        """Get output directory path."""
        return Path(self.output_directory)


@dataclass
class PerformanceConfig:
    """Performance configuration settings."""
    max_parallel_files: int = 4
    cache_doctypes: bool = True
    cache_expiry: int = 3600
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PerformanceConfig':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class PrecommitConfig:
    """Pre-commit configuration settings."""
    enabled: bool = False
    fail_on_error: bool = False
    max_new_issues: int = 10
    validators: List[str] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PrecommitConfig':
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", False),
            fail_on_error=data.get("fail_on_error", False),
            max_new_issues=data.get("max_new_issues", 10),
            validators=data.get("validators", [])
        )


@dataclass
class DevelopmentConfig:
    """Development configuration settings."""
    debug: bool = False
    save_cache: bool = True
    cache_directory: str = ".validation_cache"
    
    @classmethod
    def from_dict(cls, data: dict) -> 'DevelopmentConfig':
        """Create from dictionary."""
        return cls(**data)
    
    @property
    def cache_path(self) -> Path:
        """Get cache directory path."""
        return Path(self.cache_directory)


class ConfigManager:
    """Manages validation configuration."""
    
    DEFAULT_CONFIG_FILE = "validation_config.yaml"
    DEFAULT_USER_CONFIG = os.path.expanduser("~/.verenigingen_validation.yaml")
    
    def __init__(self, config_file: Optional[str] = None):
        """Initialize configuration manager.
        
        Args:
            config_file: Path to configuration file (optional)
        """
        self.config_file = config_file or self._find_config_file()
        self.config_data = {}
        
        # Configuration objects
        self.environment = EnvironmentConfig()
        self.validation = ValidationConfig()
        self.reporting = ReportingConfig()
        self.performance = PerformanceConfig()
        self.precommit = PrecommitConfig()
        self.development = DevelopmentConfig()
        
        # Load configuration
        self.load_config()
        
    def _find_config_file(self) -> str:
        """Find configuration file in standard locations."""
        # Check current directory
        current_dir_config = Path.cwd() / self.DEFAULT_CONFIG_FILE
        if current_dir_config.exists():
            return str(current_dir_config)
        
        # Check script directory
        script_dir = Path(__file__).parent
        script_dir_config = script_dir / self.DEFAULT_CONFIG_FILE
        if script_dir_config.exists():
            return str(script_dir_config)
        
        # Check user home directory
        user_config = Path(self.DEFAULT_USER_CONFIG)
        if user_config.exists():
            return str(user_config)
        
        # Return default path (will use defaults if not found)
        return str(script_dir_config)
    
    def load_config(self):
        """Load configuration from file."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.config_data = yaml.safe_load(f) or {}
                    
                # Parse configuration sections
                self._parse_config()
                
                logger.info(f"Loaded configuration from {self.config_file}")
            else:
                logger.info(f"Configuration file not found at {self.config_file}, using defaults")
                
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            logger.info("Using default configuration")
            
        # Override with environment variables
        self.environment.override_from_env()
        
    def _parse_config(self):
        """Parse configuration data into objects."""
        if "environment" in self.config_data:
            self.environment = EnvironmentConfig.from_dict(self.config_data["environment"])
            
        if "validation" in self.config_data:
            self.validation = ValidationConfig.from_dict(self.config_data["validation"])
            
        if "reporting" in self.config_data:
            self.reporting = ReportingConfig.from_dict(self.config_data["reporting"])
            
        if "performance" in self.config_data:
            self.performance = PerformanceConfig.from_dict(self.config_data["performance"])
            
        if "precommit" in self.config_data:
            self.precommit = PrecommitConfig.from_dict(self.config_data["precommit"])
            
        if "development" in self.config_data:
            self.development = DevelopmentConfig.from_dict(self.config_data["development"])
            
    def save_config(self, config_file: Optional[str] = None):
        """Save current configuration to file.
        
        Args:
            config_file: Path to save configuration (uses current file if not specified)
        """
        save_path = config_file or self.config_file
        
        # Build configuration dictionary
        config_data = {
            "environment": {
                "site": self.environment.site,
                "bench_path": self.environment.bench_path,
                "app_name": self.environment.app_name,
                "python_version": self.environment.python_version
            },
            "validation": {
                "default_level": self.validation.default_level,
                "exclude_patterns": self.validation.exclude_patterns,
                "preload_doctypes": self.validation.preload_doctypes,
                "field_validation": self.validation.field_validation,
                "template_validation": self.validation.template_validation
            },
            "reporting": {
                "default_format": self.reporting.default_format,
                "output_directory": self.reporting.output_directory,
                "max_issues_per_file": self.reporting.max_issues_per_file,
                "group_by_type": self.reporting.group_by_type,
                "include_snippets": self.reporting.include_snippets
            },
            "performance": {
                "max_parallel_files": self.performance.max_parallel_files,
                "cache_doctypes": self.performance.cache_doctypes,
                "cache_expiry": self.performance.cache_expiry
            },
            "precommit": {
                "enabled": self.precommit.enabled,
                "fail_on_error": self.precommit.fail_on_error,
                "max_new_issues": self.precommit.max_new_issues,
                "validators": self.precommit.validators
            },
            "development": {
                "debug": self.development.debug,
                "save_cache": self.development.save_cache,
                "cache_directory": self.development.cache_directory
            }
        }
        
        try:
            with open(save_path, 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
            logger.info(f"Configuration saved to {save_path}")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            
    def get_config_summary(self) -> dict:
        """Get configuration summary.
        
        Returns:
            Dictionary with configuration summary
        """
        return {
            "config_file": self.config_file,
            "environment": {
                "site": self.environment.site,
                "app_path": self.environment.app_path
            },
            "validation": {
                "level": self.validation.default_level,
                "exclude_count": len(self.validation.exclude_patterns),
                "preload_count": len(self.validation.preload_doctypes)
            },
            "reporting": {
                "format": self.reporting.default_format,
                "output": self.reporting.output_directory
            },
            "precommit": {
                "enabled": self.precommit.enabled,
                "validators": self.precommit.validators
            }
        }
    
    def print_config(self):
        """Print current configuration."""
        print("\n" + "="*60)
        print("VALIDATION CONFIGURATION")
        print("="*60)
        
        print(f"\nConfiguration File: {self.config_file}")
        print(f"File Exists: {os.path.exists(self.config_file)}")
        
        print("\n[Environment]")
        print(f"  Site: {self.environment.site}")
        print(f"  Bench Path: {self.environment.bench_path}")
        print(f"  App: {self.environment.app_name}")
        print(f"  App Path: {self.environment.app_path}")
        
        print("\n[Validation]")
        print(f"  Default Level: {self.validation.default_level}")
        print(f"  Exclude Patterns: {len(self.validation.exclude_patterns)} patterns")
        print(f"  Preload DocTypes: {len(self.validation.preload_doctypes)} doctypes")
        
        print("\n[Reporting]")
        print(f"  Format: {self.reporting.default_format}")
        print(f"  Output Directory: {self.reporting.output_directory}")
        print(f"  Max Issues/File: {self.reporting.max_issues_per_file}")
        
        print("\n[Performance]")
        print(f"  Max Parallel Files: {self.performance.max_parallel_files}")
        print(f"  Cache DocTypes: {self.performance.cache_doctypes}")
        
        print("\n[Pre-commit]")
        print(f"  Enabled: {self.precommit.enabled}")
        print(f"  Validators: {', '.join(self.precommit.validators) if self.precommit.validators else 'None'}")
        
        print("\n[Development]")
        print(f"  Debug: {self.development.debug}")
        print(f"  Cache Directory: {self.development.cache_directory}")
        
        print("\n" + "="*60)


# Global configuration instance
_config_instance = None


def get_config(config_file: Optional[str] = None) -> ConfigManager:
    """Get or create global configuration instance.
    
    Args:
        config_file: Optional configuration file path
        
    Returns:
        ConfigManager instance
    """
    global _config_instance
    
    if _config_instance is None or config_file:
        _config_instance = ConfigManager(config_file)
        
    return _config_instance


def reset_config():
    """Reset global configuration instance."""
    global _config_instance
    _config_instance = None


if __name__ == "__main__":
    # Test configuration manager
    config = ConfigManager()
    config.print_config()
    
    # Test configuration summary
    print("\n\nConfiguration Summary (JSON):")
    print(json.dumps(config.get_config_summary(), indent=2))
    
    # Test file exclusion
    test_files = [
        "test_member.py",
        "member.py",
        "tests/test_validation.py",
        "migrations/001_update.py"
    ]
    
    print("\n\nFile Exclusion Test:")
    for file in test_files:
        excluded = config.validation.should_exclude_file(file)
        print(f"  {file}: {'EXCLUDED' if excluded else 'INCLUDED'}")