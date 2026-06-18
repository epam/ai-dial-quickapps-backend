from quickapp.core.agent._tool_choice_holder import _ToolChoiceHolder


class TestToolChoiceHolder:
    def test_consume_returns_value_on_first_call(self):
        holder = _ToolChoiceHolder(tool_choice="required")
        assert holder.consume() == "required"

    def test_consume_returns_none_on_subsequent_calls(self):
        holder = _ToolChoiceHolder(tool_choice="required")
        holder.consume()
        assert holder.consume() is None
        assert holder.consume() is None

    def test_consume_with_none_input_returns_none_always(self):
        holder = _ToolChoiceHolder(tool_choice=None)
        assert holder.consume() is None
        assert holder.consume() is None
