# Design: Preview Feature Gating

- **Status:** Implemented
- **Dependencies:**
  - None

## Problem Statement

As new features are added to QuickApps (e.g. time awareness), some need to be shipped in
a "preview" state — available for early testing but not yet considered stable. Today there is no
mechanism to:

1. **Mark a config field as preview** — app creators can configure any field that appears in
   the schema, with no indication that a feature is experimental.
2. **Gate preview features at deployment level** — there is no way for an operator to disable
   all preview features across a deployment without modifying individual app configs.
3. **Hide preview fields from the schema** — preview features appear in the JSON schema
   alongside stable features, making them indistinguishable in the configuration UI.
4. **Gate an entire module as preview** — some features span an entire DI module (tools,
   transformers, prompt providers, etc.). There is no way to conditionally wire a whole module
   based on preview status — today the module is either always registered or manually
   if-guarded in `AppFactory`.

Without gating, preview features either ship as stable (risky) or are manually guarded with
ad-hoc checks scattered across modules (inconsistent, hard to maintain).

## Design Goals

- A reusable annotation (`PreviewField`) that can mark any config field as preview, anywhere in
  the model hierarchy, with no separate registry.
- A single environment variable (`ENABLE_PREVIEW_FEATURES`) that gates all preview features
  deployment-wide.
- When preview is disabled: preview fields are stripped from the JSON schema (the platform
  rejects configs that reference them). A runtime validator nullifies any preview fields that
  slip through (e.g., config persisted before preview was disabled) and logs a warning.
- Zero overhead for stable features — the mechanism only activates for fields explicitly marked
  with `PreviewField`.
- A `@preview_module` decorator that marks an entire DI module as preview, allowing
  `AppFactory` to conditionally wire it based on the preview flag — no ad-hoc `if` guards,
  no inheritance changes.

---

## Use Cases

### UC-1: Operator disables preview features for production

- **Trigger:** Operator deploys QuickApps without setting `ENABLE_PREVIEW_FEATURES`.
- **Behavior:** Preview fields do not appear in the JSON schema. The platform rejects configs
  that reference them. If a preview field slips through anyway (e.g., config persisted before
  preview was disabled), the runtime validator nullifies it and logs a warning. Preview modules
  are not wired — their tools, transformers, and providers are entirely absent at runtime.
- **Outcome:** No preview features are active. The primary enforcement is schema-level — the
  platform prevents misconfiguration before the app ever sees the request. Module-level
  features are enforced at startup — the DI container never registers their bindings.

### UC-2: Operator enables preview features for staging

- **Trigger:** Operator sets `ENABLE_PREVIEW_FEATURES=true` in the staging environment.
- **Behavior:** Preview fields appear in the JSON schema and configuration UI. App creators can
  configure them normally. Runtime validation accepts them. Preview modules are wired into the
  DI container and function normally.
- **Outcome:** All preview features — both field-level and module-level — are fully functional
  in this environment.

### UC-3: Developer marks a new feature as preview

- **Trigger:** Developer adds a new feature config field and uses `PreviewField(...)` instead
  of `Field(...)`.
- **Behavior:** The field is automatically gated by the preview mechanism — no additional
  wiring needed.
- **Outcome:** The feature is hidden in production, visible in staging (when preview is
  enabled), with no changes to the gating infrastructure.

### UC-4: Feature graduates from preview to stable

- **Trigger:** A preview feature is deemed stable and ready for general availability.
- **Behavior:** Developer changes `PreviewField(...)` to `Field(...)` on the config field.
- **Outcome:** The feature is no longer gated. It appears in the schema and is accepted at
  runtime regardless of the `ENABLE_PREVIEW_FEATURES` setting.

### UC-5: Developer marks an entire module as preview

- **Trigger:** Developer builds a new feature that spans a full DI module (e.g. a new tooling
  integration with its own tools, transformers, and providers).
- **Behavior:** The developer decorates the module class with `@preview_module`. `AppFactory`
  filters it out when `ENABLE_PREVIEW_FEATURES` is not set — none of its bindings (tools,
  transformers, prompt providers) are registered.
- **Outcome:** The entire feature is absent at runtime in production. In staging (with preview
  enabled), the module is wired normally and fully functional. No per-binding `if` guards
  needed.

### UC-6: Preview module graduates to stable

- **Trigger:** A preview module is deemed stable and ready for general availability.
- **Behavior:** Developer removes the `@preview_module` decorator from the module class.
- **Outcome:** The module is always wired regardless of `ENABLE_PREVIEW_FEATURES`.

---

## Proposed Design

### 1. `PreviewField` annotation

- **What:** A `Field` wrapper function (in `common/base_config.py`, alongside the existing
  `DialConfigField` / `DialFileConfigField` helpers) that tags field metadata with an
  `x-preview` marker.
- **Owner:** `common/base_config.py`.
- **Semantics:** Sets `json_schema_extra[_PREVIEW_MARKER] = True` on the field. This marker
  is read by both schema generation and runtime validation. Any config field anywhere in the
  model hierarchy can use `PreviewField(...)` instead of `Field(...)` — no registry, no
  base class changes.
