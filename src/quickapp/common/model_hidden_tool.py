from typing import Annotated

from quickapp.common import StagedBaseTool

# Tag-annotated alias: ``list[ModelHiddenTool]`` is an injector key distinct from
# ``list[StagedBaseTool]``, so code that reads the model's tools cannot see these.
ModelHiddenTool = Annotated[StagedBaseTool, "ModelHiddenTool"]
