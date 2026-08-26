"""RPN evaluator using Calculator via Operation dataclass."""
from src.calc import Calculator, Operation


def evaluate(rpn: str) -> float:
    calc = Calculator(precision=3)
    stack: list[float] = []
    for token in rpn.split():
        if token == "+":
            b, a = stack.pop(), stack.pop()
            stack.append(calc.apply(Operation("add", (a, b))))
        elif token == "-":
            b, a = stack.pop(), stack.pop()
            stack.append(calc.apply(Operation("sub", (a, b))))
        elif token == "*":
            b, a = stack.pop(), stack.pop()
            stack.append(calc.apply(Operation("mul", (a, b))))
        elif token == "/":
            b, a = stack.pop(), stack.pop()
            stack.append(calc.apply(Operation("div", (a, b))))
        else:
            stack.append(float(token))
    return stack[-1]