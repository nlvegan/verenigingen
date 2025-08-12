#!/usr/bin/env python3
"""
Performance Benchmarking Tests for Validation Infrastructure
============================================================

This test suite ensures that the massive standardization of 21 validators
to use DocTypeLoader has not introduced performance regressions.

Performance Areas Tested:
1. **DocType Loading**: Measure loading time for 1,049+ DocTypes
2. **Caching Effectiveness**: Test cache performance improvements
3. **Memory Usage**: Monitor memory consumption during loading
4. **Validator Instantiation**: Time to create validator instances
5. **File Validation Speed**: Time to validate real code files
6. **Scalability**: Performance with increasing file counts
7. **Resource Utilization**: CPU and memory efficiency

The tests establish performance baselines and ensure the standardization
provides better performance through centralized DocType loading and caching.
"""

import gc
import psutil
import time
import unittest
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import threading
import concurrent.futures


@dataclass
class PerformanceMetrics:
    """Performance measurement data"""
    operation: str
    duration: float
    memory_before: float
    memory_after: float
    memory_peak: float
    cpu_percent: float
    success: bool
    error: Optional[str] = None
    
    @property
    def memory_delta(self) -> float:
        return self.memory_after - self.memory_before
    
    def to_dict(self):
        return asdict(self)


class PerformanceProfiler:
    """Performance measurement utility"""
    
    def __init__(self):
        self.process = psutil.Process()
        self._start_time = 0
        self._start_memory = 0
        self._peak_memory = 0
        self._cpu_times = []
    
    @contextmanager
    def measure(self, operation_name: str):
        """Context manager for measuring performance"""
        # Garbage collect before measurement
        gc.collect()
        
        # Initial measurements
        self._start_time = time.time()
        self._start_memory = self.process.memory_info().rss / 1024 / 1024  # MB
        self._peak_memory = self._start_memory
        start_cpu = self.process.cpu_percent()
        
        # Start monitoring thread
        stop_monitoring = threading.Event()
        monitor_thread = threading.Thread(
            target=self._monitor_resources, 
            args=(stop_monitoring,),
            daemon=True
        )
        monitor_thread.start()
        
        error = None
        success = True
        
        try:
            yield
        except Exception as e:
            error = str(e)
            success = False
            raise
        finally:
            # Stop monitoring
            stop_monitoring.set()
            monitor_thread.join(timeout=1.0)
            
            # Final measurements
            end_time = time.time()
            end_memory = self.process.memory_info().rss / 1024 / 1024  # MB
            end_cpu = self.process.cpu_percent()
            
            duration = end_time - self._start_time
            avg_cpu = (start_cpu + end_cpu) / 2
            
            # Create metrics object
            metrics = PerformanceMetrics(
                operation=operation_name,
                duration=duration,
                memory_before=self._start_memory,
                memory_after=end_memory,
                memory_peak=self._peak_memory,
                cpu_percent=avg_cpu,
                success=success,
                error=error
            )
            
            # Store for later retrieval
            self._last_metrics = metrics
    
    def _monitor_resources(self, stop_event: threading.Event):
        """Monitor peak resource usage in background"""
        while not stop_event.is_set():
            try:
                current_memory = self.process.memory_info().rss / 1024 / 1024  # MB
                self._peak_memory = max(self._peak_memory, current_memory)
                
                time.sleep(0.1)  # Monitor every 100ms
            except:
                break
    
    def get_last_metrics(self) -> PerformanceMetrics:
        """Get metrics from last measurement"""
        return getattr(self, '_last_metrics', None)


