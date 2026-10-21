from .core import round_money


def format_total(items):
    total = sum(float(price) * qty for price, qty in items)
    return f"${total:.2f}"
