from typing import Any

from quickapp.common.perf_timer.period import Period


class PerformanceTimer:
    def __init__(self, name: str | None = None) -> None:
        self.name = name
        self._periods: dict[str, Period] = {}

    def start_period(self, key: str, level: int = 1) -> None:
        p = self._periods.get(key)
        if p is None:
            p = Period(key=key)
            self._periods[key] = p
        p.level = level
        p.start()

    def stop_period(self, key: str) -> None:
        p = self._get_period_or_raise(key)
        p.stop()

    def add_milestone(self, key: str, name: str) -> None:
        p = self._get_period_or_raise(key)
        p.add_milestone(name)

    def _get_period_or_raise(self, key: str) -> Period:
        p = self._periods.get(key)
        if p is None:
            raise KeyError(f"Period '{key}' does not exist.")
        return p

    def get_data(self) -> dict[str, Any]:
        return {
            key: {
                "start_time": p.start_time,
                "end_time": p.end_time,
                "elapsed": p.elapsed,
                "milestones": list(p.milestones),
            }
            for key, p in self._periods.items()
        }

    def get_report_md(self) -> str:
        import time

        lines = []
        hdr = f"## Performance report: {self.name}" if self.name else "## Performance report"
        lines.append(hdr)

        now_monotonic = time.perf_counter()

        for key, p in self._periods.items():
            indent = "  " * (max(1, p.level) - 1)
            lines.append(f"\n{indent}### Period: `{key}`")

            if p.start_time is None:
                lines.append(f"{indent}- Something went wrong: period was never started.")
                continue

            start = p.start_time
            end = p.end_time
            period_end = end if end is not None else now_monotonic
            total_elapsed = period_end - start

            lines.append(f"{indent}- Total_elapsed: {total_elapsed:.2f} seconds")

            if p.milestones:
                lines.append(f"{indent}- milestones:")
                prev_elapsed = 0.0
                prev_label = "start"
                for mname, mtime in p.milestones:
                    # Support both milestone stored as absolute monotonic timestamp or as elapsed since start.
                    if mtime is None:
                        m_elapsed = 0.0
                    elif mtime >= start:
                        m_elapsed = mtime - start
                    else:
                        m_elapsed = float(mtime)

                    delta = m_elapsed - prev_elapsed
                    lines.append(f"{indent}  - `{mname}`: {delta:.2f} seconds from `{prev_label}`")
                    prev_elapsed = m_elapsed
                    prev_label = mname

                # final delta between last milestone and end
                end_delta = max(0.0, total_elapsed - prev_elapsed)
                lines.append(f"{indent}  - `end`: {end_delta:.2f} seconds from `{prev_label}`")

        return "\n".join(lines)

    def get_report_json(self) -> str:
        import json
        import time

        def _r(val):
            return round(val, 2) if val is not None else None

        now_monotonic = time.perf_counter()
        report: dict[str, Any] = {"periods": {}}

        for key, p in self._periods.items():
            start = p.start_time
            end = p.end_time
            period_end = end if end is not None else now_monotonic

            if start is None:
                total_elapsed = None
            else:
                total_elapsed = period_end - start

            period_entry: dict[str, Any] = {
                "start_time": _r(start),
                "end_time": _r(end),
                "total_elapsed": _r(total_elapsed),
                "milestones": [],
            }

            if p.milestones:
                prev_elapsed = 0.0
                prev_label = "start"
                for mname, mtime in p.milestones:
                    if mtime is None:
                        m_elapsed = 0.0
                    elif start is None:
                        try:
                            m_elapsed = float(mtime)
                        except Exception:
                            m_elapsed = 0.0
                    else:
                        if mtime >= start:
                            m_elapsed = mtime - start
                        else:
                            m_elapsed = float(mtime)

                    delta = m_elapsed - prev_elapsed
                    period_entry["milestones"].append(
                        {
                            "name": mname,
                            "elapsed": _r(m_elapsed),
                            "delta_from_prev": _r(delta),
                            "from": prev_label,
                        }
                    )
                    prev_elapsed = m_elapsed
                    prev_label = mname

                end_delta = max(0.0, (total_elapsed or 0.0) - prev_elapsed)
                period_entry["end_delta_from_last_milestone"] = _r(end_delta)

            report["periods"][key] = period_entry

        return json.dumps(report, separators=(",", ":"), ensure_ascii=False)

    def reset(self) -> None:
        self._periods.clear()
