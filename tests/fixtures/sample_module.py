"""Sample module used to test deep-spec doc generation (signature + docstring)."""


GLOBAL = 42


class Calculator:
    """A calculator with a | pipe in its docstring.

    Second line of the class docstring.
    """

    def add(self, a: int, b: int = 0) -> int:
        """Add two integers.

        Returns:
            int: the sum.
        """
        return a + b

    def _helper(self, x):
        """Private helper."""
        return x


def standalone(value: str) -> str:
    """Echo the |input| value."""
    return value
