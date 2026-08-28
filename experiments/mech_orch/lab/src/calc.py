"""Calculator core — small realistic module with a planted bug."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Operation:
    name: str
    args: tuple


class Calculator:
    def __init__(self, precision: int = 2) -> None:
        self.precision = precision

    def add(self, a: float, b: float) -> float:
        return round(a + b, self.precision)

    def sub(self, a: float, b: float) -> float:
        return round(a - b, self.precision)

    def mul(self, a: float, b: float) -> float:
        return round(a * b, self.precision)

    def div(self, a: float, b: float) -> float:
        if b == 0:
            raise ZeroDivisionError("division by zero")
        return round(a / b, self.precision)

    def apply(self, op: Operation) -> float:
        fn = getattr(self, op.name, None)
        if fn is None:
            raise ValueError(f"unknown operation: {op.name}")
        return fn(*op.args)