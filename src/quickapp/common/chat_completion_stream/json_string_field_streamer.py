"""Incrementally extract one JSON string field value from a streamed object."""


class JsonStringFieldStreamer:
    """Feed partial JSON object text; emit decoded characters of one string field.

    Handles chunk boundaries and standard JSON string escapes (``\\"``, ``\\\\``,
    ``\\n``, ``\\r``, ``\\t``, ``\\uXXXX``). Once the field's closing quote is seen,
    further input is ignored (``done`` is True).
    """

    def __init__(self, field_name: str) -> None:
        self._key = f'"{field_name}"'
        self._key_i = 0
        # seek_key -> after_key -> in_value -> done
        self._phase = "seek_key"
        self._escape = False
        self._hex_left = 0
        self._hex_buf = ""
        self.done = False
        self.started = False

    def feed(self, chunk: str) -> str:
        if self.done or not chunk:
            return ""
        out: list[str] = []
        for ch in chunk:
            if self.done:
                break
            emitted = self._consume(ch)
            if emitted is not None:
                out.append(emitted)
        return "".join(out)

    def _consume(self, ch: str) -> str | None:
        if self._phase == "seek_key":
            if ch == self._key[self._key_i]:
                self._key_i += 1
                if self._key_i == len(self._key):
                    self._phase = "after_key"
                    self._key_i = 0
            elif ch == self._key[0]:
                self._key_i = 1
            else:
                self._key_i = 0
            return None

        if self._phase == "after_key":
            if ch.isspace():
                return None
            if ch == ":":
                self._phase = "seek_quote"
                return None
            # Unexpected token — reset and keep looking (nested keys are rare here).
            self._phase = "seek_key"
            if ch == self._key[0]:
                self._key_i = 1
            return None

        if self._phase == "seek_quote":
            if ch.isspace():
                return None
            if ch == '"':
                self._phase = "in_value"
                self.started = True
                return None
            self._phase = "seek_key"
            if ch == self._key[0]:
                self._key_i = 1
            return None

        # in_value
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
            return None

        if self._escape:
            self._escape = False
            if ch == "u":
                self._hex_left = 4
                self._hex_buf = ""
                return None
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
            return None
        if ch == '"':
            self._phase = "done"
            self.done = True
            return None
        return ch
