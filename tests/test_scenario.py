#!/usr/bin/env python3
"""
Test scenario for MCP tool demonstration.
This creates a realistic problem scenario to test MCP tools.
"""

import os
import sys
import time
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

def create_test_files():
    """Create test files to simulate a real project scenario."""
    print("📁 Creating test files...")

    # Create a test module
    test_module = Path("MSCodeBase/test_module.py")
    test_module.write_text('''
"""Test module for MCP tool demonstration."""

import os
import sys
from typing import List, Dict, Optional

class DataProcessor:
    """A data processing class with various methods."""

    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.data = []
        self.processed = False

    def load_data(self, file_path: str) -> bool:
        """Load data from file."""
        try:
            with open(file_path, 'r') as f:
                self.data = f.read().splitlines()
            self.processed = True
            return True
        except Exception as e:
            print(f"Error loading data: {e}")
            return False

    def process_items(self, items: List[str]) -> List[str]:
        """Process a list of items."""
        processed = []
        for item in items:
            if item.strip():
                processed.append(item.upper())
        return processed

    def save_results(self, output_path: str) -> bool:
        """Save processed results to file."""
        try:
            with open(output_path, 'w') as f:
                for item in self.data:
                    f.write(f"{item}\n")
            return True
        except Exception as e:
            print(f"Error saving results: {e}")
            return False

    def get_statistics(self) -> Dict[str, int]:
        """Get processing statistics."""
        return {
            "total_items": len(self.data),
            "processed_items": len([x for x in self.data if x.strip()]),
            "empty_items": len([x for x in self.data if not x.strip()])
        }

def main():
    """Main function for testing."""
    processor = DataProcessor()

    # Create test data
    test_data = ["item1", "item2", "", "item3", "item4"]

    # Process data
    processed = processor.process_items(test_data)
    print(f"Processed {len(processed)} items")

    # Get statistics
    stats = processor.get_statistics()
    print(f"Statistics: {stats}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
''')

    # Create a test configuration file
    config_file = Path("MSCodeBase/test_config.json")
    config_file.write_text('''{
    "database": {
        "host": "localhost",
        "port": 5432,
        "name": "test_db"
    },
    "processing": {
        "batch_size": 100,
        "timeout": 30,
        "retries": 3
    },
    "logging": {
        "level": "INFO",
        "file": "app.log"
    }
}''')

    print("✅ Test files created successfully")

def simulate_problem():
    """Simulate a problem scenario to test MCP tools."""
    print("\n🔍 Simulating problem scenario...")

    # Create a file with intentional issues
    problematic_file = Path("MSCodeBase/problematic_code.py")
    problematic_file.write_text('''
"""File with intentional issues for testing."""

import os
import sys
from typing import List

# This should cause issues
def buggy_function():
    """Function with intentional bugs."""
    undefined_variable  # This will cause NameError

    try:
        result = 1 / 0  # Division by zero
    except:
        pass

    return undefined_variable  # This will fail

# Another function with issues
def another_buggy_function():
    """Another function with issues."""
    items = []
    for i in range(10):
        items.append(i / 0)  # Division by zero in loop

    return items

# Function that should work fine
def good_function():
    """A well-written function."""
    return "This function works correctly"

# Main execution
if __name__ == "__main__":
    print("Testing problematic code...")

    try:
        result = buggy_function()
        print(f"Buggy function result: {result}")
    except Exception as e:
        print(f"Buggy function error: {e}")

    try:
        result = another_buggy_function()
        print(f"Another buggy function result: {result}")
    except Exception as e:
        print(f"Another buggy function error: {e}")

    print(f"Good function result: {good_function()}")
''')

    print("✅ Problematic code created for testing")

def main():
    """Create test scenario."""
    print("🚀 Creating MCP Tool Test Scenario")
    print("=" * 50)

    create_test_files()
    simulate_problem()

    print("\n✅ Test scenario created successfully!")
    print("\n📋 Files created:")
    print("  - MSCodeBase/test_module.py")
    print("  - MSCodeBase/test_config.json")
    print("  - MSCodeBase/problematic_code.py")

    return 0

if __name__ == "__main__":
    sys.exit(main())
