#!/usr/bin/env python3
"""
Test problem for MCP tool demonstration.
This file contains various patterns and issues to test MCP tools.
"""

import os
import sys
from typing import List, Dict, Optional

class TestClass:
    """A test class with various methods."""

    def __init__(self, value: int):
        self.value = value
        self.name = f"Test_{value}"

    def get_value(self) -> int:
        """Return the stored value."""
        return self.value

    def set_value(self, new_value: int) -> None:
        """Set a new value."""
        self.value = new_value

    def calculate_sum(self, numbers: List[int]) -> int:
        """Calculate sum of numbers."""
        return sum(numbers)

    def find_max(self, data: List[int]) -> Optional[int]:
        """Find maximum value in list."""
        if not data:
            return None
        return max(data)

    def process_data(self, input_dict: Dict[str, int]) -> Dict[str, int]:
        """Process dictionary data."""
        result = {}
        for key, value in input_dict.items():
            if value > 0:
                result[key] = value * 2
            else:
                result[key] = value
        return result

def main():
    """Main function for testing."""
    test_obj = TestClass(42)

    # Test basic functionality
    print(f"Initial value: {test_obj.get_value()}")
    test_obj.set_value(100)
    print(f"Updated value: {test_obj.get_value()}")

    # Test calculations
    numbers = [1, 2, 3, 4, 5]
    print(f"Sum: {test_obj.calculate_sum(numbers)}")
    print(f"Max: {test_obj.find_max(numbers)}")

    # Test data processing
    data = {"a": 1, "b": -2, "c": 3}
    print(f"Processed: {test_obj.process_data(data)}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
