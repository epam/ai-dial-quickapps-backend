import copy
import json
import re
import types
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict


class TemplateError(ValueError):
    """A template is malformed or refers to a path the context model does not have."""


class TemplateResolutionError(TemplateError):
    """A well-formed template could not be resolved against a concrete context.

    Messages name the placeholder path and the failing segment, never context values.
    """


class _Placeholder(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    segments: tuple[str | int, ...]


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INDEX = re.compile(r"\[(-?\d+)\]")


def contains_placeholder(value: Any) -> bool:
    """True if any string value (recursively) holds a ``${...}`` placeholder.

    Raises ``TemplateError`` on malformed placeholders. Dict keys are never templated.
    """
    if isinstance(value, str):
        return any(isinstance(part, _Placeholder) for part in _parse(value))
    if isinstance(value, dict):
        return any(contains_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_placeholder(v) for v in value)
    return False


def validate_template_paths(arguments: dict[str, Any], root_model: type[BaseModel]) -> None:
    """Statically check every placeholder path against *root_model*.

    Raises ``TemplateError`` for syntax errors and for paths the model does not define.
    """
    for placeholder in _collect_placeholders(arguments):
        _check_path(placeholder, root_model)


def render_arguments(arguments: dict[str, Any], context: BaseModel) -> dict[str, Any]:
    """Return a copy of *arguments* with every placeholder resolved against *context*.

    Raises ``TemplateResolutionError`` when a path cannot be resolved at runtime.
    """
    if not contains_placeholder(arguments):
        return copy.deepcopy(arguments)
    data = context.model_dump(mode="json")
    rendered = _render_value(arguments, data)
    assert isinstance(rendered, dict)
    return rendered


def _parse(template: str) -> list[str | _Placeholder]:
    parts: list[str | _Placeholder] = []
    literal: list[str] = []
    i = 0
    while i < len(template):
        if template.startswith("\\${", i):
            literal.append("${")
            i += 3
        elif template.startswith("${", i):
            if literal:
                parts.append("".join(literal))
                literal = []
            placeholder, i = _parse_placeholder(template, i)
            parts.append(placeholder)
        else:
            literal.append(template[i])
            i += 1
    if literal:
        parts.append("".join(literal))
    return parts


def _parse_placeholder(template: str, start: int) -> tuple[_Placeholder, int]:
    match = _IDENT.match(template, start + 2)
    if match is None:
        raise TemplateError(f"invalid placeholder at position {start}: expected an identifier")
    segments: list[str | int] = [match.group()]
    pos = match.end()
    while pos < len(template):
        char = template[pos]
        if char == "}":
            path = template[start + 2 : pos]
            return _Placeholder(path=path, segments=tuple(segments)), pos + 1
        if char == ".":
            match = _IDENT.match(template, pos + 1)
            if match is None:
                raise TemplateError(
                    f"invalid placeholder at position {start}: expected a field name after '.'"
                )
            segments.append(match.group())
            pos = match.end()
        elif char == "[":
            index = _INDEX.match(template, pos)
            if index is None:
                raise TemplateError(
                    f"invalid placeholder at position {start}: expected an integer index"
                )
            segments.append(int(index.group(1)))
            pos = index.end()
        else:
            raise TemplateError(
                f"invalid placeholder at position {start}: unexpected character {char!r}"
            )
    raise TemplateError(f"invalid placeholder at position {start}: missing closing '}}'")


def _collect_placeholders(value: Any) -> list[_Placeholder]:
    if isinstance(value, str):
        return [part for part in _parse(value) if isinstance(part, _Placeholder)]
    if isinstance(value, dict):
        return [p for v in value.values() for p in _collect_placeholders(v)]
    if isinstance(value, list):
        return [p for v in value for p in _collect_placeholders(v)]
    return []


def _strip_optional(tp: Any) -> Any:
    if get_origin(tp) in (Union, types.UnionType):
        args = [arg for arg in get_args(tp) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp


def _is_free_form(tp: Any) -> bool:
    return tp is Any or tp is dict or get_origin(tp) is dict


def _type_name(tp: Any) -> str:
    return getattr(tp, "__name__", None) or str(tp)


def _check_path(placeholder: _Placeholder, root_model: type[BaseModel]) -> None:
    current: Any = root_model
    prefix = f"invalid placeholder ${{{placeholder.path}}}"
    for segment in placeholder.segments:
        current = _strip_optional(current)
        if _is_free_form(current):
            return
        if isinstance(segment, int):
            if get_origin(current) is not list:
                raise TemplateError(
                    f"{prefix}: index [{segment}] applied to non-list type {_type_name(current)}"
                )
            (current,) = get_args(current)
            continue
        if not (isinstance(current, type) and issubclass(current, BaseModel)):
            raise TemplateError(f"{prefix}: cannot read field '{segment}' of {_type_name(current)}")
        if segment in current.model_fields:
            current = current.model_fields[segment].annotation
        elif segment in current.model_computed_fields:
            current = current.model_computed_fields[segment].return_type
        else:
            raise TemplateError(f"{prefix}: unknown field '{segment}' on {current.__name__}")


def _render_value(value: Any, data: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _render_string(value, data)
    if isinstance(value, dict):
        return {key: _render_value(item, data) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_value(item, data) for item in value]
    return value


def _render_string(template: str, data: dict[str, Any]) -> Any:
    parts = _parse(template)
    if len(parts) == 1 and isinstance(parts[0], _Placeholder):
        return _resolve(parts[0], data)
    rendered: list[str] = []
    for part in parts:
        if isinstance(part, _Placeholder):
            rendered.append(_stringify(_resolve(part, data)))
        else:
            rendered.append(part)
    return "".join(rendered)


def _resolve(placeholder: _Placeholder, data: dict[str, Any]) -> Any:
    current: Any = data
    prefix = f"cannot resolve ${{{placeholder.path}}}"
    for segment in placeholder.segments:
        if current is None:
            raise TemplateResolutionError(f"{prefix}: value is empty before '{segment}'")
        if isinstance(segment, int):
            if not isinstance(current, list) or not -len(current) <= segment < len(current):
                raise TemplateResolutionError(f"{prefix}: index [{segment}] is not available")
            current = current[segment]
        else:
            if not isinstance(current, dict) or segment not in current:
                raise TemplateResolutionError(f"{prefix}: no field '{segment}'")
            current = current[segment]
    if current is None:
        raise TemplateResolutionError(f"{prefix}: value is empty")
    return current


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
