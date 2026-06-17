from quickapp.common.utils import fenced_code_block


def test_plain_text_uses_triple_backtick_fence():
    assert fenced_code_block("a\nb") == "```\na\nb\n```"


def test_language_is_appended_to_opening_fence():
    assert fenced_code_block("x", "python") == "```python\nx\n```"


def test_nested_triple_fence_forces_four_backticks():
    content = "intro\n```py\ncode\n```\noutro"
    assert fenced_code_block(content) == f"````\n{content}\n````"


def test_fence_grows_past_longest_backtick_run():
    # Longest run is 4 backticks, so the wrapper must use 5.
    content = "before ```` after"
    assert fenced_code_block(content) == f"`````\n{content}\n`````"


def test_inline_backticks_below_three_keep_triple_fence():
    content = "use `code` and ``more`` here"
    assert fenced_code_block(content) == f"```\n{content}\n```"
