from aidial_sdk.chat_completion import Message, Role
from aidial_sdk.exceptions import InvalidRequestError

# Expected raw shape (pseudo-regex):
#   (System)? (User Assistant Tool*)* (User | Tool+)
#
# TOOL messages are allowed immediately after an ASSISTANT message that has
# non-empty tool_calls (external tool result flow). Each TOOL message must
# reference a tool_call_id from the preceding ASSISTANT's tool_calls.


def validate_messages_shape(messages: list[Message]) -> None:
    """Enforce the raw-input messages contract; raise InvalidRequestError on mismatch.

    Raised before the `with response.create_single_choice()` block in
    `_QuickAppCompletion.chat_completion` so the exception reaches the
    aidial_sdk exception handler and produces HTTP 400 with the full
    violation list in `display_message`.
    """
    if not messages:
        _raise_violations(["Messages array must not be empty."])

    violations = _collect_all_violations(messages)
    if violations:
        _raise_violations(violations)


def _collect_all_violations(messages: list[Message]) -> list[str]:
    violations: list[str] = []

    illegal_system_violations = _collect_illegal_system_violations(messages)
    if illegal_system_violations:
        violations.extend(illegal_system_violations)
        return violations

    violations.extend(_collect_sequence_violations(messages))
    violations.extend(_collect_tool_message_violations(messages))
    return violations


def _collect_illegal_system_violations(messages: list[Message]) -> list[str]:
    violations: list[str] = []
    for index, message in enumerate(messages):
        if message.role == Role.SYSTEM and index != 0:
            violations.append(
                f"Message at index {index}: role '{Role.SYSTEM.value}' is only allowed at index 0."
            )
    return violations


def _collect_sequence_violations(messages: list[Message]) -> list[str]:
    """Validate the role alternation pattern allowing TOOL after ASSISTANT with tool_calls."""
    violations: list[str] = []
    offset = 1 if messages[0].role == Role.SYSTEM else 0

    if len(messages) - offset == 0:
        violations.append("Messages array must contain at least one user message.")
        return violations

    # Walk the sequence enforcing: USER, ASSISTANT, (TOOL*), USER, ASSISTANT, (TOOL*), ...
    # The sequence may end with USER or with TOOL+ (after ASSISTANT with tool_calls).
    expected = Role.USER
    preceding_assistant_has_tool_calls = False

    for index in range(offset, len(messages)):
        actual = messages[index].role

        if actual == Role.TOOL:
            if not preceding_assistant_has_tool_calls:
                violations.append(
                    f"Message at index {index}: role 'tool' is only allowed "
                    f"immediately after an assistant message with tool_calls."
                )
            continue

        if actual != expected:
            violations.append(
                f"Message at index {index}: "
                f"expected role '{expected.value}', got '{actual.value}'."
            )

        if actual == Role.ASSISTANT:
            preceding_assistant_has_tool_calls = bool(messages[index].tool_calls)
            expected = Role.USER
        elif actual == Role.USER:
            preceding_assistant_has_tool_calls = False
            expected = Role.ASSISTANT

    # Final message must be USER or TOOL (after ASSISTANT with tool_calls).
    last = messages[-1]
    if last.role not in (Role.USER, Role.TOOL):
        violations.append(
            f"Messages must end with a user or tool message, "
            f"but index {len(messages) - 1} has role '{last.role.value}'."
        )

    return violations


def _collect_tool_message_violations(messages: list[Message]) -> list[str]:
    """Validate that each TOOL message's tool_call_id matches the preceding ASSISTANT."""
    violations: list[str] = []
    preceding_tool_call_ids: set[str] = set()

    for index, message in enumerate(messages):
        if message.role == Role.ASSISTANT and message.tool_calls:
            preceding_tool_call_ids = {tc.id for tc in message.tool_calls if tc.id}
        elif message.role == Role.TOOL:
            tool_call_id = message.tool_call_id
            if not tool_call_id:
                violations.append(
                    f"Message at index {index}: tool message must have a tool_call_id."
                )
            elif tool_call_id not in preceding_tool_call_ids:
                violations.append(
                    f"Message at index {index}: tool_call_id '{tool_call_id}' "
                    f"does not match any tool call in the preceding assistant message."
                )
        elif message.role != Role.ASSISTANT:
            preceding_tool_call_ids = set()

    return violations


def _raise_violations(violations: list[str]) -> None:
    display_message = "Invalid messages array:\n" + "\n".join(f"- {v}" for v in violations)
    raise InvalidRequestError(
        message="Invalid messages array",
        display_message=display_message,
    )
