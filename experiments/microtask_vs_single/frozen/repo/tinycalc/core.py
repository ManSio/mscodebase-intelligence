from decimal import Decimal


def mean(values):
    return sum(values)


def round_money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))
