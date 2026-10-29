# Design: User Time Zone

- **Status:** Approved
- **Approved:** 2026-10-29
- **Issue:** [I#649](https://github.com/epam/ai-dial-quickapps-backend/issues/649)
- **Dependencies:**
  - [Time Awareness](time_awareness.md)

## Problem Statement

`TimestampModule` binds `TimeProvider` with its defaults (`UTC`, `TimestampSource.DEFAULT`). The injected timestamp,
the tool-result annotations and `current_timestamp` therefore all use UTC. "Today" or "tomorrow morning" resolves
against UTC, so near midnight the date is wrong, and times sent to calendar tools are off by the user's offset.

The user's zone already reaches QuickApps. The reason time awareness deferred this ("Core does not pass a time zone")
no longer holds:

| Hop | Today |
|-----|-------|
| Chat → Core | Chat sends the browser zone as `X-Timezone` ([ai-dial-chat I#8442](https://github.com/epam/ai-dial-chat/issues/8442); Chat 1.1.0+ and `development-0.x`) |
| Core → app | `ProxyUtil.copyHeaders` forwards it unchanged |
| QuickApps | Lands in `ForwardedHeaders` (observed: `forwarded_headers=['x-timezone', …]`); not used for time |

No Chat or Core change is needed.

## Design Goals

- A valid `X-Timezone` drives the injected timestamp, the tool-result annotations and `current_timestamp` called
  without an argument.
- `features.timestamp.default_timezone` is the fallback when the request has none; UTC otherwise.
- An invalid header never fails the request.
- Every timestamp the model sees carries its UTC offset.

---

## Use Cases

| # | Trigger | Outcome |
|---|---------|---------|
| UC-1 | A Kyiv user asks "what's on my calendar today?" at 00:30 local (22:30 UTC) | Injected `2026-10-30T00:30:00+02:00 (Europe/Kyiv, source=request)`; the agent queries 30 Oct |
| UC-2 | An API client sends no header; the app sets `default_timezone: Europe/Warsaw` | Warsaw time, `source=default` |
| UC-3 | The header is `UTC+3` (invalid) | Ignored with a DEBUG record; falls back to `default_timezone`, then UTC |
| UC-4 | A Kyiv user asks for the time in Tokyo | `current_timestamp({"timezone": "Asia/Tokyo"})` as today; with no argument it returns Kyiv time |
| UC-5 | The user's zone changes mid-conversation | Old entries keep their zone and offset; the new turn uses the new zone |

---

## Proposed Design

```mermaid
flowchart LR
    H["X-Timezone"] --> C["TIMEZONE_HEADER_VALUE (raw)"]
    C --> R{"resolve_user_timezone"}
    A["features.timestamp.default_timezone"] --> R
    R -->|"valid header"| P1["TimeProvider(zone, REQUEST)"]
    R -->|"else default set"| P2["TimeProvider(zone, DEFAULT)"]
    R -->|"else"| P3["TimeProvider(UTC, DEFAULT)"]
```

### 1. Reading the header

- `common/_di_types.py`: constant `TIMEZONE_HEADER = "X-Timezone"` and DI key
  `TIMEZONE_HEADER_VALUE = Annotated[str | None, "TIMEZONE_HEADER_VALUE"]`.
- `_RequestContextSetup.setup_context` stores the raw header value in `_RequestContext.timezone_header_value`, next
  to `accept_language`. `AppModule` provides it, and no validation happens at this point.
- The header name is fixed, with no `PROXY_*` env override, because no proxy is known to rewrite it.

### 2. Resolving and validating (`timestamp_tooling`)

- `resolve_user_timezone(header_value, default_timezone) -> tuple[ZoneInfo, TimestampSource]`:
  valid header → `REQUEST`; else `default_timezone` → `DEFAULT`; else UTC → `DEFAULT`. The user's zone wins over
  the app default.
- `TimestampSource` keeps its two values: `request` means the zone was given explicitly (header or
  `current_timestamp` argument), and `default` means it was assumed. A new value would break older pods during a
  rollout, because `get_metadata_from_state` rejects unknown values.
- `is_valid_iana_timezone(name)` in `common/` checks membership in the `tzdata` package's `zones` list (598 names)
  minus `Factory`. It does not use `ZoneInfo(name)`, which probes the filesystem: that call accepts `europe/warsaw`
  on macOS and resolves `localtime` to the server's zone. `tzdata` becomes a direct dependency.
- Aliases such as `Europe/Kiev` (still reported by Chrome) are accepted as sent.
- The value is stripped, and an empty value counts as absent. An invalid value is logged at DEBUG with the header
  name and value length only (CODESTYLE §9).

### 3. Building `TimeProvider` (`TimestampModule`)

- A request-scoped `@provider` replaces the class binding. It returns `TimeProvider(*resolve_user_timezone(...))`,
  or plain UTC without resolving when the feature is off.
- Ordering: `TimeProvider` is first resolved through `ProviderOf` in `_MessagesSetup.run_transformers`, after
  `setup_context`. Fix the stale comment in `_provide_message_transformers` that says otherwise. A unit test pins
  this.

### 4. What the model sees

| Surface | Today | After (Kyiv) |
|---------|-------|--------------|
| Injected timestamp | `2026-10-29T11:36:12+00:00 (UTC, source=default)` | `2026-10-29T13:36:12+02:00 (Europe/Kyiv, source=request)` |
| Tool-result annotation | `[Timestamp: 2026-10-29 11:36:12 UTC]` | `[Timestamp: 2026-10-29 13:36:12+02:00 Europe/Kyiv]` (adds `%:z`) |
| `current_timestamp` `timezone` description | "Defaults to UTC." | "Defaults to the time zone of the injected current timestamp." |

### 5. App-level default (`config/timestamp.py`)

- Add `ToolCallTimestampConfig.default_timezone: str | None = PreviewField(default=None)`.
- An invalid value (per `is_valid_iana_timezone`) fails config validation. A typo by the app author should be loud, not silently UTC.
- In the schema it is a plain string; no enum of about 600 names.
- Only the field is preview-gated. Header resolution fixes a Stable feature, and `"timestamp": null` turns it off.

---

## Secondary Fixes

- `current_timestamp` passes the model's `timezone` argument straight to `ZoneInfo`. Apply the header's
  normalization instead: strip the value, and treat an empty string as absent (models often send `""`). Then call
  `is_valid_iana_timezone` and raise `InvalidToolCallParameterException("timezone", …)`, so the model retries.

---

## Out of Scope

| Item | Why deferred |
|------|--------------|
| Learn the zone from conversation | Chat already sends the header, and API clients can send it or rely on `default_timezone` |
| Editor field for `default_timezone` | JSON config works today; tracked as a follow-up editor issue |
| App-pinned zone (override the user's) | No demand. Workaround: system prompt or an explicit `current_timestamp` zone. Can be added later as `timezone_mode: fallback \| fixed` |
| Per-user stored preference | Belongs in Chat or Core user settings |

---

## Configuration / Usage Examples

```json
{ "features": { "timestamp": { "default_timezone": "Europe/Warsaw" } } }
```

| `X-Timezone` | `default_timezone` | Zone | `source` |
|--------------|--------------------|------|----------|
| `Europe/Kyiv` | any | `Europe/Kyiv` | `request` |
| absent / empty / invalid | `Europe/Warsaw` | `Europe/Warsaw` | `default` |
| absent / empty / invalid | unset | `UTC` | `default` |

API clients set `X-Timezone` themselves; Core forwards it.

---

## Migration

### Breaking changes

- Behaviour change: Chat users see local time instead of UTC. Apps whose prompts assume UTC should drop that
  assumption. Call this out in the release notes.

### Non-breaking changes

- `default_timezone` is optional.
- Integration-test LLM caches that include the tool description or annotations must be re-recorded.

### Known issues (to record in `docs/time_awareness.md`)

| What happens | Where | Workaround |
|--------------|-------|------------|
| No header, so `default_timezone` or UTC is used | API clients, scheduled runs, Chat older than I#8442 | Send `X-Timezone` or set `default_timezone` |
| A valid but wrong zone overrides `default_timezone` | Firefox `resistFingerprinting` / Tor Browser (`UTC` or `Atlantic/Reykjavik`), or a misconfigured OS | Fix the browser or OS; or name the zone so the agent passes it to `current_timestamp` |

## Summary of Changes

| Component | Change |
|-----------|--------|
| `common/_di_types.py` | `TIMEZONE_HEADER`, `TIMEZONE_HEADER_VALUE` |
| `common/` | `is_valid_iana_timezone` |
| `core/application/` | `_RequestContext.timezone_header_value`; read in `setup_context`; provided by `AppModule` |
| `config/timestamp.py` | `default_timezone` (`PreviewField`) with validator |
| `timestamp_tooling/` | `resolve_user_timezone`; `TimeProvider` provider; offset in the annotation; tool description; argument validation; stale comment fixed |
| `pyproject.toml` | `tzdata` as a direct dependency |
| `CONFIGURATION.md`, `docs/time_awareness.md` | `default_timezone`; local-zone behaviour; known issues |
| `docs/README.md` | Time awareness row: add this design to the L3 column |
| App schema | Regenerated |
