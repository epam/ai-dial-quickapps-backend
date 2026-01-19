import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class AgentInstructionsProvider:
    """
    Loads all `.md` files from `config/predefined/instructions/` once at construction
    and provides the concatenated content via `get`.
    """

    def __init__(self) -> None:
        self._prompt: str = ""
        self._load_instructions()

    def _load_instructions(self) -> None:
        project_root = Path(__file__).parents[3]
        instructions_dir = project_root / "config" / "predefined" / "instructions"

        if not instructions_dir.exists() or not instructions_dir.is_dir():
            logger.debug(f"No instructions directory found at `{instructions_dir}`")
            self._prompt = ""
            return

        md_files: List[Path] = sorted(instructions_dir.glob("*.md"))
        if not md_files:
            logger.debug(f"No `.md` files found in `{instructions_dir}`")
            self._prompt = ""
            return

        parts: List[str] = []
        for md in md_files:
            try:
                parts.append(md.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error(f"Failed to read `{md}`: {exc}")

        # Combine files in sorted order, separated by two newlines
        self._prompt = "\n\n".join(p for p in parts if p)

    def get(self) -> str:
        return self._prompt
