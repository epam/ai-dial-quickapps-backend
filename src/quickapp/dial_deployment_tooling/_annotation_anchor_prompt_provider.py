from quickapp.common.abstract.base_prompt_provider import PromptPartProvider

_ANNOTATION_ANCHOR_RULE = """\
## Citation Anchors

Some tool responses embed citation anchors written as `<cit id="...">` directly after the
claim they support. These are **not** the internal `[id]` citations you are told to strip —
they are part of the answer and must survive into your response.

1. Copy each `<cit id="...">` tag **verbatim**, keeping it directly after the claim it supports.
2. **Never invent** an id, alter an existing one, or renumber them.
3. Drop an anchor only when you drop the claim it supports.
4. Do not mention or explain the anchors to the user.\
"""


class _AnnotationAnchorPromptProvider(PromptPartProvider):
    """Tells the orchestrator to preserve `<cit id="...">` anchors from tool responses.

    Registered only when a deployment tool sets ``propagate_annotations_to_choice``:
    without surviving anchors, every propagated annotation would point at nothing.
    """

    async def get_prompt_part(self) -> str:
        return _ANNOTATION_ANCHOR_RULE
