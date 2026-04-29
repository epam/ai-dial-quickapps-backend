import pytest

from quickapp.config.utils import JsonMergePatchError, json_merge_patch


class TestJsonMergePatch:
    """Cases for `json_merge_patch` (RFC 7396 + discriminator-rejection rule)."""

    def test_merge_replaces_scalar(self):
        result = json_merge_patch({"a": 1, "b": 2}, {"a": 99})
        assert result == {"a": 99, "b": 2}

    def test_merge_adds_key(self):
        result = json_merge_patch({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_merge_recursive_objects(self):
        target = {"deployment": {"name": "dial-rag", "params": {"k": 1}}}
        patch = {"deployment": {"params": {"k": 2}}}
        result = json_merge_patch(target, patch)
        assert result == {"deployment": {"name": "dial-rag", "params": {"k": 2}}}

    def test_merge_replaces_array_wholesale(self):
        target = {"required": ["query", "attachment_urls"]}
        patch = {"required": ["query"]}
        result = json_merge_patch(target, patch)
        assert result == {"required": ["query"]}

    def test_null_removes_key(self):
        result = json_merge_patch({"a": 1, "b": 2}, {"b": None})
        assert result == {"a": 1}

    def test_null_on_missing_key_is_noop(self):
        result = json_merge_patch({"a": 1}, {"b": None})
        assert result == {"a": 1}

    def test_empty_patch_returns_target_copy(self):
        target = {"a": 1, "nested": {"b": 2}}
        result = json_merge_patch(target, {})
        assert result == target
        assert result is not target
        assert result["nested"] is not target["nested"]

    def test_non_dict_patch_replaces_target_wholesale(self):
        result = json_merge_patch({"a": 1}, [1, 2, 3])
        assert result == [1, 2, 3]

    def test_dict_patch_against_non_dict_target_creates_new_dict(self):
        result = json_merge_patch(None, {"a": 1})
        assert result == {"a": 1}

    def test_top_level_type_in_patch_rejected(self):
        with pytest.raises(JsonMergePatchError) as excinfo:
            json_merge_patch({"type": "deployment-tool"}, {"type": "rest-api-tool"})
        assert excinfo.value.path == "/type"
        assert "type" in str(excinfo.value)

    def test_nested_type_in_tools_array_rejected(self):
        target = {"tools": [{"type": "deployment-tool", "deployment": {"name": "x"}}]}
        patch = {"tools": [{"type": "rest-api-tool"}]}
        with pytest.raises(JsonMergePatchError) as excinfo:
            json_merge_patch(target, patch)
        assert excinfo.value.path == "/tools/0/type"
        assert "type" in excinfo.value.message

    def test_nested_type_in_arbitrary_object_rejected(self):
        target = {"deployment": {"name": "dial-rag"}}
        patch = {"deployment": {"type": "something"}}
        with pytest.raises(JsonMergePatchError) as excinfo:
            json_merge_patch(target, patch)
        assert excinfo.value.path == "/deployment/type"

    def test_patch_does_not_mutate_target(self):
        target = {"a": {"b": [1, 2]}}
        patch = {"a": {"b": [9]}}
        json_merge_patch(target, patch)
        assert target == {"a": {"b": [1, 2]}}
