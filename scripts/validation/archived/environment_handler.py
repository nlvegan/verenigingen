#!/usr/bin/env python3
"""
Consolidated Environment Handler for Validation Scripts
Provides unified Frappe environment initialization and error handling
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from contextlib import contextmanager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EnvironmentConfig:
    """Configuration for Frappe environment initialization."""
    
    # Default configuration values
    DEFAULT_SITE = "dev.veganisme.net"
    DEFAULT_APP = "verenigingen"
    DEFAULT_BENCH_PATH = "/home/frappe/frappe-bench"
    
    # Environment variable names
    ENV_SITE = "FRAPPE_SITE"
    ENV_BENCH_PATH = "FRAPPE_BENCH_PATH"
    ENV_APP = "FRAPPE_APP"
    
    @classmethod
    def get_site(cls) -> str:
        """Get site name from environment or default."""
        return os.environ.get(cls.ENV_SITE, cls.DEFAULT_SITE)
    
    @classmethod
    def get_bench_path(cls) -> str:
        """Get bench path from environment or default."""
        return os.environ.get(cls.ENV_BENCH_PATH, cls.DEFAULT_BENCH_PATH)
    
    @classmethod
    def get_app(cls) -> str:
        """Get app name from environment or default."""
        return os.environ.get(cls.ENV_APP, cls.DEFAULT_APP)
    
    @classmethod
    def get_app_path(cls) -> str:
        """Get full path to the app."""
        bench_path = cls.get_bench_path()
        app = cls.get_app()
        return os.path.join(bench_path, "apps", app)


class FrappeEnvironment:
    """Manages Frappe environment initialization and cleanup."""
    
    def __init__(self, site: Optional[str] = None, bench_path: Optional[str] = None):
        """Initialize environment configuration."""
        self.site = site or EnvironmentConfig.get_site()
        self.bench_path = bench_path or EnvironmentConfig.get_bench_path()
        self.frappe = None
        self._initialized = False
        
    def _setup_python_path(self) -> None:
        """Add Frappe paths to Python path."""
        # Add virtual environment site-packages
        venv_path = os.path.join(self.bench_path, "env", "lib", "python3.12", "site-packages")
        if os.path.exists(venv_path) and venv_path not in sys.path:
            sys.path.insert(0, venv_path)
        
        # Add Frappe app path
        frappe_path = os.path.join(self.bench_path, "apps", "frappe")
        if frappe_path not in sys.path:
            sys.path.insert(0, frappe_path)
            
        # Add bench path for site packages
        bench_site_path = os.path.join(self.bench_path, "sites")
        if bench_site_path not in sys.path:
            sys.path.insert(0, bench_site_path)
            
    def initialize(self, connect_db: bool = True) -> None:
        """Initialize Frappe environment.
        
        Args:
            connect_db: Whether to connect to database (default: True)
        """
        if self._initialized:
            return
            
        try:
            # Setup Python path
            self._setup_python_path()
            
            # Import Frappe
            import frappe
            self.frappe = frappe
            
            # Initialize Frappe
            try:
                # Check if already initialized
                _ = frappe.local.site
            except (AttributeError, RuntimeError):
                # Not initialized, do it now
                frappe.init(site=self.site, sites_path=os.path.join(self.bench_path, "sites"))
                
            # Connect to database if requested
            if connect_db:
                try:
                    _ = frappe.db
                except (AttributeError, RuntimeError):
                    frappe.connect()
                
            self._initialized = True
            logger.debug(f"Frappe environment initialized for site: {self.site}")
            
        except ImportError as e:
            logger.error(f"Failed to import Frappe: {e}")
            logger.error("Please ensure you're running this script from the Frappe bench directory")
            raise
            
        except Exception as e:
            logger.error(f"Failed to initialize Frappe environment: {e}")
            raise
            
    def cleanup(self) -> None:
        """Clean up Frappe environment."""
        if self.frappe and self._initialized:
            try:
                self.frappe.destroy()
                self._initialized = False
                logger.debug("Frappe environment cleaned up")
            except Exception as e:
                logger.warning(f"Error during cleanup: {e}")
                
    @contextmanager
    def context(self, connect_db: bool = True):
        """Context manager for Frappe environment.
        
        Usage:
            with FrappeEnvironment().context() as env:
                # Use env.frappe to access Frappe
                docs = env.frappe.get_all("DocType")
        """
        try:
            self.initialize(connect_db=connect_db)
            yield self
        finally:
            self.cleanup()


class ValidationEnvironment:
    """Specialized environment for validation scripts."""
    
    def __init__(self):
        """Initialize validation environment."""
        self.env = FrappeEnvironment()
        self.app_path = EnvironmentConfig.get_app_path()
        self._doctype_cache = {}
        
    @contextmanager
    def validation_context(self, load_doctypes: bool = True):
        """Context manager with validation-specific setup.
        
        Args:
            load_doctypes: Whether to preload DocType definitions
        """
        with self.env.context() as env:
            self.frappe = env.frappe
            
            if load_doctypes:
                self._load_doctypes()
                
            yield self
            
    def _load_doctypes(self) -> None:
        """Preload DocType definitions for validation."""
        try:
            # Load commonly used DocTypes
            common_doctypes = [
                "Member", "Membership", "Chapter", "Volunteer",
                "SEPA Mandate", "Sales Invoice", "Payment Entry"
            ]
            
            for doctype in common_doctypes:
                try:
                    meta = self.frappe.get_meta(doctype)
                    self._doctype_cache[doctype] = {
                        "fields": [f.fieldname for f in meta.fields],
                        "meta": meta
                    }
                except Exception as e:
                    logger.debug(f"Could not load DocType {doctype}: {e}")
                    
        except Exception as e:
            logger.warning(f"Error preloading DocTypes: {e}")
            
    def get_doctype_fields(self, doctype: str) -> list:
        """Get fields for a DocType from cache or database.
        
        Args:
            doctype: Name of the DocType
            
        Returns:
            List of field names
        """
        if doctype in self._doctype_cache:
            return self._doctype_cache[doctype]["fields"]
            
        try:
            meta = self.frappe.get_meta(doctype)
            fields = [f.fieldname for f in meta.fields]
            self._doctype_cache[doctype] = {
                "fields": fields,
                "meta": meta
            }
            return fields
        except Exception as e:
            logger.warning(f"Could not get fields for {doctype}: {e}")
            return []
            
    def validate_field_exists(self, doctype: str, fieldname: str) -> bool:
        """Check if a field exists in a DocType.
        
        Args:
            doctype: Name of the DocType
            fieldname: Name of the field
            
        Returns:
            True if field exists, False otherwise
        """
        fields = self.get_doctype_fields(doctype)
        return fieldname in fields


def get_validation_environment() -> ValidationEnvironment:
    """Factory function to get validation environment.
    
    Returns:
        Configured ValidationEnvironment instance
    """
    return ValidationEnvironment()


def initialize_standalone_validator():
    """Initialize environment for standalone validator scripts.
    
    This function handles the common initialization pattern used
    by most validation scripts.
    
    Returns:
        Tuple of (frappe module, app_path string)
    """
    env = FrappeEnvironment()
    env.initialize()
    return env.frappe, EnvironmentConfig.get_app_path()


# Backward compatibility functions
def init_frappe_environment(site: Optional[str] = None) -> Any:
    """Legacy function for initializing Frappe environment.
    
    Deprecated: Use FrappeEnvironment or ValidationEnvironment instead.
    """
    logger.warning("init_frappe_environment is deprecated. Use FrappeEnvironment class instead.")
    env = FrappeEnvironment(site=site)
    env.initialize()
    return env.frappe


if __name__ == "__main__":
    # Test the environment handler
    print("Testing Environment Handler...")
    print(f"Site: {EnvironmentConfig.get_site()}")
    print(f"Bench Path: {EnvironmentConfig.get_bench_path()}")
    print(f"App: {EnvironmentConfig.get_app()}")
    print(f"App Path: {EnvironmentConfig.get_app_path()}")
    
    # Test Frappe initialization
    print("\nTesting Frappe initialization...")
    with FrappeEnvironment().context() as env:
        print(f"Frappe version: {env.frappe.__version__}")
        print(f"Site: {env.frappe.local.site}")
        
    # Test validation environment
    print("\nTesting validation environment...")
    with ValidationEnvironment().validation_context() as val_env:
        print(f"Loaded {len(val_env._doctype_cache)} DocTypes")
        
        # Test field validation
        if val_env.validate_field_exists("Member", "first_name"):
            print("✓ Member.first_name exists")
        else:
            print("✗ Member.first_name not found")
            
    print("\nEnvironment handler test complete!")