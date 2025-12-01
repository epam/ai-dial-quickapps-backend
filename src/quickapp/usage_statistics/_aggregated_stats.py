from typing import Literal


class _AggregatedStats:
    def __init__(
        self,
        deployment_name: str,
        deployment_id: str,
        total_prompt_tokens: int | Literal["-"],
        total_completion_tokens: int | Literal["-"],
        total_cost: float | Literal["-"],
    ):
        self._deployment_name = deployment_name
        self._deployment_id = deployment_id
        self._total_prompt_tokens = total_prompt_tokens
        self._total_completion_tokens = total_completion_tokens
        self._total_cost = total_cost

    @property
    def deployment_name(self) -> str:
        return self._deployment_name

    @property
    def deployment_id(self) -> str:
        return self._deployment_id

    @property
    def total_prompt_tokens(self) -> int | Literal["-"]:
        return self._total_prompt_tokens

    @property
    def total_completion_tokens(self) -> int | Literal["-"]:
        return self._total_completion_tokens

    @property
    def total_cost(self) -> float | Literal["-"]:
        return self._total_cost

    def add_prompt_tokens(self, tokens: int) -> None:
        if isinstance(self.total_prompt_tokens, int):
            self._total_prompt_tokens += tokens  # type: ignore[operator]

    def add_completion_tokens(self, tokens: int) -> None:
        if isinstance(self.total_completion_tokens, int):
            self._total_completion_tokens += tokens  # type: ignore[operator]

    def add_total_cost(self, cost: float | Literal["-"]) -> None:
        if isinstance(self.total_cost, float) and isinstance(cost, float):
            self._total_cost += cost  # type: ignore[operator]
