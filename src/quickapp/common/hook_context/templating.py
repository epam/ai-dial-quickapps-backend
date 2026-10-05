"""Hook argument templating on top of json-e; the only module that imports it."""

import copy
import re
import types
from typing import Any, Union, get_args, get_origin

import jsone
from jsone import builtins as _jsone_builtins
from jsone.AST import ASTNode, BinOp, ContextValue, FunctionCall
from jsone.AST import List as _ListNode
from jsone.AST import Object as _ObjectNode
from jsone.AST import UnaryOp, ValueAccess
from jsone.parser import Parser
from jsone.render import operators as _jsone_operators
from jsone.render import tokenizer
from jsone.shared import JSONTemplateError
from pydantic import BaseModel


class TemplateError(ValueError):
    """A template is malformed or refers to a name the context model does not have."""


class TemplateResolutionError(TemplateError):
    """A well-formed template could not be rendered against a concrete context.

    Messages name the failing template location, never context values.
    """


# A path segment: a field name, a list index, or None for a slice (the list stays a list).
_Segment = str | int | None
_DYNAMIC = object()

_INTERPOLATION_START = re.compile(r"\$?\${")
_ESCAPED_KEY = re.compile(r"\$\$")
_IDENTIFIER_KEY = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*$")
_BINDING_KEY = re.compile(r"(?:each|by)\(([^)]*)\)$")
_EXPRESSION_OPERATORS = ("$eval", "$if")
_BUILTIN_NAMES = frozenset(_jsone_builtins.build()) | {"now"}


def contains_placeholder(value: Any) -> bool:
    """True if *value* holds anything json-e would evaluate: a ``${...}`` interpolation
    in a string (or key), or an operator key such as ``$eval``. Escapes (``$${``, ``$$name``)
    are literals, not placeholders."""
    return _holds_template(value, include_escapes=False)


def _needs_rendering(value: Any) -> bool:
    """Like ``contains_placeholder``, but escapes count too: json-e must unescape them."""
    return _holds_template(value, include_escapes=True)


def _holds_template(value: Any, *, include_escapes: bool) -> bool:
    if isinstance(value, str):
        return any(
            include_escapes or match.group() != "$${"
            for match in _INTERPOLATION_START.finditer(value)
        )
    if isinstance(value, dict):
        return any(
            (include_escapes and _ESCAPED_KEY.match(key) is not None)
            or _IDENTIFIER_KEY.match(key) is not None
            or _holds_template(key, include_escapes=include_escapes)
            or _holds_template(item, include_escapes=include_escapes)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_holds_template(item, include_escapes=include_escapes) for item in value)
    return False


def validate_template_paths(arguments: dict[str, Any], root_model: type[BaseModel]) -> None:
    """Best-effort static check of *arguments* against *root_model*.

    Covers ``${...}`` interpolations and the ``$eval`` / ``$if`` expressions: syntax, unknown
    names and unknown fields along a field/index/slice path. Other operators are only
    checked when rendered. Also rejects ``$name`` keys that are not json-e operators (json-e
    reserves them; write ``$$name`` for a literal key). Raises ``TemplateError``.
    """
    _check_reserved_keys(arguments)
    known = _declared_names(arguments)
    for source, tree in _collect_expressions(arguments):
        _check_node(tree, source, root_model, known)


def render_arguments(arguments: dict[str, Any], context: BaseModel) -> dict[str, Any]:
    """Return a copy of *arguments* with every template evaluated against *context*.

    Raises ``TemplateResolutionError`` when rendering fails at runtime.
    """
    if not _needs_rendering(arguments):
        return copy.deepcopy(arguments)
    try:
        rendered = jsone.render(arguments, context.model_dump(mode="json"))
    except JSONTemplateError as error:
        raise TemplateResolutionError(str(error)) from error
    if not isinstance(rendered, dict):
        raise TemplateResolutionError("arguments must render to an object")
    return rendered


def _check_reserved_keys(value: Any) -> None:
    if isinstance(value, dict):
        # Keys of an operator object ($then, $else, ...) are that operator's parameters.
        if not any(key in _jsone_operators for key in value):
            for key in value:
                if _IDENTIFIER_KEY.match(key):
                    raise TemplateError(
                        f"key {key!r} is reserved by the template language; use '${key}' "
                        "to write it literally"
                    )
        for item in value.values():
            _check_reserved_keys(item)
    elif isinstance(value, list):
        for item in value:
            _check_reserved_keys(item)


