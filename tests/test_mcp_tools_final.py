#!/usr/bin/env python3
"""
Final MCP Tool Demonstration and Verification
This script tests various MCP tools to identify working and problematic ones.
"""

import os
import sys
import time
import json
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

def create_test_scenario():
    """Create a realistic test scenario."""
    print("🔍 Creating test scenario...")

    # Create a file with intentional bugs for testing
    test_file = Path("MSCodeBase/test_bugs.py")
    test_file.write_text('''
"""File with intentional bugs for testing."""

import os
import sys
from typing import List

# Intentional bugs
class BuggyClass:
    """Class with intentional bugs."""

    def __init__(self):
        self.undefined_var = None

    def buggy_method(self):
        """Method with intentional bugs."""
        # This will cause NameError
        result = undefined_variable + 1

        # This will cause ZeroDivisionError
        try:
            division_result = 1 / 0
        except:
            pass

        return result

# Function with syntax issues
def syntax_error_function():
    """Function with syntax issues."""
    # Missing closing parenthesis
    print("This function has syntax issues")

    # Unclosed string
    bad_string = "This string is not closed properly

    return bad_string

# Function that should work fine
def good_function():
    """A well-written function."""
    return "This function works correctly"

# Main execution
if __name__ == "__main__":
    print("Testing MCP tool detection...")

    # Test buggy class
    buggy_obj = BuggyClass()

    try:
        result = buggy_obj.buggy_method()
        print(f"Buggy method result: {result}")
    except Exception as e:
        print(f"Buggy method error: {e}")

    # Test syntax error function
    try:
        result = syntax_error_function()
        print(f"Syntax error function result: {result}")
    except Exception as e:
        print(f"Syntax error function error: {e}")

    print(f"Good function result: {good_function()}")
''')

    print("✅ Test scenario created")

def test_tool_with_timeout(tool_func, *args, timeout=30, **kwargs):
    """Test a tool with timeout to detect hanging tools."""
    print(f"🔍 Testing tool with timeout {timeout}s...")
    start_time = time.time()

    try:
        result = tool_func(*args, **kwargs)
        elapsed = time.time() - start_time

        if elapsed > timeout:
            print(f"⚠️  TIMEOUT: Tool took {elapsed:.1f}s (limit: {timeout}s)")
            return {"status": "timeout", "result": None, "time": elapsed}
        elif result is None:
            print(f"❌ FAILED: Tool returned None")
            return {"status": "failed", "result": None, "time": elapsed}
        else:
            print(f"✅ SUCCESS: Tool completed in {elapsed:.1f}s")
            return {"status": "success", "result": result, "time": elapsed}
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ ERROR: {str(e)[:100]} ({elapsed:.1f}s)")
        return {"status": "error", "result": str(e), "time": elapsed}

