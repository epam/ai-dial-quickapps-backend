from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.exceptions import InvalidRequestError

# Expected raw shape (pseudo-regex): (System)? (User Assistant)* User
#
# The orchestrator persists tool-call history in
# custom_content.state[TOOL_EXECUTION_HISTORY] on assistant messages;
# raw TOOL messages or inline tool_calls are not part of the client contract.


def validate_messages_shape(messages: list[Message]) -> None:
    """Enforce the raw-input messages contract; raise InvalidRequestError on mismatch.

    Raised before the `with response.create_single_choice()` block in
    `_QuickAppCompletion.chat_completion` so the exception reaches the
    aidial_sdk exception handler and produces HTTP 400 with the full
    violation list in `display_message`.
    """
    if not messages:
        _raise_violations(["Messages array must not be empty."])

    illegal_role_violations = _collect_illegal_role_violations(messages)
    if illegal_role_violations:
        _raise_violations(illegal_role_violations)

    sequence_violations = _collect_sequence_violations(messages)
    if sequence_violations:
        _raise_violations(sequence_violations)


def _collect_illegal_role_violations(messages: list[Message]) -> list[str]:
    violations: list[str] = []
    for index, message in enumerate(messages):
        if message.role == Role.TOOL:
            violations.append(
                f"Message at index {index}: role '{Role.TOOL.value}' is not allowed in raw input."
            )
        elif message.role == Role.SYSTEM and index != 0:
            violations.append(
                f"Message at index {index}: role '{Role.SYSTEM.value}' is only allowed at index 0."
            )
    return violations


def _collect_sequence_violations(messages: list[Message]) -> list[str]:
    violations: list[str] = []
    offset = 1 if messages[0].role == Role.SYSTEM else 0
    tail_len = len(messages) - offset

    if tail_len == 0:
        violations.append("Messages array must contain at least one user message.")
        return violations

    for index in range(offset, len(messages)):
        expected = Role.USER if (index - offset) % 2 == 0 else Role.ASSISTANT
        actual = messages[index].role
        if actual != expected:
            violations.append(
                f"Message at index {index}: "
                f"expected role '{expected.value}', got '{actual.value}'."
            )

    # When tail length is even, alternation would expect assistant at the last
    # position, so a non-user last message is not caught by the loop above.
    # Fire this rule only in that slot to avoid duplicating alternation errors.
    if tail_len % 2 == 0 and messages[-1].role != Role.USER:
        violations.append(
            f"Messages must end with a user message, "
            f"but index {len(messages) - 1} has role '{messages[-1].role.value}'."
        )

    return violations


def _raise_violations(violations: list[str]) -> None:
    display_message = "Invalid messages array:\n" + "\n".join(f"- {v}" for v in violations)
    raise InvalidRequestError(
        message="Invalid messages array",
        display_message=display_message,
    )
