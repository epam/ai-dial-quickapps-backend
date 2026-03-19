import logging
import os
from collections import defaultdict
from enum import Enum
from typing import Dict

import pytest
import pytest_asyncio
from _pytest.nodes import Node
from pydantic import BaseModel, Field

from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_client import (
    _PyInterpreterClient,
)
from quickapp.internal_tooling.py_interpreter_tooling._py_interpreter_settings import (
    _PyInterpreterSettings,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.common import PyInterpreterSession

logger = logging.getLogger(__name__)
print(" Loading conftest.py")


class FailureReason(Enum):
    ARGUMENTS = "ToolCall argument failures"
    ANSWER = "Answer content similarity failures"
    ROLE = "Message role differs from expected"
    HTTP_STATUS = "Http call status failures"
    CITATION = "Citation failures"
    ATTACHMENT = "Attachment failures"
    TOOL_CALL_COUNT = "Tool call count failures"
    TOOL_CALL_MISMATCH = "Tool call mismatch failures"
    LLM_CACHE_MISSING = "Missing cached LLM responses"
    # Add more reasons as needed

    def __str__(self):
        return self.value


class TestStats(BaseModel):
    name: str
    passed: int
    failed: int
    price: float = 0
    failure_reasons: dict[FailureReason, int] = Field(default_factory=dict)

    @property
    def total(self):
        return self.failed + self.passed

    def __str__(self):
        return f"{self.passed}/{self.total} - {self.name}"

    def to_dict(self):
        return {
            "name": self.name,
            "passed": self.passed,
            "failed": self.failed,
            "price": self.price,
            "failure_reasons": {k.name: v for k, v in self.failure_reasons.items()},
        }

    def increment_failure(self, fr: FailureReason):
        self.failure_reasons[fr] = self.failure_reasons.get(fr, 0) + 1


class SuiteStats(BaseModel):
    test_stat_list: list[TestStats] = Field(default_factory=list)

    @property
    def passed(self):
        return sum(ts.passed for ts in self.test_stat_list)

    @property
    def failed(self):
        return sum(ts.failed for ts in self.test_stat_list)

    @property
    def total(self):
        return self.failed + self.passed

    @property
    def price(self):
        return sum(ts.price for ts in self.test_stat_list)

    @property
    def failure_reasons(self) -> Dict[FailureReason, int]:
        reasons = defaultdict(int)
        for test_stat in self.test_stat_list:
            for reason, count in test_stat.failure_reasons.items():
                reasons[reason] += count
        return reasons

    def __str__(self):
        try:
            p = self.passed / self.total
        except ZeroDivisionError:
            p = 0.0

        header = (
            f"Test Runs: {self.total}, "
            f"Passed: {self.passed}, "
            f"Failed: {self.failed}, "
            f"PassRate: {p:.2%}",
            f"Total Price: {self.price}$",
        )

        # Group failures by reason
        failure_lines = []
        for reason in FailureReason:
            if count := self.failure_reasons.get(reason, 0):
                failure_lines.append(f"{reason}: {count}")

        failure_section = "\n".join(failure_lines) if failure_lines else "No failures"
        test_lines = '\n'.join(str(stat) for stat in self.test_stat_list)

        return (
            f"\n{header}\n"
            f"Failure breakdown:\n{failure_section}\n"
            f"Test results:\n{test_lines}"
        )

    def to_dict(self):
        return {"test_stat_list": [stat.to_dict() for stat in self.test_stat_list]}


def report_test_stats(config, test_stat: TestStats):
    if hasattr(config, 'workerinput'):  # Worker node
        if not hasattr(config, 'worker_stats'):
            config.worker_stats = []
        config.worker_stats.append(test_stat.to_dict())
    else:  # local run from IDE. Test executes on the main node.
        config.test_stats.append(test_stat.to_dict())


@pytest_asyncio.fixture(scope="session")
async def session_fixture():
    logger.info("Starting session_fixture")
    _settings = _PyInterpreterSettings()

    async with _PyInterpreterClient(api_key=_settings.api_key, base_url=_settings.url) as client:
        if _settings.default_session_id:
            if not client.check_session_opened(
                request=PyInterpreterSession(sessionId=_settings.default_session_id)
            ):
                _settings.default_session_id = None

        if not _settings.default_session_id:
            session_id = await client.open_session()
            os.environ["PY_INTERPRETER_DEFAULT_SESSION_ID"] = session_id.sessionId

    # Yield control to tests
    yield
    logger.info("Tearing down session_fixture")

    # Cleanup: Close session if SESSION_ID exists in environment variables
    if "PY_INTERPRETER_DEFAULT_SESSION_ID" in os.environ:
        session_id = os.getenv("PY_INTERPRETER_DEFAULT_SESSION_ID")
        async with _PyInterpreterClient(
            api_key=_settings.api_key,
            base_url=_settings.url,
        ) as client:
            await client.close_session(request=PyInterpreterSession(sessionId=session_id))
            del os.environ["PY_INTERPRETER_DEFAULT_SESSION_ID"]


@pytest.fixture(scope="session")
def unique_port(worker_id):
    """Generate unique port per xdist worker"""
    port = int(os.getenv("MOCK_DIAL_CORE_PORT", "8081"))

    if worker_id == "master":
        # When not using xdist or running with -n0
        return port

    worker_number = int(worker_id.replace("gw", ""))
    return port + worker_number  # Base port + worker offset


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requires_session: mark test as requiring a py_interpreter session"
    )
    if not hasattr(config, "workerinput"):
        config.test_stats = []


def pytest_testnodedown(node: Node, error):
    """Controller hook: called when worker node shuts down"""
    if hasattr(node, 'workeroutput') and 'test_stats' in node.workeroutput:
        node.config.test_stats.extend(node.workeroutput['test_stats'])


def pytest_generate_tests(metafunc):
    if "requires_session" in metafunc.definition.keywords:
        metafunc.fixturenames.append("session_fixture")


def pytest_addoption(parser):
    parser.addoption("--model", action="store", default="", help="Agent LLM model to use in tests")
    parser.addoption(
        "--no-cache", action="store_true", default="", help="Disable cache usage for e2e tests"
    )


def pytest_sessionfinish(session, exitstatus):
    if not hasattr(session.config, 'workerinput'):
        """Controller hook: called after all workers finish"""
        # Convert string keys to FailureReason enum members in all test_stats entries, as
        # session.config.test_stats.failure_reason is dict[str, int], because we can store only primitives there.
        converted_stats = [
            {
                **s,
                "failure_reasons": {
                    FailureReason[k] if isinstance(k, str) else k: v
                    for k, v in s["failure_reasons"].items()
                },
            }
            for s in session.config.test_stats
        ]
        test_stat_list = [TestStats(**s) for s in converted_stats]
        final_stats = SuiteStats(test_stat_list=test_stat_list)
        logger.info("Aggregated Stats:")
        logger.info(str(final_stats))
    if hasattr(session.config, 'workerinput'):
        """Worker hook: called before worker finish"""
        session.config.workeroutput['test_stats'] = [
            dict(stats) for stats in getattr(session.config, 'worker_stats', [])
        ]