- **Change:** New function and constant in `base_config.py`.

```python
_PREVIEW_MARKER = "x-preview"


def PreviewField(default=None, **kwargs) -> FieldInfo:
    json_schema_extra = kwargs.get("json_schema_extra", {})
    if isinstance(json_schema_extra, dict):
        json_schema_extra[_PREVIEW_MARKER] = True
    else:
        original_extra = json_schema_extra

        def new_extra(schema):
            if callable(original_extra):
                original_extra(schema)
            schema[_PREVIEW_MARKER] = True

        json_schema_extra = new_extra
    kwargs["json_schema_extra"] = json_schema_extra
    return Field(default, **kwargs)
```

This follows the same callable-wrapping pattern as `_dial_config_field` in `base_config.py`.

**Constraint:** `PreviewField` must always be used with `default=None` and the type annotation
must be `T | None`. The runtime validator nullifies preview fields by setting them to `None` —
a non-nullable type would violate its own constraint after nullification. `PreviewField`
enforces this by requiring `default=None` (raised as a `TypeError` if a non-`None` default is
provided).

### 2. `FeatureSettings`

- **What:** A `BaseSettings` class that reads the `ENABLE_PREVIEW_FEATURES` env variable.
- **Owner:** `common/feature_settings.py`.
- **Semantics:** Follows the existing `AgentSettings` / `PresentationSettings` pattern.
  Defaults to `False`. Instantiated directly (not via DI) where needed — both
  `model_json_schema()` (a classmethod) and the runtime validator need it, and neither has
  access to the injector.
- **Change:** New settings class.

```python
class FeatureSettings(BaseSettings):
    enable_preview_features: bool = Field(
        default=False, alias="ENABLE_PREVIEW_FEATURES"
    )
```

This is consistent with how `LoggingSettings` works — instantiated at call time, reading
directly from the environment. The DI exception is acknowledged: `model_json_schema()` is a
classmethod and cannot receive settings via injection.

### 3. Schema stripping

- **What:** A `strip_preview_fields(schema)` utility that recursively removes properties
  marked with `x-preview` from a JSON schema dict.
- **Owner:** `common/base_config.py`.
- **Semantics:** Walks `properties` at each level of the schema (including `$defs`). For each
  property with `x-preview: true`, removes it from `properties` and from `required` (if
  present). After removal, prunes any `$defs` entries that are no longer referenced anywhere
  in the **remaining** schema (using the existing `_collect_defs_references` helper, which
  scans the full schema post-removal — shared definitions used by stable fields are preserved). Applied in
  `BaseApplicationTypeConfig.model_json_schema()` when `ENABLE_PREVIEW_FEATURES` is not set.
- **Change:** New utility function; modification to `model_json_schema()`.

`model_json_schema()` **always** applies stripping based on `ENABLE_PREVIEW_FEATURES` — it
does not distinguish callers. The behavior is controlled entirely by the env variable:

- **`dump_app_schema` and CI** run with `ENABLE_PREVIEW_FEATURES=true` (set in the Makefile
  for the `dump_app_schema` and `lint` targets). This produces and checks the **full** schema
  with all preview fields included. The committed schema is always the full version.
- **Configuration support API** in production runs **without** the env var, so preview fields
  are stripped at runtime. Users cannot see or configure preview features.

This keeps CI deterministic and eliminates the need for `model_json_schema()` to know its
call context.

### 4. Runtime validation

- **What:** A `model_validator` on `ApplicationConfig` that nullifies preview fields when
  `ENABLE_PREVIEW_FEATURES` is not set.
- **Owner:** `config/application.py`.
- **Semantics:** The validator recursively walks the config model tree. Algorithm:

  ```
  def gate_preview_fields(model):
      for field_name, field_info in model.model_fields.items():
          value = getattr(model, field_name)
          if has_preview_marker(field_info) and value is not None:
              setattr(model, field_name, None)
              log warning
          elif isinstance(value, BaseModel):
              gate_preview_fields(value)  # recurse into nested models
  ```

  The recursion covers `BaseModel` instances at any nesting depth. Lists and dicts of models
  are not recursed — preview fields are expected on config objects, not inside collections.

  This is a **safety net**, not the primary enforcement. The primary enforcement is
  schema-level: when preview is disabled, preview fields are stripped from the JSON schema,
  and the platform rejects configs that reference unknown fields. The runtime validator only
  activates in edge cases (e.g., config persisted before preview was disabled, or config
  injected bypassing schema validation). No warning stage is emitted — a log warning suffices
  for this defensive case.
- **Change:** New validator on `ApplicationConfig`.

### 5. Module-level preview gating

- **What:** A `@preview_module` decorator that marks a DI module class as preview, and
  filtering logic in `AppFactory` that excludes decorated modules when preview is disabled.