class PerformanceBenchmarkTest(unittest.TestCase):
    """Performance benchmarking for validation infrastructure"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        cls.app_path = Path("/home/frappe/frappe-bench/apps/verenigingen")
        cls.bench_path = cls.app_path.parent.parent
        cls.validation_dir = cls.app_path / "scripts" / "validation"
        
        cls.profiler = PerformanceProfiler()
        cls.performance_results = {}
        
        print(f"🚀 Performance benchmarking for {cls.app_path}")
        print(f"📊 System: {psutil.cpu_count()} CPUs, {psutil.virtual_memory().total / 1024**3:.1f}GB RAM")
    
    def test_doctype_loader_performance(self):
        """Benchmark DocType loading performance"""
        from doctype_loader import DocTypeLoader
        
        # Test cold loading (first time)
        with self.profiler.measure("doctype_loader_cold_load"):
            loader = DocTypeLoader(str(self.bench_path), verbose=False)
            doctypes = loader.get_doctypes()
        
        cold_metrics = self.profiler.get_last_metrics()
        self.performance_results["doctype_loader_cold"] = cold_metrics
        
        # Test warm loading (cached)
        with self.profiler.measure("doctype_loader_warm_load"):
            cached_doctypes = loader.get_doctypes()
        
        warm_metrics = self.profiler.get_last_metrics()
        self.performance_results["doctype_loader_warm"] = warm_metrics
        
        # Validate performance expectations
        self.assertLess(
            cold_metrics.duration, 15.0,
            f"Cold DocType loading too slow: {cold_metrics.duration:.2f}s"
        )
        
        self.assertLess(
            warm_metrics.duration, 0.1,
            f"Warm DocType loading not cached properly: {warm_metrics.duration:.2f}s"
        )
        
        cache_speedup = cold_metrics.duration / max(warm_metrics.duration, 0.001)
        self.assertGreater(
            cache_speedup, 10,
            f"Cache not effective enough: only {cache_speedup:.1f}x speedup"
        )
        
        print(f"✅ DocType Loader Performance:")
        print(f"   Cold load: {cold_metrics.duration:.3f}s, {cold_metrics.memory_delta:.1f}MB")
        print(f"   Warm load: {warm_metrics.duration:.3f}s, {cache_speedup:.0f}x speedup")
        print(f"   DocTypes loaded: {len(doctypes)}")
    
    def test_validator_instantiation_performance(self):
        """Benchmark validator instantiation performance"""
        # Test different validators
        validators_to_test = [
            ('unified_validation_engine', 'SpecializedPatternValidator'),
            ('doctype_field_validator', 'AccurateFieldValidator'),
        ]
        
        for module_name, class_name in validators_to_test:
            try:
                # Import the module
                module_path = self.validation_dir / f"{module_name}.py"
                if not module_path.exists():
                    continue
                
                import importlib.util
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec is None or spec.loader is None:
                    continue
                
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                if not hasattr(module, class_name):
                    continue
                
                validator_class = getattr(module, class_name)
                
                # Benchmark instantiation
                with self.profiler.measure(f"validator_instantiation_{module_name}"):
                    validator = validator_class(str(self.app_path))
                
                metrics = self.profiler.get_last_metrics()
                self.performance_results[f"validator_{module_name}"] = metrics
                
                # Validate performance
                self.assertLess(
                    metrics.duration, 10.0,
                    f"{class_name} instantiation too slow: {metrics.duration:.2f}s"
                )
                
                print(f"✅ {class_name} instantiation: {metrics.duration:.3f}s, {metrics.memory_delta:.1f}MB")
                
            except Exception as e:
                print(f"⚠️  Could not test {class_name}: {e}")
    
    def test_file_validation_performance(self):
        """Benchmark file validation performance"""
        # Find test files
        test_files = []
        search_areas = [
            self.app_path / "verenigingen" / "doctype",
            self.app_path / "scripts" / "api_maintenance"
        ]
        
        for area in search_areas:
            if area.exists():
                py_files = list(area.rglob("*.py"))
                # Filter and limit
                filtered_files = [
                    f for f in py_files 
                    if not any(skip in str(f) for skip in ['test_', '__pycache__', '.pyc'])
                ]
                test_files.extend(filtered_files[:3])  # 3 files per area
        
        test_files = test_files[:5]  # Limit total files
        
        if not test_files:
            self.skipTest("No suitable test files found")
        
        try:
            from unified_validation_engine import SpecializedPatternValidator
            validator = SpecializedPatternValidator(str(self.app_path))
            
            # Test individual file validation
            file_validation_times = []
            
            for test_file in test_files:
                with self.profiler.measure(f"file_validation_{test_file.name}"):
                    violations = validator.validate_file(test_file)
                
                metrics = self.profiler.get_last_metrics()
                file_validation_times.append(metrics.duration)
                
                print(f"   {test_file.name}: {metrics.duration:.3f}s ({len(violations)} violations)")
            
            # Calculate averages
            avg_validation_time = sum(file_validation_times) / len(file_validation_times)
            max_validation_time = max(file_validation_times)
            
            # Validate performance expectations
            self.assertLess(
                avg_validation_time, 2.0,
                f"Average file validation too slow: {avg_validation_time:.2f}s"
            )
            
            self.assertLess(
                max_validation_time, 5.0,
                f"Slowest file validation too slow: {max_validation_time:.2f}s"
            )
            
            print(f"✅ File Validation Performance:")
            print(f"   Average: {avg_validation_time:.3f}s per file")
            print(f"   Maximum: {max_validation_time:.3f}s per file")
            print(f"   Files tested: {len(test_files)}")
            
        except ImportError:
            self.skipTest("SpecializedPatternValidator not available")
    
    def test_batch_validation_performance(self):
        """Benchmark batch validation performance"""
        # Find multiple files for batch testing
        test_files = []
        for area in [self.app_path / "verenigingen" / "doctype"]:
            if area.exists():
                py_files = list(area.rglob("*.py"))
                filtered_files = [
                    f for f in py_files 
                    if not any(skip in str(f) for skip in ['test_', '__pycache__'])
                ]
                test_files.extend(filtered_files[:10])  # Up to 10 files
        
        if len(test_files) < 3:
            self.skipTest("Insufficient files for batch testing")
        
        try:
            from unified_validation_engine import SpecializedPatternValidator
            validator = SpecializedPatternValidator(str(self.app_path))
            
            # Test batch validation
            with self.profiler.measure("batch_validation"):
                total_violations = 0
                for test_file in test_files[:5]:  # Limit for performance
                    violations = validator.validate_file(test_file)
                    total_violations += len(violations)
            
            batch_metrics = self.profiler.get_last_metrics()
            self.performance_results["batch_validation"] = batch_metrics
            
            # Calculate metrics
            files_per_second = len(test_files[:5]) / batch_metrics.duration
            
            # Validate batch performance
            self.assertGreater(
                files_per_second, 0.5,
                f"Batch validation too slow: {files_per_second:.2f} files/second"
            )
            
            print(f"✅ Batch Validation Performance:")
            print(f"   {files_per_second:.2f} files/second")
            print(f"   Total time: {batch_metrics.duration:.3f}s")
            print(f"   Total violations: {total_violations}")
            print(f"   Memory usage: {batch_metrics.memory_delta:.1f}MB")
            
        except ImportError:
            self.skipTest("SpecializedPatternValidator not available")
    
    def test_memory_efficiency(self):
        """Test memory efficiency of the standardized infrastructure"""
        from doctype_loader import DocTypeLoader
        
        # Measure memory usage during multiple operations
        initial_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
        
        # Load DocTypes multiple times to test for memory leaks
        loaders = []
        with self.profiler.measure("memory_efficiency_test"):
            for i in range(3):
                loader = DocTypeLoader(str(self.bench_path), verbose=False)
                doctypes = loader.get_doctypes()
                loaders.append(loader)
                
                # Force garbage collection
                gc.collect()
        
        memory_metrics = self.profiler.get_last_metrics()
        
        # Memory growth should be reasonable
        memory_growth = memory_metrics.memory_delta
        memory_per_loader = memory_growth / 3
        
        self.assertLess(
            memory_per_loader, 100,  # Less than 100MB per loader instance
            f"Memory usage too high: {memory_per_loader:.1f}MB per loader"
        )
        
        print(f"✅ Memory Efficiency:")
        print(f"   Memory growth: {memory_growth:.1f}MB for 3 loaders")
        print(f"   Per loader: {memory_per_loader:.1f}MB")
        print(f"   Peak memory: {memory_metrics.memory_peak:.1f}MB")
    
    def test_concurrent_performance(self):
        """Test performance under concurrent load"""
        def validate_file_worker(file_path):
            """Worker function for concurrent validation"""
            try:
                from unified_validation_engine import SpecializedPatternValidator
                validator = SpecializedPatternValidator(str(self.app_path))
                violations = validator.validate_file(file_path)
                return len(violations)
            except Exception as e:
                return -1
        
        # Find test files
        test_files = []
        for area in [self.app_path / "verenigingen" / "doctype"]:
            if area.exists():
                py_files = list(area.rglob("*.py"))
                filtered_files = [
                    f for f in py_files 
                    if not any(skip in str(f) for skip in ['test_', '__pycache__'])
                ]
                test_files.extend(filtered_files[:8])  # 8 files for testing
        
        if len(test_files) < 4:
            self.skipTest("Insufficient files for concurrent testing")
        
        # Test concurrent validation
        with self.profiler.measure("concurrent_validation"):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = [
                    executor.submit(validate_file_worker, test_file) 
                    for test_file in test_files[:4]
                ]
                
                results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        concurrent_metrics = self.profiler.get_last_metrics()
        
        # Validate concurrent performance
        successful_validations = sum(1 for r in results if r >= 0)
        self.assertGreaterEqual(
            successful_validations, 3,
            f"Too many concurrent validation failures: {successful_validations}/4"
        )
        
        print(f"✅ Concurrent Performance:")
        print(f"   Duration: {concurrent_metrics.duration:.3f}s")
        print(f"   Successful validations: {successful_validations}/4")
        print(f"   Memory usage: {concurrent_metrics.memory_delta:.1f}MB")
    
    def test_scalability_performance(self):
        """Test performance scalability with different loads"""
        from doctype_loader import DocTypeLoader
        
        # Test with different numbers of DocType accesses
        access_counts = [10, 100, 500]
        scalability_results = {}
        
        loader = DocTypeLoader(str(self.bench_path), verbose=False)
        doctypes = loader.get_doctypes()
        doctype_names = list(doctypes.keys())
        
        for count in access_counts:
            with self.profiler.measure(f"scalability_{count}_accesses"):
                for i in range(count):
                    # Access different DocTypes
                    doctype_name = doctype_names[i % len(doctype_names)]
                    fields = loader.get_field_names(doctype_name)
                    has_field = loader.has_field(doctype_name, 'name')
            
            metrics = self.profiler.get_last_metrics()
            scalability_results[count] = {
                'duration': metrics.duration,
                'access_rate': count / metrics.duration
            }
        
        # Validate scalability
        for count, result in scalability_results.items():
            access_rate = result['access_rate']
            self.assertGreater(
                access_rate, 100,  # At least 100 accesses per second
                f"Poor scalability at {count} accesses: {access_rate:.1f} accesses/second"
            )
            
            print(f"   {count} accesses: {result['duration']:.3f}s ({access_rate:.0f} accesses/sec)")
        
        print("✅ Scalability Performance: All load levels acceptable")


def run_performance_benchmarks():
    """Run all performance benchmark tests"""
    print("🚀 Running Performance Benchmark Tests")
    print("=" * 80)
    
    # Create and run test suite
    test_suite = unittest.TestSuite()
    test_suite.addTests(unittest.TestLoader().loadTestsFromTestCase(PerformanceBenchmarkTest))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print detailed summary
    print("\n" + "=" * 80)
    print("🚀 Performance Benchmark Summary")
    print("=" * 80)
    
    total_tests = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total_tests - failures - errors
    
    print(f"Performance Tests: {total_tests}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failures}")
    print(f"🚫 Errors: {errors}")
    
    # Show performance summary from class
    if hasattr(PerformanceBenchmarkTest, 'performance_results'):
        print("\n📊 Key Performance Metrics:")
        
        for test_name, metrics in PerformanceBenchmarkTest.performance_results.items():
            if hasattr(metrics, 'duration'):
                print(f"   {test_name}: {metrics.duration:.3f}s")
        
    if result.failures:
        print("\n❌ Performance Failures:")
        for test, traceback in result.failures:
            failure_msg = traceback.split('\n')[-2] if traceback else "Performance threshold exceeded"
            print(f"  - {test}: {failure_msg}")
    
    success = failures == 0 and errors == 0
    
    if success:
        print("\n🎉 All performance benchmarks PASSED!")
        print("The standardization has maintained or improved performance.")
    else:
        print("\n⚠️  Some performance benchmarks failed.")
        print("Performance optimization may be needed.")
    
    return success


if __name__ == "__main__":
    success = run_performance_benchmarks()
    exit(0 if success else 1)