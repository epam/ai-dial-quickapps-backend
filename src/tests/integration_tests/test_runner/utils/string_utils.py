import os
import re


def truncate_string(input_string, max_length, suffix='...'):
    if len(input_string) <= max_length:
        return input_string
    else:
        return input_string[: max_length - len(suffix)] + suffix


def extract_total_price(input_string):
    pattern = r'[0-9\.]+(?=\s*$)'
    match = re.search(pattern, input_string)

    if match:
        return float(match.group(0))
    else:
        return 0
