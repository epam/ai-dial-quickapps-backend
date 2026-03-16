import time

from pydantic import BaseModel, Field


class Period(BaseModel):
    key: str
    level: int = 1
    start_time: float | None = None
    end_time: float | None = None
    milestones: list[tuple[str, float]] = Field(default_factory=list)

    def start(self) -> None:
        if self.start_time is not None and self.end_time is None:
            raise RuntimeError(f"Period '{self.key}' is already running.")
        self.start_time = time.perf_counter()
        self.end_time = None
        self.milestones.clear()

    def stop(self) -> float:
        if self.start_time is None:
            raise RuntimeError(f"Period '{self.key}' has not been started.")
        if self.end_time is None:
            self.end_time = time.perf_counter()
        return self.elapsed

    def add_milestone(self, name: str) -> None:
        if self.start_time is None:
            raise RuntimeError(f"Period '{self.key}' has not been started.")
        now = time.perf_counter()
        self.milestones.append((name, now))

    @property
    def elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        if self.end_time is None:
            return time.perf_counter() - self.start_time
        return self.end_time - self.start_time
