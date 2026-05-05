from enum import Enum


class ToolNames(Enum):
    IMAGE_GENERATION_TOOL = "image_generation_tool"
    WEB_SEARCH_TOOL = "web_search_tool"
    RAG_SEARCH_TOOL = "rag_search_tool"
    PYTHON_CODE_INTERPRETER = "internal_code_execution_python_interpreter"
    CREATE_SHAPE_BOX = "shapes_box_toolset_create_shape_box"
    ADD_SHAPE_TO_BOX = "shapes_box_toolset_add_shape_to_box"
    REMOVE_SHAPES_FROM_BOX = "shapes_box_toolset_remove_shapes_from_box"
    GET_SHAPES_FROM_BOX = "shapes_box_toolset_get_shapes_from_box"
    INVERT_STRING = "mcp-local-toolset_Invert_String"
    LIST_FROM_WORD = "mcp-local-toolset_list_from_word"
