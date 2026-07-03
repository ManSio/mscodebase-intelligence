
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