- **Owner:** `common/preview.py` (decorator), `app_factory.py` (filtering).
- **Semantics:** The decorator sets a `_is_preview_module = True` attribute on the class.
  `AppFactory.create()` reads `FeatureSettings` once at startup and filters the module list
  before passing it to the `Injector`:

  ```python
  _PREVIEW_MODULE_ATTR = "_is_preview_module"


  def preview_module(cls):
      """Mark a DI module as preview — filtered out when preview features are disabled."""
      setattr(cls, _PREVIEW_MODULE_ATTR, True)
      return cls


  def is_preview_module(module) -> bool:
      return getattr(type(module), _PREVIEW_MODULE_ATTR, False)
  ```

  In `AppFactory`:

  ```
  modules = [AppModule(), AgentModule(), ..., SomePreviewModule()]
  if not FeatureSettings().enable_preview_features:
      modules = [m for m in modules if not is_preview_module(m)]
  injector = Injector(modules)
  ```

  This is a pure startup-time check. When a preview module is filtered out, none of its
  bindings are registered — tools, transformers, providers, and initializers from that module
  are entirely absent. The decorator does not alter the module's inheritance chain or
  behavior; it only adds a marker attribute that `AppFactory` reads.

- **Change:** New decorator and helper in `common/preview.py`; modification to
  `AppFactory.create()`.

---

## Out of Scope

### Per-feature preview opt-in

An allowlist like `PREVIEW_FEATURES=timestamp,other_feature` would give operators granular
control over which preview features to enable. Deferred because a single boolean is sufficient
for the current scale of preview features. If the number of concurrent preview features grows,
this can be added as an extension to `FeatureSettings`.

### Preview feature documentation / changelog

A mechanism to auto-generate documentation of which features are in preview, what they do, and
when they were introduced. Deferred — the feature count is small enough that manual
documentation suffices.

---

## Configuration / Usage Examples

### Marking a field as preview

```python
class Features(BaseModel):
    timestamp: TimestampConfig | None = PreviewField(
        default=None, description="Time awareness configuration."
    )
```

### Graduating a feature to stable

```python
class Features(BaseModel):
    timestamp: TimestampConfig | None = Field(
        default=None, description="Time awareness configuration."
    )
```

### Marking a module as preview

```python
@preview_module
class TimestampModule(Module):
    def configure(self, binder: Binder):
        binder.bind(TimestampProvider, to=TimestampProvider, scope=singleton)
        ...
```

### Graduating a module to stable

```python
# Remove the decorator — module is always wired
class TimestampModule(Module):
    def configure(self, binder: Binder):
        binder.bind(TimestampProvider, to=TimestampProvider, scope=singleton)
        ...
```

### Environment configuration

```bash
# Staging — preview features enabled
ENABLE_PREVIEW_FEATURES=true

# Production — preview features disabled (default)
# ENABLE_PREVIEW_FEATURES is not set or set to false
```

### Runtime log output (edge case)

If an app config somehow contains `"features": {"timestamp": {}}` but preview is disabled
(e.g., config persisted before preview was turned off), the runtime validator logs:

```
WARNING - Preview feature "timestamp" is configured but preview features are disabled
(ENABLE_PREVIEW_FEATURES is not set). The feature has been deactivated.
```

Under normal operation this does not occur — the platform rejects such configs at the schema
validation level.

---

## Migration

### Breaking changes

None.

### Non-breaking changes

- New `PreviewField` helper in `base_config.py` — no effect on existing fields.
- New `FeatureSettings` class — only read when preview gating logic is invoked.
- `model_json_schema()` modification — strips fields when `ENABLE_PREVIEW_FEATURES` is not
  set. `dump_app_schema` and CI run with `ENABLE_PREVIEW_FEATURES=true`, so the committed
  schema is always the full version.
- New `model_validator` on `ApplicationConfig` — only activates when preview fields slip
  through with gating off. Existing configs with no preview fields are unaffected.
- New `@preview_module` decorator — no effect on existing modules. Only modules explicitly
  decorated are filtered.
- `AppFactory` filtering — existing modules are unaffected; the filter is a no-op when no
  preview modules are registered.

## Summary of Changes

### `common/base_config.py`

- **Add** `_PREVIEW_MARKER` constant
- **Add** `PreviewField()` helper function
- **Add** `strip_preview_fields()` utility

### `common/`

- **Add** `FeatureSettings(BaseSettings)` (`feature_settings.py`)
- **Add** `preview_module` decorator and `is_preview_module` helper (`preview.py`)

### `common/base_config.py` (`BaseApplicationTypeConfig`)

- **Modify** `model_json_schema()` — apply `strip_preview_fields()` when
  `ENABLE_PREVIEW_FEATURES` is not set

### `config/application.py`

- **Add** `model_validator` on `ApplicationConfig` for runtime preview gating (nullify +
  log warning)

### `app_factory.py`

- **Modify** `AppFactory.create()` — filter out `@preview_module`-decorated modules when
  `ENABLE_PREVIEW_FEATURES` is not set

### `Makefile`

- **Modify** `dump_app_schema` and `lint` targets — set `ENABLE_PREVIEW_FEATURES=true` so
  the committed schema includes all preview fields