def run_comprehensive_tests():
    """Run comprehensive MCP tool tests."""
    print("🚀 Starting Comprehensive MCP Tool Test")
    print("=" * 60)

    test_results = {}

    # Test basic tools
    print("\n" + "="*60)
    print("🔧 TESTING BASIC TOOLS")
    print("="*60)

    # Test read_file
    try:
        from tools import read_file
        result = test_tool_with_timeout(read_file, 10, "MSCodeBase/AGENT_DIARY.md")
        test_results["read_file"] = result
    except Exception as e:
        print(f"❌ read_file import failed: {e}")
        test_results["read_file"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test grep
    try:
        from tools import grep
        result = test_tool_with_timeout(grep, 10, "def get_stale_files", "MSCodeBase/src/core/index_guard.py")
        test_results["grep"] = result
    except Exception as e:
        print(f"❌ grep import failed: {e}")
        test_results["grep"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test find_path
    try:
        from tools import find_path
        result = test_tool_with_timeout(find_path, 10, "*.py", "MSCodeBase/src")
        test_results["find_path"] = result
    except Exception as e:
        print(f"❌ find_path import failed: {e}")
        test_results["find_path"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test index tools
    print("\n" + "="*60)
    print("📊 TESTING INDEX TOOLS")
    print("="*60)

    # Test get_index_status
    try:
        from tools import get_index_status
        result = test_tool_with_timeout(get_index_status, 10)
        test_results["get_index_status"] = result
    except Exception as e:
        print(f"❌ get_index_status import failed: {e}")
        test_results["get_index_status"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_index_progress
    try:
        from tools import get_index_progress
        result = test_tool_with_timeout(get_index_progress, 10)
        test_results["get_index_progress"] = result
    except Exception as e:
        print(f"❌ get_index_progress import failed: {e}")
        test_results["get_index_progress"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_index_timeline
    try:
        from tools import get_index_timeline
        result = test_tool_with_timeout(get_index_timeline, 10)
        test_results["get_index_timeline"] = result
    except Exception as e:
        print(f"❌ get_index_timeline import failed: {e}")
        test_results["get_index_timeline"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test analysis tools
    print("\n" + "="*60)
    print("🔍 TESTING ANALYSIS TOOLS")
    print("="*60)

    # Test get_symbol_info
    try:
        from tools import get_symbol_info
        result = test_tool_with_timeout(get_symbol_info, 10, "get_stale_files")
        test_results["get_symbol_info"] = result
    except Exception as e:
        print(f"❌ get_symbol_info import failed: {e}")
        test_results["get_symbol_info"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_related_files
    try:
        from tools import get_related_files
        result = test_tool_with_timeout(get_related_files, 10, "MSCodeBase", "src/core/index_guard.py")
        test_results["get_related_files"] = result
    except Exception as e:
        print(f"❌ get_related_files import failed: {e}")
        test_results["get_related_files"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test impact_analysis
    try:
        from tools import impact_analysis
        result = test_tool_with_timeout(impact_analysis, 10, "get_stale_files")
        test_results["impact_analysis"] = result
    except Exception as e:
        print(f"❌ impact_analysis import failed: {e}")
        test_results["impact_analysis"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test intel tools
    print("\n" + "="*60)
    print("🧠 TESTING INTEL TOOLS")
    print("="*60)

    # Test intel_get_runtime_status
    try:
        from tools import intel_get_runtime_status
        result = test_tool_with_timeout(intel_get_runtime_status, 10)
        test_results["intel_get_runtime_status"] = result
    except Exception as e:
        print(f"❌ intel_get_runtime_status import failed: {e}")
        test_results["intel_get_runtime_status"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test intel_trigger_reindex
    try:
        from tools import intel_trigger_reindex
        result = test_tool_with_timeout(intel_trigger_reindex, 10)
        test_results["intel_trigger_reindex"] = result
    except Exception as e:
        print(f"❌ intel_trigger_reindex import failed: {e}")
        test_results["intel_trigger_reindex"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test intel_get_job_status (skip as needs job_id)
    try:
        from tools import intel_get_job_status
        test_results["intel_get_job_status"] = {"status": "skipped", "result": "needs_job_id", "time": 0}
    except Exception as e:
        print(f"❌ intel_get_job_status import failed: {e}")
        test_results["intel_get_job_status"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test search tools
    print("\n" + "="*60)
    print("🔎 TESTING SEARCH TOOLS")
    print("="*60)

    # Test search_code
    try:
        from tools import search_code
        result = test_tool_with_timeout(search_code, 10, "get_stale_files")
        test_results["search_code"] = result
    except Exception as e:
        print(f"❌ search_code import failed: {e}")
        test_results["search_code"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test smart_search
    try:
        from tools import smart_search
        result = test_tool_with_timeout(smart_search, 10, "get_stale_files", "fast")
        test_results["smart_search"] = result
    except Exception as e:
        print(f"❌ smart_search import failed: {e}")
        test_results["smart_search"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test context_search
    try:
        from tools import context_search, read_file
        code = read_file("MSCodeBase/src/core/index_guard.py")
        if code:
            result = test_tool_with_timeout(context_search, 10, selected_code=code[:500])
            test_results["context_search"] = result
        else:
            test_results["context_search"] = {"status": "skipped", "result": "no_code", "time": 0}
    except Exception as e:
        print(f"❌ context_search import failed: {e}")
        test_results["context_search"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test cross-project tools
    print("\n" + "="*60)
    print("🌐 TESTING CROSS-PROJECT TOOLS")
    print("="*60)

    # Test cross_project_deps
    try:
        from tools import cross_project_deps
        result = test_tool_with_timeout(cross_project_deps, 10, action="graph")
        test_results["cross_project_deps"] = result
    except Exception as e:
        print(f"❌ cross_project_deps import failed: {e}")
        test_results["cross_project_deps"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test cross_repo_search
    try:
        from tools import cross_repo_search
        result = test_tool_with_timeout(cross_repo_search, 10, "get_stale_files")
        test_results["cross_repo_search"] = result
    except Exception as e:
        print(f"❌ cross_repo_search import failed: {e}")
        test_results["cross_repo_search"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test diagnostic tools
    print("\n" + "="*60)
    print("🩺 TESTING DIAGNOSTIC TOOLS")
    print("="*60)

    # Test get_health_report
    try:
        from tools import get_health_report
        result = test_tool_with_timeout(get_health_report, 10, project_root="MSCodeBase")
        test_results["get_health_report"] = result
    except Exception as e:
        print(f"❌ get_health_report import failed: {e}")
        test_results["get_health_report"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_logs
    try:
        from tools import get_logs
        result = test_tool_with_timeout(get_logs, 10, project_root="MSCodeBase")
        test_results["get_logs"] = result
    except Exception as e:
        print(f"❌ get_logs import failed: {e}")
        test_results["get_logs"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_bug_correlation
    try:
        from tools import get_bug_correlation
        result = test_tool_with_timeout(get_bug_correlation, 10, project_root="MSCodeBase")
        test_results["get_bug_correlation"] = result
    except Exception as e:
        print(f"❌ get_bug_correlation import failed: {e}")
        test_results["get_bug_correlation"] = {"status": "import_error", "result": str(e), "time": 0}

    # Test get_hotspots
    try:
        from tools import get_hotspots
        result = test_tool_with_timeout(get_hotspots, 10, project_root="MSCodeBase")
        test_results["get_hotspots"] = result
    except Exception as e:
        print(f"❌ get_hotspots import failed: {e}")
        test_results["get_hotspots"] = {"status": "import_error", "result": str(e), "time": 0}

    return test_results

def analyze_results(all_results):
    """Analyze test results and identify issues."""
    print("\n" + "="*60)
    print("📊 ANALYSIS OF RESULTS")
    print("="*60)

    summary = {
        "total_tools": 0,
        "successful": 0,
        "failed": 0,
        "timeout": 0,
        "error": 0,
        "import_error": 0,
        "skipped": 0,
        "problematic_tools": []
    }

    for category, results in all_results.items():
        print(f"\n📋 Category: {category}")
        for tool_name, result in results.items():
            summary["total_tools"] += 1
            status = result.get("status", "unknown")

            if status == "success":
                summary["successful"] += 1
                print(f"  ✅ {tool_name}: SUCCESS ({result['time']:.1f}s)")
            elif status == "timeout":
                summary["timeout"] += 1
                summary["problematic_tools"].append(tool_name)
                print(f"  ⚠️  {tool_name}: TIMEOUT ({result['time']:.1f}s)")
            elif status == "error":
                summary["error"] += 1
                summary["problematic_tools"].append(tool_name)
                print(f"  ❌ {tool_name}: ERROR ({result['time']:.1f}s)")
            elif status == "import_error":
                summary["import_error"] += 1
                summary["problematic_tools"].append(tool_name)
                print(f"  🚫 {tool_name}: IMPORT ERROR")
            elif status == "skipped":
                summary["skipped"] += 1
                print(f"  ⏭️  {tool_name}: SKIPPED")

    print(f"\n🎯 OVERALL SUMMARY:")
    print(f"  Total tools tested: {summary['total_tools']}")
    print(f"  Successful: {summary['successful']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  Timeout: {summary['timeout']}")
    print(f"  Error: {summary['error']}")
    print(f"  Import Error: {summary['import_error']}")
    print(f"  Skipped: {summary['skipped']}")

    if summary["problematic_tools"]:
        print(f"\n⚠️  PROBLEMATIC TOOLS:")
        for tool in summary["problematic_tools"]:
            print(f"  - {tool}")

    return summary

def main():
    """Run comprehensive MCP tool demonstration."""
    print("🚀 Starting MCP Tool Demonstration and Verification")
    print("=" * 60)

    # Create test scenario
    create_test_scenario()

    # Run comprehensive tests
    test_results = run_comprehensive_tests()

    # Analyze results
    summary = analyze_results(test_results)

    # Save results to file
    results_file = "MSCodeBase/mcp_tool_demonstration_results.json"
    with open(results_file, 'w') as f:
        json.dump({
            "timestamp": time.time(),
            "summary": summary,
            "detailed_results": test_results
        }, f, indent=2)

    print(f"\n💾 Results saved to: {results_file}")

    # Return appropriate exit code
    if summary["timeout"] > 0 or summary["error"] > 0 or summary["import_error"] > 0:
        print(f"\n⚠️  Demonstration completed with issues. {summary['timeout']} timeouts, {summary['error']} errors, {summary['import_error']} import errors.")
        return 1
    else:
        print(f"\n🎉 All tools work successfully!")
        return 0

if __name__ == "__main__":
    sys.exit(main())
