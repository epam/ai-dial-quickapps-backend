import json
import logging
import warnings
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from injector import inject
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_project_root_path = Path(__file__).parents[3]
_DOCKER_BUILTIN_PATH = Path("/app/predefined")
_DEV_BUILTIN_PATH = _project_root_path / "config" / "predefined"


class ContentType(StrEnum):
    PROMPT = "prompt"
    TOOL = "tool"
    TOOLSET = "toolset"
    SKILL = "skills"

    @property
    def file_glob(self) -> str:
        return "*.md" if self.is_text else "*.json"

    @property
    def is_text(self) -> bool:
        return self in (ContentType.PROMPT, ContentType.SKILL)


class PredefinedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="predefined_")
    base_path: str | None = Field(
        default=None,
        description="Deprecated. Use extra_paths instead. "
        "Base path where predefined templates are stored.",
    )
    extra_paths: str | None = Field(
        default=None,
        description="Colon-separated list of directories layered on top of the built-in "
        "predefined content. Later entries override earlier ones.",
    )


@dataclass(frozen=True)
class LayerInfo:
    path: Path
    content_counts: dict[ContentType, int] = field(default_factory=dict)
    overrides: dict[ContentType, list[str]] = field(default_factory=dict)


@inject
class PredefinedContentProvider:
    """Singleton service owning all predefined content scanning, merging, caching, and retrieval.

    On construction, resolves the ordered list of layer directories (built-in first,
    then extra paths left to right), scans each layer, reads all files eagerly,
    and merges by content type and filename stem (last wins).
    """

    def __init__(self, settings: PredefinedSettings) -> None:
        self._text_store: dict[ContentType, dict[str, str]] = {ct: {} for ct in ContentType}
        self._json_store: dict[ContentType, dict[str, Any]] = {ct: {} for ct in ContentType}
        self._layers_info: list[LayerInfo] = []

        layers = self._resolve_layers(settings)
        self._load_all(layers)
        self._log_summary(layers)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_names(self, content_type: ContentType) -> list[str]:
        """Return sorted list of available names for the given content type."""
        store = self._text_store if content_type.is_text else self._json_store
        return sorted(store[content_type].keys())

    def read_text(self, content_type: ContentType, name: str) -> str:
        """Read a text content item (PROMPT or SKILL). Raises TypeError / KeyError."""
        if not content_type.is_text:
            raise TypeError(
                f"read_text() is not supported for {content_type.value} "
                f"(use read_json() instead)"
            )
        try:
            return self._text_store[content_type][name]
        except KeyError:
            raise KeyError(f"{content_type.value} '{name}' not found in predefined content")

    def read_json(self, content_type: ContentType, name: str) -> dict[str, Any]:
        """Read a JSON content item (TOOL or TOOLSET). Raises TypeError / KeyError."""
        if content_type.is_text:
            raise TypeError(
                f"read_json() is not supported for {content_type.value} "
                f"(use read_text() instead)"
            )
        try:
            return self._json_store[content_type][name]
        except KeyError:
            raise KeyError(f"{content_type.value} '{name}' not found in predefined content")

    def get_layers_info(self) -> list[LayerInfo]:
        """Return diagnostic info about all resolved layers."""
        return list(self._layers_info)

    # ------------------------------------------------------------------
    # Layer resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_layers(settings: PredefinedSettings) -> list[Path]:
        """Resolve the ordered list of layer directories."""
        layers: list[Path] = []

        # 1. Built-in layer (always present)
        if _DOCKER_BUILTIN_PATH.is_dir():
            layers.append(_DOCKER_BUILTIN_PATH)
        elif _DEV_BUILTIN_PATH.is_dir():
            layers.append(_DEV_BUILTIN_PATH)
        else:
            raise RuntimeError(
                f"Built-in predefined content directory not found. "
                f"Checked {_DOCKER_BUILTIN_PATH} and {_DEV_BUILTIN_PATH}. "
                f"The application cannot start without built-in predefined content."
            )

        # 2. Extra layers
        if settings.extra_paths is not None and settings.base_path is not None:
            logger.warning(
                "Both PREDEFINED_EXTRA_PATHS and PREDEFINED_BASE_PATH are set. "
                "PREDEFINED_BASE_PATH is ignored."
            )

        extra_raw: str | None = None
        if settings.extra_paths is not None:
            extra_raw = settings.extra_paths
        elif settings.base_path is not None:
            warnings.warn(
                "PREDEFINED_BASE_PATH is deprecated. Use PREDEFINED_EXTRA_PATHS instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            extra_raw = settings.base_path

        if extra_raw:
            for raw_path in extra_raw.split(":"):
                raw_path = raw_path.strip()
                if not raw_path:
                    continue
                p = Path(raw_path)
                if not p.is_dir():
                    raise RuntimeError(f"Extra predefined content path is not a directory: {p}")
                layers.append(p)

        return layers

    # ------------------------------------------------------------------
    # Eager loading
    # ------------------------------------------------------------------

    def _load_all(self, layers: list[Path]) -> None:
        """Eagerly scan all layers and read all files into memory."""
        # Track names seen so far for override detection
        seen: dict[ContentType, set[str]] = {ct: set() for ct in ContentType}

        for layer_path in layers:
            counts: dict[ContentType, int] = {}
            overrides: dict[ContentType, list[str]] = {}

            for ct in ContentType:
                sub_dir = layer_path / ct.value
                if not sub_dir.is_dir():
                    continue

                layer_overrides: list[str] = []
                count = 0
                for file_path in sorted(sub_dir.glob(ct.file_glob)):
                    name = file_path.stem
                    count += 1

                    if name in seen[ct]:
                        layer_overrides.append(name)

                    self._read_file(ct, file_path, layer_path)
                    seen[ct].add(name)

                if count:
                    counts[ct] = count
                if layer_overrides:
                    overrides[ct] = layer_overrides

            self._layers_info.append(
                LayerInfo(path=layer_path, content_counts=counts, overrides=overrides)
            )

    def _read_file(self, ct: ContentType, file_path: Path, layer_path: Path) -> None:
        """Read a single file into the appropriate store."""
        try:
            if ct.is_text:
                self._text_store[ct][file_path.stem] = file_path.read_text(encoding="utf-8")
            else:
                with file_path.open("r", encoding="utf-8") as f:
                    self._json_store[ct][file_path.stem] = json.load(f)
        except Exception as e:
            raise RuntimeError(
                f"Failed to read {ct.value} file {file_path} in layer {layer_path}: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_summary(self, layers: list[Path]) -> None:
        """Log startup summary of layers and merged totals."""
        logger.info("Predefined content layers: %s", [str(p) for p in layers])

        for info in self._layers_info:
            parts: list[str] = []
            for ct in ContentType:
                count = info.content_counts.get(ct, 0)
                if count:
                    override_names = info.overrides.get(ct, [])
                    if override_names:
                        parts.append(
                            f"{count} {ct.value}(s) (override: {', '.join(override_names)})"
                        )
                    else:
                        parts.append(f"{count} {ct.value}(s)")
            if parts:
                logger.info("Layer %s: %s", info.path, ", ".join(parts))

        # Merged totals
        totals: list[str] = []
        for ct in ContentType:
            store = self._text_store if ct.is_text else self._json_store
            n = len(store[ct])
            if n:
                totals.append(f"{n} {ct.value}(s)")
        logger.info("Merged predefined content: %s", ", ".join(totals))
