# Time Awareness `[Preview]`

> [!IMPORTANT]
> Time Awareness is a **preview** feature. Its API and behavior may change in breaking ways without a major
> version bump. See [Feature Lifecycle](../README.md#feature-lifecycle) for details.

## Why

LLMs have no inherent sense of time. Without external help, the agent cannot answer "what day is it?", reason
about whether fetched data is stale, or compute deadlines relative to "now."

Time awareness solves this by giving the agent access to the current time and annotating tool results with
their production timestamps.

## What it does

When enabled, the feature provides three capabilities:

1. **The agent always knows the current time.** At every user turn, the current UTC timestamp is automatically
   injected into the conversation. The agent can answer time-sensitive questions immediately, without making any
   tool calls.

2. **The agent can convert timezones.** If a user asks "what time is it in Tokyo?", the agent calls the
   `current_timestamp` tool with `timezone: "Asia/Tokyo"`. The conversion is done server-side, avoiding LLM
   errors with DST or unusual offset rules.

3. **Tool results carry freshness information.** Every tool response is automatically annotated with the time
   it was produced. When the agent executes multiple tools across several iterations, it can compare each
   result's production time against the current time and assess staleness. For example, if a weather API was
   called 10 minutes ago and the user asks a follow-up question, the agent can see the age of the data and
   decide whether to re-fetch or reuse the earlier result.

## How to enable

Add a `features` section to the application config:

```json
{
  "orchestrator": { "deployment": { "name": "gpt-4o" } },
  "features": {
    "timestamp": {}
  }
}
```

The feature is enabled by default when preview features are active. To explicitly disable it for a specific app,
set `"timestamp": null`.

## What the agent sees

On the first turn, the agent receives the current time as if it had called a tool:

```
[user]      What day is it?
[assistant] (tool_call: current_timestamp -> {})
[tool]      2026-03-24T14:30:00+00:00 (UTC, source=default)
[assistant] Today is Monday, March 24, 2026.
```

On subsequent turns, previous timestamps are preserved with their original times, and a fresh timestamp is
appended — so the agent can see the progression of time across the conversation.

### Tool result annotations

Every tool response (REST APIs, deployments, MCP tools, etc.) is annotated with its production time before
being sent to the LLM:

```
{"temperature": 22, "unit": "celsius"}
[Timestamp: 2026-03-24 14:30:00 UTC]
```

The agent can compare this against the current time to reason about freshness. For instance, if the agent
fetched stock prices at 14:30 and the user asks again at 14:45, the agent sees a 15-minute gap and can decide
to call the API again rather than reusing stale data.

These annotations are transient — they are visible only to the LLM during processing and do not appear in the
persisted conversation history or in the response shown to the user.
