import sys

from .formatting import format_total


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        return 2
    price, quantity = args
    print(format_total([(price, int(quantity))]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
