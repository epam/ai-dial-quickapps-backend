---
paths:
  - "src/tests/unit_tests/**"
---

# Unit Testing

## Location & Structure

`src/tests/unit_tests/` — organized by feature domain, mirroring `src/quickapp/`:

```
unit_tests/
├── common/               # Shared utilities (common.py) + tests for common/ modules
├── agent_tests/           # Orchestrator, tool call accumulation, attachment filtering
├── application_tests/     # Completion handling, request context setup
├── config_tests/          # Pydantic config validation, preview features
├── dial_core_services_tests/  # DIAL API client interactions
├── dial_deployment_tooling_tests/  # Deployment tool execution
├── file_transfer_tests/   # File argument transformation
├── internal_tooling_tests/  # Python interpreter, display content
├── mcp_tool_tests/        # MCP protocol tools, connection management
├── rest_api_tooling_tests/  # REST API tool execution
├── skills_tests/          # Agent skill parsing, XML generation
├── starters_tests/        # Conversation starters
├── timestamp_tooling/     # Timestamp annotation
└── usage_statistics_tests/  # Pricing & usage tracking
```

## Running

```bash
make test                          # all unit tests
make test ARGS="-k test_name -x"   # filtered, stop on first failure
make test_cov                      # with coverage report
```

## Characteristics

- Fast and isolated — no external services, no network, no disk I/O
- No DI container in most tests — dependencies injected directly via constructor with mocks
- No `conftest.py` files — fixtures are defined locally in each test module
- `@pytest.mark.asyncio` required on every async test (no `asyncio_mode = "auto"`)

## Naming Conventions

- **Files**: `test_<module>.py` (e.g., `test_pricing_service.py`)
- **Functions**: `test_<scenario>` in snake_case (e.g., `test_get_price_from_cache`)
- **Classes**: `Test<Feature>` in PascalCase to group related tests (e.g., `class TestParseFrontmatter:`)

## Shared Test Utilities

`src/tests/unit_tests/common/common.py` provides helpers for tests that need DI or HTTP context:

- `create_test_app(modules)` — builds a FastAPI app with `Injector` for tests that need real DI wiring
- `create_request_headers(api_key, starters)` — builds HTTP headers with DIAL app properties
- `create_request_body(message_content)` — builds a completion request body
- `create_app_configuration(toolsets)` — builds `ApplicationConfig` with sensible defaults

Use `create_test_app` only when testing DI integration (e.g., module binding). Most unit tests should
avoid DI entirely and construct the system-under-test directly.

## Mocking Patterns

Dependencies are mocked via constructor injection using `unittest.mock`:

```python
@pytest.fixture
def mock_registry():
    registry = MagicMock(spec=_PricingRegistry)
    registry.get_model_pricing.return_value = None
    return registry

@pytest.fixture
def service(mock_registry):
    return _PricingService(mock_registry, MagicMock())
```

### Mock types

- **`MagicMock(spec=SomeClass)`** — type-safe mocks for sync dependencies
- **`AsyncMock`** — for async methods/coroutines
- **`patch()`** — for module-level symbols when constructor injection isn't feasible (e.g., `@patch("httpx.AsyncClient")`)
- **`SimpleNamespace`** — lightweight stand-ins for data objects with known attributes (used in agent_tests, mcp_tool_tests)
- **Never use `create_autospec`** — the codebase consistently uses `MagicMock(spec=...)` instead

### Test data builders

For complex objects, define module-level helper functions prefixed with `_make_` or `_`:

```python
def _make_model_info(prompt: str | None = "0.01", completion: str | None = "0.02") -> MagicMock:
    pricing = MagicMock()
    pricing.prompt = prompt
    pricing.completion = completion
    model_info = MagicMock()
    model_info.pricing = pricing
    return model_info
```

Common patterns: `_make_accumulated_tool_call()`, `_make_tool_call()`, `_attachment()`, `_make_processor()`.

## Async Tests

```python
@pytest.mark.asyncio
async def test_download_file():
    mock_service = AsyncMock()
    mock_service.download_file.return_value = b"content"
    result = await mock_service.download_file("path")
    mock_service.download_file.assert_awaited_once_with("path")
```

- Always decorate with `@pytest.mark.asyncio` — this is **not** auto-detected
- Use `AsyncMock` for mocking coroutines
- Assert with `.assert_awaited_once()`, `.assert_awaited_once_with()`, `.assert_not_awaited()`

## Pydantic Model Testing

Use `monkeypatch` for environment variables that affect `BaseSettings`:

```python
def test_feature_enabled(self, monkeypatch):
    monkeypatch.setenv("ENABLE_PREVIEW_FEATURES", "true")
    features = Features()
    assert features.timestamp is not None

def test_feature_disabled(self, monkeypatch):
    monkeypatch.delenv("ENABLE_PREVIEW_FEATURES", raising=False)
    features = Features()
    assert features.timestamp is None
```

Test validation errors with `pytest.raises`:
```python
with pytest.raises(ValidationError, match="starters"):
    ConversationStartersConfig(starters=[])
```

## Exception Testing

```python
with pytest.raises(RuntimeError) as excinfo:
    await orchestrator.invoke()
assert "doesn't return any result" in str(excinfo.value)

# Or with match parameter:
with pytest.raises(TypeError, match="PreviewField requires default=None"):
    PreviewField(default="something")
```

## HTTP Testing

- **External HTTP calls**: mock with `@patch("httpx.AsyncClient")` or `pytest-httpx` (`httpx_mock` fixture)
- **FastAPI endpoint testing**: use `starlette.testclient.TestClient` with `create_test_app()`

## Assertion Style

Use plain `assert` statements — no assertion libraries:

```python
assert result.input_token_price == 0.01          # value equality
assert result is cached_value                      # identity
assert len(tools) == 4                             # collection size
mock.method.assert_called_once_with(expected_arg)  # mock verification
```
