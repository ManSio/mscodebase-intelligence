
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
