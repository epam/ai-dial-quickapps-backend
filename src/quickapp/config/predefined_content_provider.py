import json
import logging
import warnings
from enum import StrEnum
from pathlib import Path
from typing import Any

from injector import inject
from pydantic import BaseModel, ConfigDict, Field
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
    extra_paths: list[str] | None = Field(
        default=None,
        description="JSON list of directories layered on top of the built-in "
        "predefined content. Later entries override earlier ones.",
    )


class LayerInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    content_counts: dict[ContentType, int] = Field(default_factory=dict)
    overrides: dict[ContentType, list[str]] = Field(default_factory=dict)


@inject
class PredefinedContentProvider:
    """Singleton service owning all predefined content scanning, merging, caching, and retrieval.

    On construction, resolves the ordered list of layer directories (built-in first,
    then extra paths left to right), scans each layer, reads all files eagerly,
    and merges by content type and filename stem (last wins).
    """

    def __init__(self, settings: PredefinedSettings) -> None:
        self.__text_store: dict[ContentType, dict[str, str]] = {ct: {} for ct in ContentType}
        self.__json_store: dict[ContentType, dict[str, Any]] = {ct: {} for ct in ContentType}
        self.__layers_info: list[LayerInfo] = []
        self.__default_configuration: dict[str, Any] = {}

        layers = self.__resolve_layers(settings)
        self.__load_all(layers)
        self.__log_summary(layers)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_names(self, content_type: ContentType) -> list[str]:
        """Return sorted list of available names for the given content type."""
        store = self.__text_store if content_type.is_text else self.__json_store
        return sorted(store[content_type].keys())

    def read_text(self, content_type: ContentType, name: str) -> str:
        """Read a text content item (PROMPT or SKILL). Raises TypeError / KeyError."""
        if not content_type.is_text:
            raise TypeError(
                f"read_text() is not supported for {content_type.value} "
                f"(use read_json() instead)"
            )
        try:
            return self.__text_store[content_type][name]
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
            return self.__json_store[content_type][name]
        except KeyError:
            raise KeyError(f"{content_type.value} '{name}' not found in predefined content")

    def get_layers_info(self) -> list[LayerInfo]:
        """Return diagnostic info about all resolved layers."""
        return list(self.__layers_info)

    def get_default_configuration(self) -> dict[str, Any]:
        return dict(self.__default_configuration)

    # ------------------------------------------------------------------
    # Layer resolution
    # ------------------------------------------------------------------

    @staticmethod
    def __resolve_layers(settings: PredefinedSettings) -> list[Path]:
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

        if settings.extra_paths is not None:
            extra_list = settings.extra_paths
        elif settings.base_path is not None:
            warnings.warn(
                "PREDEFINED_BASE_PATH is deprecated. Use PREDEFINED_EXTRA_PATHS instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            extra_list = [settings.base_path]
        else:
            extra_list = None

        if extra_list:
            for raw_path in extra_list:
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

    def __load_all(self, layers: list[Path]) -> None:
        """Eagerly scan all layers and read all files into memory."""
        seen: dict[ContentType, set[str]] = {ct: set() for ct in ContentType}

        for layer_path in layers:
            counts: dict[ContentType, int] = {}
            overrides: dict[ContentType, list[str]] = {}

            for ct in ContentType:
                entries = self.__scan_entries(layer_path / ct.value, ct)
                if not entries:
                    continue

                layer_overrides: list[str] = []
                for name, file_path in entries:
                    if name in seen[ct]:
                        layer_overrides.append(name)
                    self.__read_file(ct, file_path, layer_path, name_override=name)
                    seen[ct].add(name)

                counts[ct] = len(entries)
                if layer_overrides:
                    overrides[ct] = layer_overrides

            self.__merge_default_configuration_from_layer(layer_path)

            self.__layers_info.append(
                LayerInfo(path=layer_path, content_counts=counts, overrides=overrides)
            )

    def __merge_default_configuration_from_layer(self, layer_path: Path) -> None:
        """Load optional ``default_configuration.json`` at the layer root; shallow-merge into
        ``__default_configuration``. Malformed files are logged and skipped (no startup failure).
        """
        path = layer_path / "default_configuration.json"
        if not path.is_file():
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(
                "Failed to read default_configuration.json in layer %s: %s. "
                "Treating this file as empty.",
                layer_path,
                e,
            )
            return
        if not isinstance(data, dict):
            logger.error(
                "default_configuration.json in layer %s must be a JSON object, got %s. "
                "Treating this file as empty.",
                layer_path,
                type(data).__name__,
            )
            return
        self.__default_configuration.update(data)

    @staticmethod
    def __scan_entries(sub_dir: Path, ct: ContentType) -> list[tuple[str, Path]]:
        """Return (name, file_path) pairs for all valid entries in a content-type directory."""
        if not sub_dir.is_dir():
            return []

        if ct == ContentType.SKILL:
            entries: list[tuple[str, Path]] = []
            for skill_dir in sorted(sub_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                skill_file = skill_dir / "SKILL.md"
                if skill_file.is_file():
                    entries.append((skill_dir.name, skill_file))
            return entries

        return [(f.stem, f) for f in sorted(sub_dir.glob(ct.file_glob))]

    def __read_file(
        self,
        ct: ContentType,
        file_path: Path,
        layer_path: Path,
        name_override: str | None = None,
    ) -> None:
        """Read a single file into the appropriate store."""
        name = name_override or file_path.stem
        try:
            if ct.is_text:
                self.__text_store[ct][name] = file_path.read_text(encoding="utf-8")
            else:
                with file_path.open("r", encoding="utf-8") as f:
                    self.__json_store[ct][name] = json.load(f)
        except Exception as e:
            raise RuntimeError(
                f"Failed to read {ct.value} file {file_path} in layer {layer_path}: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def __log_summary(self, layers: list[Path]) -> None:
        """Log startup summary of layers and merged totals."""
        logger.info("Predefined content layers: %s", [str(p) for p in layers])

        for info in self.__layers_info:
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
            store = self.__text_store if ct.is_text else self.__json_store
            n = len(store[ct])
            if n:
                totals.append(f"{n} {ct.value}(s)")
        logger.info("Merged predefined content: %s", ", ".join(totals))