def _collect_expressions(value: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, str):
        found.extend(_parse_interpolations(value))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in _EXPRESSION_OPERATORS:
                if not isinstance(item, str):
                    raise TemplateError(f"{key} must be given a string expression")
                found.append((item, _parse_expression(item)))
            else:
                found.extend(_collect_expressions(key))
                found.extend(_collect_expressions(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_expressions(item))
    return found


def _parse(source: str) -> tuple[Any, Any]:
    """Parse the leading expression of *source*; return its tree and the first unconsumed token."""
    try:
        parser = Parser(source, tokenizer)
        return parser.parse(), parser.current_token
    except StopIteration:
        raise TemplateError("the expression is empty or unterminated") from None
    except JSONTemplateError as error:
        raise TemplateError(str(error.args[0])) from error
    except Exception as error:  # json-e's parser raises AttributeError on truncated input
        raise TemplateError("the expression is malformed") from error


def _parse_expression(source: str) -> Any:
    try:
        tree, token = _parse(source)
    except TemplateError as error:
        raise TemplateError(f"invalid expression {source!r}: {error}") from error
    if tree is None or token is not None:
        raise TemplateError(f"invalid expression {source!r}")
    return tree


def _parse_interpolations(template: str) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    rest = template
    match = _INTERPOLATION_START.search(rest)
    while match:
        rest = rest[match.end() :]
        if match.group() != "$${":
            try:
                tree, token = _parse(rest)
            except TemplateError as error:
                raise TemplateError(f"invalid ${{..}} expression: {error}") from error
            if tree is None or token is None or token.kind != "}":
                raise TemplateError(f"invalid ${{..}} expression near {rest[:40]!r}")
            found.append((rest[: token.start].strip(), tree))
            rest = rest[token.start + 1 :]
        match = _INTERPOLATION_START.search(rest)
    return found


def _declared_names(value: Any) -> set[str]:
    """Names bound inside the template (``$let``, ``each(..)``, ``by(..)``), scoping ignored."""
    names: set[str] = set()
    if isinstance(value, dict):
        bindings = value.get("$let")
        if isinstance(bindings, dict):
            names.update(bindings)
        for key, item in value.items():
            binding = _BINDING_KEY.match(key)
            if binding:
                names.update(name.strip() for name in binding.group(1).split(",") if name.strip())
            names |= _declared_names(item)
    elif isinstance(value, list):
        for item in value:
            names |= _declared_names(item)
    return names


def _check_node(node: Any, source: str, root_model: type[BaseModel], declared: set[str]) -> None:
    if node is None:
        raise TemplateError(f"invalid expression {source!r}: missing operand")
    access = _flatten_access(node)
    if access is not None:
        root, segments, nested = access
        name = root.token.value
        is_local = name in declared or (
            name in _BUILTIN_NAMES and name not in _model_names(root_model)
        )
        if not is_local:
            _check_path(source, [name, *segments], root_model)
        for child in nested:
            _check_node(child, source, root_model, declared)
    elif isinstance(node, BinOp):
        _check_node(node.left, source, root_model, declared)
        _check_node(node.right, source, root_model, declared)
    elif isinstance(node, UnaryOp):
        _check_node(node.expr, source, root_model, declared)
    elif isinstance(node, FunctionCall):
        _check_node(node.name, source, root_model, declared)
        for arg in node.args:
            _check_node(arg, source, root_model, declared)
    elif isinstance(node, _ListNode):
        for item in node.list:
            _check_node(item, source, root_model, declared)
    elif isinstance(node, _ObjectNode):
        for item in node.obj.values():
            _check_node(item, source, root_model, declared)


def _model_names(model: type[BaseModel]) -> set[str]:
    return set(model.model_fields) | set(model.model_computed_fields)


def _flatten_access(node: Any) -> tuple[Any, list[_Segment], list[Any]] | None:
    """Split ``a.b[0][1:].c`` into root ``a`` and segments; None if the chain is not rooted in a name.

    The segment list stops at the first dynamic index (``a[i]``), whose expression is returned
    in the third element so its own names are still checked.
    """
    segments: list[Any] = []
    nested: list[Any] = []
    current = node
    while not isinstance(current, ContextValue):
        if isinstance(current, BinOp) and current.token.kind == ".":
            segments.append(current.right.token.value)
            current = current.left
        elif isinstance(current, ValueAccess):
            if current.isInterval:
                segments.append(None)
                nested.extend(child for child in (current.left, current.right) if child)
            else:
                segments.append(_literal_segment(current.left))
                if segments[-1] is _DYNAMIC:
                    nested.append(current.left)
            current = current.arr
        else:
            return None
    segments.reverse()
    static: list[_Segment] = []
    for segment in segments:
        if segment is _DYNAMIC:
            break
        static.append(segment)
    return current, static, nested


def _literal_segment(index: Any) -> Any:
    if type(index) is ASTNode and index.token.kind == "number" and "." not in index.token.value:
        return int(index.token.value)
    if type(index) is ASTNode and index.token.kind == "string":
        return index.token.value[1:-1]
    if (
        isinstance(index, UnaryOp)
        and index.token.kind == "-"
        and type(index.expr) is ASTNode
        and index.expr.token.kind == "number"
        and "." not in index.expr.token.value
    ):
        return -int(index.expr.token.value)
    return _DYNAMIC


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


def _check_path(source: str, segments: list[_Segment], root_model: type[BaseModel]) -> None:
    current: Any = root_model
    prefix = f"invalid expression {source!r}"
    for segment in segments:
        current = _strip_optional(current)
        if _is_free_form(current):
            return
        if segment is None or isinstance(segment, int):
            if get_origin(current) is not list:
                raise TemplateError(
                    f"{prefix}: cannot index or slice non-list type {_type_name(current)}"
                )
            if segment is not None:
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
