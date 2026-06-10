from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedOffloadConfig:
    """Per-request resolved offload settings, computed once and shared.

    `enabled` already folds in the read-back availability gate, so the
    processor stays oblivious to the dial-files coupling. `missing_read_back_tools`
    is non-empty only when offload was requested but its read-back tools are not
    exposed — the single signal the initialization-warning provider needs.
    """

    enabled: bool
    size_threshold: int
    excluded_tools: frozenset[str]
    missing_read_back_tools: tuple[str, ...] = ()
