"""Incrementally walk top-level keys of a streamed JSON object (tool-call arguments)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


@dataclass(frozen=True)
class KeyReady:
    key: str


@dataclass(frozen=True)
class StringChars:
    key: str
    text: str


@dataclass(frozen=True)
class ValueComplete:
    key: str
    value: Any


@dataclass(frozen=True)
class ObjectDone:
    pass


ArgumentStreamEvent = KeyReady | StringChars | ValueComplete | ObjectDone


class _StringDecode(Enum):
    DONE = auto()
    PENDING = auto()


class JsonObjectArgumentStreamer:
    """Feed partial JSON object text; emit events for top-level key/values.

    String values emit ``StringChars`` as decoded characters arrive, then
    ``ValueComplete`` with the full string. Nested objects/arrays and scalars
    emit only ``ValueComplete`` once the value is fully buffered and parsed.
    """

    __slots__ = (
        "_phase",
        "_key_buf",
        "_escape",
        "_hex_left",
        "_hex_buf",
        "_current_key",
        "_string_parts",
        "_raw_buf",
        "_nest_depth",
        "_nest_stack",
        "_in_nest_string",
        "_nest_escape",
        "done",
    )

    def __init__(self) -> None:
        # seek_object → between_keys → in_key → after_key → seek_value
        # → in_string → in_raw → done
        self._phase = "seek_object"
        self._key_buf = ""
        self._escape = False
        self._hex_left = 0
        self._hex_buf = ""
        self._current_key = ""
        self._string_parts: list[str] = []
        self._raw_buf = ""
        self._nest_depth = 0
        self._nest_stack: list[str] = []
        self._in_nest_string = False
        self._nest_escape = False
        self.done = False

    def feed(self, chunk: str) -> list[ArgumentStreamEvent]:
        if self.done or not chunk:
            return []
        events: list[ArgumentStreamEvent] = []
        for ch in chunk:
            if self.done:
                break
            events.extend(self._consume(ch))
        return events

    def _consume(self, ch: str) -> list[ArgumentStreamEvent]:
        phase = self._phase
        if phase == "seek_object":
            if ch.isspace():
                return []
            if ch == "{":
                self._phase = "between_keys"
                return []
            # Not an object — give up quietly.
            self._phase = "done"
            self.done = True
            return []

        if phase == "between_keys":
            if ch.isspace() or ch == ",":
                return []
            if ch == "}":
                self._phase = "done"
                self.done = True
                return [ObjectDone()]
            if ch == '"':
                self._phase = "in_key"
                self._key_buf = ""
                self._escape = False
                self._hex_left = 0
                self._hex_buf = ""
                return []
            return []

        if phase == "in_key":
            decoded = self._consume_string_char(ch)
            if decoded is _StringDecode.DONE:
                self._current_key = self._key_buf
                self._phase = "after_key"
                return [KeyReady(self._current_key)]
            if decoded is not _StringDecode.PENDING:
                self._key_buf += decoded
            return []

        if phase == "after_key":
            if ch.isspace():
                return []
            if ch == ":":
                self._phase = "seek_value"
                return []
            return []

        if phase == "seek_value":
            if ch.isspace():
                return []
            if ch == '"':
                self._phase = "in_string"
                self._string_parts = []
                self._escape = False
                self._hex_left = 0
                self._hex_buf = ""
                return []
            if ch in "{[":
                self._phase = "in_raw"
                self._raw_buf = ch
                self._nest_depth = 1
                self._nest_stack = [ch]
                self._in_nest_string = False
                self._nest_escape = False
                return []
            # number / true / false / null
            self._phase = "in_raw"
            self._raw_buf = ch
            self._nest_depth = 0
            self._nest_stack = []
            self._in_nest_string = False
            self._nest_escape = False
            return []

        if phase == "in_string":
            return self._consume_top_string_char(ch)

        if phase == "in_raw":
            return self._consume_raw_char(ch)

        return []

    def _consume_top_string_char(self, ch: str) -> list[ArgumentStreamEvent]:
        decoded = self._consume_string_char(ch)
        if decoded is _StringDecode.DONE:
            value = "".join(self._string_parts)
            key = self._current_key
            self._phase = "between_keys"
            self._string_parts = []
            return [ValueComplete(key, value)]
        if decoded is not _StringDecode.PENDING:
            self._string_parts.append(decoded)
            return [StringChars(self._current_key, decoded)]
        return []

    def _consume_raw_char(self, ch: str) -> list[ArgumentStreamEvent]:
        if self._nest_depth > 0:
            self._raw_buf += ch
            if self._in_nest_string:
                if self._nest_escape:
                    self._nest_escape = False
                elif ch == "\\":
                    self._nest_escape = True
                elif ch == '"':
                    self._in_nest_string = False
                return []
            if ch == '"':
                self._in_nest_string = True
                return []
            if ch in "{[":
                self._nest_depth += 1
                self._nest_stack.append(ch)
                return []
            if ch in "}]":
                self._nest_depth -= 1
                if self._nest_stack:
                    self._nest_stack.pop()
                if self._nest_depth == 0:
                    return self._finish_raw_value()
                return []
            return []

        # Scalar (number/bool/null): end at delimiter
        if ch.isspace() or ch in ",}":
            events = self._finish_raw_value()
            # Re-process delimiter in between_keys
            self._phase = "between_keys"
            more = self._consume(ch)
            return events + more
        self._raw_buf += ch
        return []

    def _finish_raw_value(self) -> list[ArgumentStreamEvent]:
        raw = self._raw_buf
        self._raw_buf = ""
        key = self._current_key
        self._phase = "between_keys"
        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        return [ValueComplete(key, value)]

    def _consume_string_char(self, ch: str) -> str | _StringDecode:
        """Decode one char inside a JSON string."""
        if self._hex_left:
            self._hex_buf += ch
            self._hex_left -= 1
            if self._hex_left == 0:
                try:
                    return chr(int(self._hex_buf, 16))
                except ValueError:
                    return ""
                finally:
                    self._hex_buf = ""
            return _StringDecode.PENDING

        if self._escape:
            self._escape = False
            if ch == "u":
                self._hex_left = 4
                self._hex_buf = ""
                return _StringDecode.PENDING
            return {
                '"': '"',
                "\\": "\\",
                "/": "/",
                "b": "\b",
                "f": "\f",
                "n": "\n",
                "r": "\r",
                "t": "\t",
            }.get(ch, ch)

        if ch == "\\":
            self._escape = True
            return _StringDecode.PENDING
        if ch == '"':
            return _StringDecode.DONE
        return ch
