from quickapp.common.media_types import MediaTypes
from quickapp.internal_tooling.py_interpreter_tooling._constants import (
    SUPPORTED_DISPLAY_MEDIA_TYPES,
)
from quickapp.internal_tooling.py_interpreter_tooling.model.args import DataSampleConfig
from quickapp.internal_tooling.py_interpreter_tooling.model.response import CodeExecutionResponse

_SUPPORTED_RESULT_MEDIA_TYPES = frozenset(
    [
        MediaTypes.MARKDOWN,
        MediaTypes.PLAIN_TEXT,
    ]
)


class ContentSanitizer:

    @staticmethod
    def sanitize(
        data: CodeExecutionResponse, data_sample_config: DataSampleConfig | None
    ) -> CodeExecutionResponse:
        """
        Deletes from Py Interpreter response all content that is not supported to avoid LLM overload with unnecessary info
        """
        if data_sample_config:
            ContentSanitizer._sanityze_result(data, data_sample_config)
            ContentSanitizer._sanityze_stdout(data, data_sample_config)

        if data.display:
            ContentSanitizer._sanitize_display(data)

        return data

    @staticmethod
    def _sanityze_result(
        data: CodeExecutionResponse, data_sample_config: DataSampleConfig | None
    ):
        if data.result and isinstance(data.result, dict):
            updated_data = {}
            for media_type, content in data.result.items():
                if media_type in _SUPPORTED_RESULT_MEDIA_TYPES:
                    updated_data[media_type] = ContentSanitizer._to_sample(
                        content, data_sample_config
                    )
            data.result = updated_data

    @staticmethod
    def _sanityze_stdout(data: CodeExecutionResponse, data_sample_config: DataSampleConfig):
        if data.stdout and isinstance(data.stdout, str):
            data.stdout = ContentSanitizer._to_sample(data.stdout, data_sample_config)

    @staticmethod
    def _to_sample(content: str, data_sample_config: DataSampleConfig | None) -> str:
        # Handle Optional fields with explicit defaults to avoid type errors
        if data_sample_config is None:
            data_sample_config = DataSampleConfig()

        if not data_sample_config.sample_data:
            return content

        total_content_length = len(content)
        total_pages = (
            total_content_length + data_sample_config.page_size - 1
        ) // data_sample_config.page_size

        page = max(0, min(data_sample_config.page, total_pages - 1)) if total_pages > 0 else 0

        start_index = page * data_sample_config.page_size
        end_index = min(start_index + data_sample_config.page_size, total_content_length)

        sample = content[start_index:end_index]

        if total_pages > 1:
            pagination_info = f"\n[Page {page + 1} of {total_pages}]"
            if page < total_pages - 1:
                pagination_info += f" Use page={page + 1} to see more."
            sample += pagination_info

        return sample

    @staticmethod
    def _sanitize_display(data: CodeExecutionResponse):
        updated_display_content = {}
        for content_dicts in data.display:
            for media_type, content in content_dicts.items():
                if (
                    media_type in _SUPPORTED_RESULT_MEDIA_TYPES
                    or media_type in SUPPORTED_DISPLAY_MEDIA_TYPES
                ):
                    updated_display_content[media_type] = content
        data.display = []
        if updated_display_content:
            data.display.append(updated_display_content)
