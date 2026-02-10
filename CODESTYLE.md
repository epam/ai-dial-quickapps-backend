# Code style and module organization

This document describes how the application is structured and how to add or change code in a consistent way. It is aimed at newcomers and contributors.

## 1. Dependency Injection (injector)

**All interactions between modules should go through Dependency Injection.** We use the [injector](https://github.com/python-injector/injector) library.

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
- **Define it in (or next to) that module** (e.g. `agent/agent_settings.py`, `internal_tooling/internal_tooling_settings.py`, `config/logging_settings.py`).
- Use **pydantic-settings** (`BaseSettings`) for the class. Use `Field(..., alias="ENV_VAR_NAME")` so existing env var names (often with different prefixes) are supported.
- **Bind the settings class in that module’s `configure()`** (e.g. `binder.bind(AgentSettings, to=AgentSettings, scope=singleton)`). Consumers receive the same instance via constructor injection.
- **Do not** add `os.getenv` / `os.environ` in application or tooling code. The only place that should read env for app config is inside the settings classes (or a dedicated loader like `LoggingSettings.from_env()` when you need guaranteed env reads).

### Where settings live

| Area              | Settings class           | Typical env vars (examples)        |
|-------------------|--------------------------|------------------------------------|
| Agent             | `AgentSettings`          | `SHOW_USAGE_STATISTICS`, `CHAT_MESSAGE_LOG_LEN`, `DEFAULT_AGENT_MAX_ITERATIONS` |
| Application / UI  | `PresentationSettings`   | `SHOW_USAGE_STATISTICS`, `SHOW_EXECUTION_TIME_STAGE` |
| Internal tooling  | `InternalToolingSettings` | `CONTENT_DOWNLOADER_FILE_SIZE_LIMIT` |
| Logging           | `LoggingSettings`        | `LOG_LEVEL`, `QUICKAPP_LOG_LEVEL`, `LOG_FORMAT`, … |
| DIAL / runtime    | `DialSettings`           | `dial_*` prefix                    |

### Example (settings class)

```python
# agent/agent_settings.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_extra=True)

    show_usage_statistics: bool = Field(default=False, alias="SHOW_USAGE_STATISTICS")
    chat_message_log_length: Optional[int] = Field(default=None, alias="CHAT_MESSAGE_LOG_LEN")
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
    # use agent_settings.quickapp_log_level, etc.
```

### Shared / cross-cutting settings

- Settings used by more than one module (e.g. presentation, DIAL URL) live in **`common/`** (e.g. `PresentationSettings`, `DialSettings`) so that no circular imports are introduced (no module imports another feature module just for settings).
- Logging is special: `LoggingSettings` lives under `config/` and is used to build `LoggingConfig` at startup (e.g. in `app_factory`), not via injector.

---

## 3. Summary checklist

- **DI:** New services or config used across modules are requested in constructors and bound in a module’s `configure()`; no direct instantiation of other modules’ types in business code.
- **Env:** Any dependency on env vars is encapsulated in a pydantic-settings class owned by (or shared for) that module, bound in the injector and injected; no `os.getenv` in application/tooling code.
- **Naming:** Module class `XxxModule`, settings class `XxxSettings` (or a shared name like `PresentationSettings`), env names preserved via `Field(alias="ENV_VAR_NAME")`.
