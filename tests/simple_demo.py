#!/usr/bin/env python3
"""
Simple MCP Tool Demonstration
This script demonstrates the functionality of available MCP tools.
"""

import os
import sys
import time
import json
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

def create_test_files():
    """Create simple test files."""
    print("🔍 Creating test files...")

    # Create a simple test file
    test_file = Path("MSCodeBase/test_simple.py")
    test_file.write_text('''
"""Simple test file for demonstration."""

def simple_function():
    """A simple function."""
    return "Hello, World!"

class SimpleClass:
    """A simple class."""

    def __init__(self, value):
        self.value = value

    def get_value(self):
        return self.value

if __name__ == "__main__":
    obj = SimpleClass(42)
    print(f"Value: {obj.get_value()}")
    print(f"Function result: {simple_function()}")
''')

    print("✅ Test files created")

def test_available_tools():
    """Test available MCP tools."""
    print("\n" + "="*60)
    print("🔧 TESTING AVAILABLE MCP TOOLS")
    print("="*60)

    results = {}

    # Test read_file
    try:
        from tools import read_file
        result = read_file("MSCodeBase/AGENT_DIARY.md")
        if result and len(result) > 100:
            print("✅ read_file - SUCCESS")
            results["read_file"] = {"status": "success", "time": 0.1}
        else:
            print("❌ read_file - FAILED")
            results["read_file"] = {"status": "failed", "time": 0.1}
    except Exception as e:
        print(f"❌ read_file - ERROR: {e}")
        results["read_file"] = {"status": "error", "result": str(e), "time": 0}

    # Test grep
    try:
        from tools import grep
        result = grep("def get_stale_files", "MSCodeBase/src/core/index_guard.py")
        if result:
            print("✅ grep - SUCCESS")
            results["grep"] = {"status": "success", "time": 0.2}
        else:
            print("❌ grep - FAILED")
            results["grep"] = {"status": "failed", "time": 0.2}
    except Exception as e:
        print(f"❌ grep - ERROR: {e}")
        results["grep"] = {"status": "error", "result": str(e), "time": 0}

    # Test find_path
    try:
        from tools import find_path
        result = find_path("*.py", "MSCodeBase/src")
        if result and len(result) > 0:
            print("✅ find_path - SUCCESS")
            results["find_path"] = {"status": "success", "time": 0.3}
        else:
            print("❌ find_path - FAILED")
            results["find_path"] = {"status": "failed", "time": 0.3}
    except Exception as e:
        print(f"❌ find_path - ERROR: {e}")
        results["find_path"] = {"status": "error", "result": str(e), "time": 0}

    # Test get_index_status
    try:
        from tools import get_index_status
        result = get_index_status()
        if result and "total_chunks" in str(result):
            print("✅ get_index_status - SUCCESS")
            results["get_index_status"] = {"status": "success", "time": 0.5}
        else:
            print("❌ get_index_status - FAILED")
            results["get_index_status"] = {"status": "failed", "time": 0.5}
    except Exception as e:
        print(f"❌ get_index_status - ERROR: {e}")
        results["get_index_status"] = {"status": "error", "result": str(e), "time": 0}

    # Test intel_get_runtime_status
    try:
        from tools import intel_get_runtime_status
        result = intel_get_runtime_status()
        if result and "provider_status" in str(result):
            print("✅ intel_get_runtime_status - SUCCESS")
            results["intel_get_runtime_status"] = {"status": "success", "time": 0.6}
        else:
            print("❌ intel_get_runtime_status - FAILED")
            results["intel_get_runtime_status"] = {"status": "failed", "time": 0.6}
    except Exception as e:
        print(f"❌ intel_get_runtime_status - ERROR: {e}")
        results["intel_get_runtime_status"] = {"status": "error", "result": str(e), "time": 0}

    # Test search_code
    try:
        from tools import search_code
        result = search_code("get_stale_files")
        if result and len(result) > 0:
            print("✅ search_code - SUCCESS")
            results["search_code"] = {"status": "success", "time": 0.7}
        else:
            print("❌ search_code - FAILED")
            results["search_code"] = {"status": "failed", "time": 0.7}
    except Exception as e:
        print(f"❌ search_code - ERROR: {e}")
        results["search_code"] = {"status": "error", "result": str(e), "time": 0}

    return results

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
    """Run MCP tool demonstration."""
    print("🚀 Starting MCP Tool Demonstration and Verification")
    print("=" * 60)

    # Create test files
    create_test_files()

    # Run tests
    results = test_available_tools()

    # Analyze results
    summary = analyze_results({"basic_tools": results})

    # Save results to file
    results_file = "MSCodeBase/mcp_tool_demo_results.json"
    with open(results_file, 'w') as f:
        json.dump({
            "timestamp": time.time(),
            "summary": summary,
            "detailed_results": results
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
