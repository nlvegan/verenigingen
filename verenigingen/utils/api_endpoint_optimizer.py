"""
API endpoint optimization utility for Verenigingen app

This utility applies code quality improvements to API endpoints:
- Standardized error handling
- Performance monitoring
- Input validation and sanitization
- Role-based access control
- Rate limiting
- Caching optimization
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List

import frappe

from verenigingen.utils.config_manager import ConfigManager
from verenigingen.utils.error_handling import get_logger


class APIEndpointOptimizer:
    """Utility to optimize API endpoints across the codebase"""

    def __init__(self):
        self.logger = get_logger("verenigingen.api_optimizer")
        self.api_directory = Path(frappe.get_app_path("verenigingen", "api"))
        self.optimization_stats = {"files_processed": 0, "endpoints_optimized": 0, "errors": []}

    def optimize_all_endpoints(self, dry_run: bool = True) -> Dict[str, Any]:
        """
        Optimize all API endpoints in the app

        Args:
            dry_run: If True, only analyze without making changes

        Returns:
            Dictionary with optimization results
        """
        self.logger.info(f"Starting API endpoint optimization (dry_run={dry_run})")

        api_files = list(self.api_directory.glob("*.py"))

        for api_file in api_files:
            if api_file.name == "__init__.py":
                continue

            try:
                self._optimize_file(api_file, dry_run)
                self.optimization_stats["files_processed"] += 1
            except Exception as e:
                error_msg = f"Failed to optimize {api_file.name}: {str(e)}"
                self.logger.error(error_msg)
                self.optimization_stats["errors"].append(error_msg)

        return self.optimization_stats

    def _optimize_file(self, file_path: Path, dry_run: bool) -> None:
        """Optimize a single API file"""

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        original_content = content

        # Apply optimizations
        content = self._add_imports(content)
        content = self._optimize_endpoints(content)
        content = self._add_validation(content)
        content = self._improve_error_handling(content)

        if content != original_content:
            if not dry_run:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)

                self.logger.info(f"Optimized {file_path.name}")
            else:
                self.logger.info(f"Would optimize {file_path.name}")

    def _add_imports(self, content: str) -> str:
        """Add necessary imports for optimization utilities"""

        # Check if imports already exist
        if "from verenigingen.utils.error_handling import" in content:
            return content

        import_block = """
