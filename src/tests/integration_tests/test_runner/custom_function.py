class CustomFunction:
    @staticmethod
    def contains(actual: str, expected: str) -> bool:
        return expected in actual

    @staticmethod
    def not_contains(actual: str, expected: str) -> bool:
        return expected not in actual
