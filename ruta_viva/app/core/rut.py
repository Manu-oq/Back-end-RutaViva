import re


def validate_rut(rut: str) -> bool:
    cleaned = re.sub(r"[^0-9kK]", "", rut)
    if len(cleaned) < 2:
        return False

    body = cleaned[:-1]
    dv = cleaned[-1].upper()

    if not body.isdigit():
        return False

    total = 0
    multiplier = 2
    for digit in reversed(body):
        total += int(digit) * multiplier
        multiplier = multiplier + 1 if multiplier < 7 else 2

    remainder = 11 - (total % 11)
    expected_dv = {
        11: "0",
        10: "K",
    }.get(remainder, str(remainder))

    return dv == expected_dv


def format_rut(rut: str) -> str:
    cleaned = re.sub(r"[^0-9kK]", "", rut).upper()
    if len(cleaned) < 2:
        return rut
    body = cleaned[:-1]
    dv = cleaned[-1]
    return f"{body}-{dv}"