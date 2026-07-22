# Code style and module organization

This document describes how the application is structured and how to add or change code in a consistent way. It is aimed at newcomers and contributors.

---

## 1. Dependency Injection (injector)

**All interactions between modules should go through Dependency Injection.** We use the [injector](https://github.com/python-injector/injector) library (with [fastapi-injector](https://github.com/abstractkitchen/fastapi-injector) for FastAPI).

### Rules

- **Do not** import and instantiate another module’s services or config in business code. Request them via constructor parameters and let the injector provide them.
- **Do** define one **module class** per feature (e.g. `AgentModule`, `InternalToolModule`). The module’s `configure(binder)` method declares how types are bound (to which implementation, in which scope).
- **Do** use the `@inject` decorator on classes that receive injected dependencies, and declare dependencies in `__init__`; the injector will resolve them when creating the instance.
- **Do** use `@provider` / `@multiprovider` in the module when the injector needs custom logic to create an instance (e.g. depending on other injected types).

### Where it’s wired

- **`app_factory.py`** builds the root `Injector` with the list of modules (`AppModule`, `AgentModule`, `InternalToolModule`, etc.) and gets the FastAPI app from the injector.
- Each **`*_module.py`** (e.g. `agent_module.py`, `internal_tooling_module.py`) defines a class that extends `injector.Module` and in `configure()` binds interfaces/classes to implementations and scopes (`singleton`, `request_scope`, etc.).

### Example (consumer)

```python
from injector import inject

@inject
class AssistantInvoker:
    def __init__(
        self,
        config: ApplicationConfig,
        agent_settings: AgentSettings,
        ...
    ) -> None:
        self.__agent_settings = agent_settings
```

`AssistantInvoker` does not import or construct `AgentSettings`; the injector passes it in.

### Example (module binding)

```python
# In agent_module.py
class AgentModule(Module):
    def configure(self, binder: Binder) -> None:
        binder.bind(AgentSettings, to=AgentSettings, scope=singleton)
        binder.bind(AssistantInvoker, to=AssistantInvoker, scope=NoScope)
        ...
```

---

## 2. Per-module settings (environment variables)

**If a module depends on environment variables, it must have its own settings class and use it via DI.** Do not read `os.getenv` (or `os.environ`) in business code or in random modules.

### Rules

- **One settings class per (injector) module** that needs config (e.g. `AgentSettings`, `InternalToolingSettings`, `LoggingSettings`). Name it `{ModuleName}Settings` when it belongs to a feature module.
- **Define it in (or next to) that module** (e.g. `core/agent/agent_settings.py`, `internal_tooling/internal_tooling_settings.py`, `config/logging_settings.py`). Settings shared across modules live in `config/` (e.g. `config/agent_settings.py`).
- Use **pydantic-settings** (`BaseSettings`) for the class. Use `Field(..., alias="ENV_VAR_NAME")` so existing env var names (often with different prefixes) are supported.
- **Bind the settings class in that module’s `configure()`** (e.g. `binder.bind(AgentSettings, to=AgentSettings, scope=singleton)`). Consumers receive the same instance via constructor injection.
- **Do not** add `os.getenv` / `os.environ` in application or tooling code. The only place that should read env for app config is inside the settings classes.
- **Document** the purpose and default of each env variable (e.g. in the settings class docstring or the table below).

### Example (settings class)

```python
# config/agent_settings.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict()

    show_usage_statistics: bool = Field(default=False, alias="SHOW_USAGE_STATISTICS")
    default_agent_max_iterations: int = Field(default=15, alias="DEFAULT_AGENT_MAX_ITERATIONS")
```

### Example (module binding and use)

In the module’s `configure()`:

```python
binder.bind(AgentSettings, to=AgentSettings, scope=singleton)
```

In a class that needs these settings:

```python
@inject
def __init__(self, ..., agent_settings: AgentSettings) -> None:
    self.__agent_settings = agent_settings
```

### Shared / cross-cutting settings

- Settings used by more than one module (e.g. presentation, DIAL URL) live in **`common/`** (e.g. `PresentationSettings`, `DialSettings`) so that no circular imports are introduced.
- Logging is special: `LoggingSettings` lives under `config/` and is used to build `LoggingConfig` at startup (e.g. in `app_factory`), not via injector.

---

## 3. Encapsulation and visibility

- **Protected by default**: Use a single leading underscore (`_`) for class attributes and methods that are internal to the class or module.
- **Public only when needed**: Expose public attributes (no underscore) only when they are part of the intended external API.
- This keeps the public surface small and makes refactoring safer.

---

## 4. Types and clarity

- **Type hints**: Use type hints on function and method signatures (parameters and return types) so readers and tools (IDEs, linters) understand expected types.
- **Modern built-in generics**: Prefer built-in generics over `typing` aliases where possible:
  - `list[str]`, `dict[str, int]`, `tuple[str, float]` instead of `List`, `Dict`, `Tuple`.
  - For unions in Python 3.10+, use `str | None` instead of `Optional[str]`.
- **Complex or ambiguous cases**: Add a short docstring to clarify meaning or constraints.
- **Factory methods**: For a `@classmethod` that acts as a factory, use `typing.Self` as the return type.

---

## 5. Naming

- **Functions and methods**: `snake_case`.
- **Classes**: `PascalCase` (e.g. `AgentSettings`, `AssistantInvoker`).
- **Constants**: `UPPER_SNAKE_CASE` (e.g. `DEFAULT_LOG_LEVEL`).
- **Modules**: `snake_case` filenames (e.g. `agent_settings.py`, `app_module.py`).

---

## 6. Code organization and imports

- **Logical separation**: Group related classes and functions into modules. Each module should have a clear purpose or feature.
- **Explicit imports**: Avoid `from module import *`. Import only what you use.
- **Import order**: Standard library → third-party → local/project modules, with a blank line between each group.

---

## 7. Class bodies and global state

- **No conditional or complex logic in class bodies**: Do not put conditionals or non-trivial logic at class level (e.g. `if condition: x = ...`). Use constants, `__init__`, factory functions, or helper functions instead.
- **Avoid mutable global state**: Prefer passing mutable objects as parameters. If global or shared state is necessary, document it and ensure thread-safe access where relevant.

---

## 8. Pydantic: validation and complex arguments

- **Validation**: Use Pydantic models for structured data validation instead of ad-hoc checks. Prefer `MyModel.model_validate(data)` over manual validation of dicts.
- **Complex arguments**: Prefer Pydantic models (or typed structures) for complex function arguments instead of `dict[str, Any]` or nested dicts when the shape is fixed. Using `dict` is fine when keys and values are homogeneous (e.g. a mapping from id to a known type).
- **Mutable defaults in Pydantic**: Do not use mutable default values (e.g. `items: list[str] = []`). Use `Field(default_factory=list)` (or similar) instead.
- **Pydantic over dataclasses**: Use Pydantic `BaseModel` instead of `@dataclass` (including `frozen=True`) for value objects and data containers. Pydantic gives us consistent validation, serialization, and IDE/type integration across the codebase; mixing `dataclasses` with Pydantic fragments those guarantees. For immutability, set `model_config = ConfigDict(frozen=True)`.

---

## 9. Logging and error handling

- **Use the logging module**: Use Python’s `logging` (e.g. `logger.info`, `logger.debug`, `logger.exception`) instead of `print()` for production behavior. Configure log levels appropriately (e.g. via `LoggingSettings` / `QUICKAPP_LOG_LEVEL`).
- **Graceful error handling**: Use exceptions where appropriate. Avoid silent failures; log or re-raise with clear messages so issues are visible and debuggable.

### Level semantics

Pick the level from what the record *means for the service*, not from how it reads while developing (design: [`docs/designs/log_levels_and_content_policy.md`](docs/designs/log_levels_and_content_policy.md)):

| Level | Meaning | Examples |
|---|---|---|
| **DEBUG** | Developer diagnostics: control flow, intermediate values, structure summaries. Verbose, not a narrative. | State-holder summaries, routine rejections/skips, perf reports |
| **INFO** | The operational narrative: startup/config summaries plus the per-request lifecycle skeleton. Metadata-only, low bounded volume per request. | Request received, model call, tool executed, fallback applied, request completed |
| **WARNING** | Something unexpected happened and the service handled it; the request continues, possibly degraded. | Stream recovery applied, unsupported content block tolerated, tool failure handed to a fallback, deprecated config |
| **ERROR** | A failure that affected the request outcome or cost the service functionality; each occurrence is worth investigating. | Unhandled request exception (with `error_reference`), toolset init failure surfaced to the user |

### Single-writer rule for ERROR (and WARNING)

- A failure is logged at **ERROR exactly once**, by the layer that *owns its final handling*. In the request path that owner is `_QuickAppCompletion` (the `error_reference` record).
- A layer that hands a failure onward — to a fallback strategy, a recovery policy, or by (re-)raising for an upstream handler — logs at **WARNING or not at all**, never ERROR. `StagedBaseTool` (the tool choke point) writes the single WARNING for a tool failure; layers beneath it that merely detect and raise (e.g. `_MCPTool`) stay at DEBUG.
- One failure gets **one salient record per severity** — do not re-log the same failure as it propagates up.

### Content rule (metadata over payload)

- Records at **every** level (DEBUG included) carry structure, not content: roles, counts/sizes, durations, tool/skill/deployment/model names, identifiers, statuses/outcomes, error codes and types, MIME types, HTTP status codes, header **names**, and URLs stripped to scheme/host/path (use `common.url_sanitization.sanitize_url_for_log`).
- Never log message bodies, tool-call argument values, tool/LLM response bodies, attachment content, header **values**, or URL query strings/fragments. The rule is an allowlist: when in doubt, a value is content. This includes exception messages our own code raises — keep response bodies off them (e.g. `ToolErrorException.__str__` is structural; the body stays on the `error_message` attribute for the LLM/user channels).
- Payload debugging is gated behind the `LOG_PAYLOADS` switch: emit an unconditional structure summary, then pass the payload through `common.payload_logging.log_payload` (a no-op unless `LOG_PAYLOADS=true`, truncating each field and prefixing the record with the `[payload]` marker). Never log payload content unconditionally.
- Lifecycle-skeleton records use `common.lifecycle_logging.format_event` — a stable prefix plus `key=value` fields — so structured output (#438) and request ids (#439) can enrich them later without rewording.

---

## 10. Linters and formatters

- **Linting**: Use the project’s linter (e.g. mypy, ruff) to catch style and type issues early. Fix or address reported issues before submitting changes.
- **Formatting**: Use the project’s formatter (e.g. ruff format, black) to keep style consistent. Run it before committing (e.g. via a `make format` or equivalent if the project provides it).

---

## 11. Dependencies

- **Declare direct dependencies**: Any package that is directly imported in the codebase must be declared as a dependency (e.g. in `pyproject.toml` or `requirements.txt`). Do not rely on transitive dependencies for direct imports.

---

## 12. Summary checklist

- **DI**: Cross-module use of services or config goes through constructor injection; types are bound in a module’s `configure()`; no direct instantiation of other modules’ types in business code.
- **Env**: Env-based config lives in a pydantic-settings class per module (or shared in `common/`), bound in the injector and injected; no `os.getenv` in application/tooling code.
- **Naming**: Module class `XxxModule`, settings class `XxxSettings`, env names preserved via `Field(alias="ENV_VAR_NAME")`.
- **Visibility**: Prefer protected (`_`) for internals; public only for the intended API.
- **Types**: Use type hints and modern generics; use Pydantic for validation and complex arguments (not `@dataclass`); avoid mutable defaults in Pydantic fields.
- **Structure**: Clear module boundaries, explicit imports, no complex logic in class bodies, logging instead of print, declared dependencies.