# Import enhanced utilities
from verenigingen.utils.error_handling import (
    handle_api_error, ValidationError, PermissionError,
    validate_required_fields, log_error
)
from verenigingen.utils.performance_utils import performance_monitor, QueryOptimizer, cached
from verenigingen.utils.api_validators import (
    validate_api_input, APIValidator, require_roles, rate_limit
)
from verenigingen.utils.config_manager import ConfigManager
"""

        # Find a good place to insert imports (after existing imports)
        lines = content.split("\n")
        insert_index = 0

        for i, line in enumerate(lines):
            if line.startswith("import ") or line.startswith("from "):
                insert_index = i + 1
            elif line.strip() == "" and insert_index > 0:
                break

        lines.insert(insert_index, import_block)
        return "\n".join(lines)

    def _optimize_endpoints(self, content: str) -> str:
        """Add decorators to API endpoints"""

        # Pattern to match API endpoint definitions
        endpoint_pattern = r"(@frappe\.whitelist\([^)]*\)\s*\n)(def\s+\w+\([^)]*\):)"

        def add_decorators(match):
            whitelist_decorator = match.group(1)
            function_def = match.group(2)

            # Determine appropriate decorators based on function name and parameters
            decorators = []

            # Add error handling to all endpoints
            decorators.append("@handle_api_error")

            # Add performance monitoring
            if any(keyword in function_def.lower() for keyword in ["bulk", "export", "process", "send"]):
                decorators.append("@performance_monitor(threshold_ms=5000)")
            else:
                decorators.append("@performance_monitor(threshold_ms=1000)")

            # Add role requirements for admin functions
            if any(
                keyword in function_def.lower()
                for keyword in ["approve", "reject", "delete", "bulk", "admin"]
            ):
                decorators.append('@require_roles(["System Manager", "Verenigingen Administrator"])')

            # Add rate limiting for resource-intensive operations
            if any(keyword in function_def.lower() for keyword in ["export", "bulk", "send", "process"]):
                decorators.append("@rate_limit(max_requests=5, window_minutes=60)")
            elif "validate" in function_def.lower():
                decorators.append("@rate_limit(max_requests=30, window_minutes=60)")

            # Add caching for read-only operations
            if any(keyword in function_def.lower() for keyword in ["get_", "list_", "fetch_"]):
                decorators.append("@cached(ttl=300)")

            decorator_block = "\n".join(decorators) + "\n"

            return whitelist_decorator + decorator_block + function_def

        return re.sub(endpoint_pattern, add_decorators, content, flags=re.MULTILINE)

    def _add_validation(self, content: str) -> str:
        """Add input validation to functions"""

        # This is a simplified approach - in practice, would need more sophisticated parsing
        function_pattern = r'(def\s+\w+\([^)]*\):\s*\n\s*"""[^"]*"""\s*\n)'

        def add_validation_block(match):
            function_header = match.group(1)

            # Extract parameter names from function signature
            param_match = re.search(r"def\s+\w+\(([^)]*)\)", function_header)
            if param_match:
                params = param_match.group(1).split(",")
                required_params = []

                for param in params:
                    param = param.strip()
                    if "=" not in param and param not in ["self", "*args", "**kwargs"]:
                        param_name = param.split(":")[0].strip()
                        if param_name:
                            required_params.append(param_name)

                if required_params:
                    validation_block = """
    # Validate required inputs
    validate_required_fields(
        {{{", ".join(f'"{p}": {p}' for p in required_params)}}},
        {required_params}
    )

    # Sanitize text inputs
    {chr(10).join(f'    {p} = APIValidator.sanitize_text({p}, max_length=200) if isinstance({p}, str) else {p}' for p in required_params)}

"""
                    return function_header + validation_block

            return function_header

        return re.sub(function_pattern, add_validation_block, content, flags=re.MULTILINE)

    def _improve_error_handling(self, content: str) -> str:
        """Improve error handling patterns"""

        # Replace basic frappe.logger() calls with enhanced logging
        content = re.sub(r"frappe\.logger\(\)\.error\(([^)]+)\)", r'log_error(\1, "API Error")', content)

        # Replace frappe.throw with appropriate exceptions
        content = re.sub(r'frappe\.throw\(_\("([^"]+)"\)\)', r'raise ValidationError("\1")', content)

        # Replace basic exception handling
        content = re.sub(
            rf'except Exception as e:\s*\n\s*return {"success": False, "error": str\(e\)}',
            r'except Exception as e:\n        log_error(f"Unexpected error: {str(e)}", "API Error")\n        raise',
            content,
        )

        return content

    def analyze_endpoint_performance(self) -> Dict[str, Any]:
        """Analyze API endpoints for performance bottlenecks"""

        analysis = {
            "slow_endpoints": [],
            "n_plus_one_risks": [],
            "missing_caching": [],
            "missing_validation": [],
        }

        api_files = list(self.api_directory.glob("*.py"))

        for api_file in api_files:
            if api_file.name == "__init__.py":
                continue

            try:
                with open(api_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # Analyze for performance issues
                self._analyze_file_performance(api_file.name, content, analysis)

            except Exception as e:
                self.logger.error(f"Failed to analyze {api_file.name}: {str(e)}")

        return analysis

    def _analyze_file_performance(self, filename: str, content: str, analysis: Dict[str, Any]) -> None:
        """Analyze a single file for performance issues"""

        # Check for potential N+1 query patterns
        if re.search(r"for\s+\w+\s+in\s+\w+:.*frappe\.db\.get_value", content, re.DOTALL):
            analysis["n_plus_one_risks"].append({"file": filename, "issue": "Potential N+1 query in loop"})

        # Check for missing caching on read operations
        get_functions = re.findall(r"def\s+(get_\w+|list_\w+|fetch_\w+)", content)
        for func in get_functions:
            if "@cached" not in content:
                analysis["missing_caching"].append(
                    {"file": filename, "function": func, "suggestion": "Consider adding @cached decorator"}
                )

        # Check for missing input validation
        if "@validate_api_input" not in content and "validate_required_fields" not in content:
            analysis["missing_validation"].append(
                {"file": filename, "issue": "No input validation decorators found"}
            )

        # Check for complex operations without performance monitoring
        if any(keyword in content.lower() for keyword in ["bulk", "export", "process", "send"]):
            if "@performance_monitor" not in content:
                analysis["slow_endpoints"].append(
                    {"file": filename, "issue": "Complex operations without performance monitoring"}
                )

    def generate_optimization_report(self) -> Dict[str, Any]:
        """Generate comprehensive optimization report"""

        analysis = self.analyze_endpoint_performance()
        stats = self.optimization_stats.copy()

        report = {
            "summary": {
                "total_files": len(list(self.api_directory.glob("*.py"))) - 1,  # Exclude __init__.py
                "files_processed": stats["files_processed"],
                "endpoints_optimized": stats["endpoints_optimized"],
                "errors": len(stats["errors"]),
            },
            "performance_analysis": analysis,
            "recommendations": self._generate_recommendations(analysis),
            "next_steps": [
                "Run the optimizer with dry_run=False to apply changes",
                "Add tests for optimized endpoints",
                "Monitor performance metrics after deployment",
                "Consider implementing API documentation generation",
            ],
        }

        return report

    def _generate_recommendations(self, analysis: Dict[str, Any]) -> List[str]:
        """Generate optimization recommendations based on analysis"""

        recommendations = []

        if analysis["n_plus_one_risks"]:
            recommendations.append(
                "Address N+1 query risks by using QueryOptimizer.bulk_get_linked_docs() "
                "or implementing JOIN queries"
            )

        if analysis["missing_caching"]:
            recommendations.append(
                "Add caching to read-only endpoints using @cached decorator " "to reduce database load"
            )

        if analysis["missing_validation"]:
            recommendations.append(
                "Implement input validation using APIValidator utilities "
                "to prevent security vulnerabilities"
            )

        if analysis["slow_endpoints"]:
            recommendations.append(
                "Add performance monitoring to track slow operations " "and identify bottlenecks"
            )

        recommendations.extend(
            [
                "Consider implementing API versioning for backward compatibility",
                "Add comprehensive API documentation with examples",
                "Implement API testing suite with performance benchmarks",
                "Set up monitoring and alerting for API performance metrics",
            ]
        )

        return recommendations


# CLI functions for running the optimizer


@frappe.whitelist()
def run_api_optimization(dry_run=True):
    """Run API endpoint optimization"""
    optimizer = APIEndpointOptimizer()
    return optimizer.optimize_all_endpoints(dry_run=dry_run)


@frappe.whitelist()
def analyze_api_performance():
    """Analyze API endpoint performance"""
    optimizer = APIEndpointOptimizer()
    return optimizer.analyze_endpoint_performance()


@frappe.whitelist()
def generate_api_report():
    """Generate comprehensive API optimization report"""
    optimizer = APIEndpointOptimizer()
    return optimizer.generate_optimization_report()


# Example usage:
# bench --site dev.veganisme.net execute verenigingen.utils.api_endpoint_optimizer.generate_api_report
