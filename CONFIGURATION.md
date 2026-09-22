# Quick Apps (2.0) — Configuration Reference

This file contains the full configuration reference for Quick Apps (2.0): configuration model,
orchestrator configuration, contexts, tool sets, tool fallback and attachments, authorization types, parameters,
display configuration, environment variables, examples and notes for registering and running Quick Apps.

Navigation: [Documentation hub](docs/README.md) · [Local development](docs/local-development.md) · [Root README](README.md)

## Configuration model

Quick Apps are defined by a JSON-schema–validated manifest.
Schema reference:

- Generated locally via: make dump_app_schema
- Hosted reference: https://mydial.epam.com/custom_application_schemas/quickapps2

The `$id` written into the generated schema defaults to that hosted URL. Override it with
`APP_SCHEMA_ID` when your DIAL installation uses a different hostname or schema name
(see [Environment Variables](#environment-variables)). When unset, the current default is kept
for backward compatibility.

## Agent Configuration:

<details>
<summary><b>Configuration JSON Sample</b></summary>

The project contains predefined configs of application and predefined tools

* [Sample application](../docker_compose_files/core/configuration/applications.json).
* [Chat-hub application](../docker_compose_files/core/configuration/chathub/openai.json).
* [Predefined Tools/Toolsets](../config/predefined).

<br>Here's a full example of configuration:

```json
{
  "orchestrator": {
    "deployment": {
      "deployment_id": "gpt-4o-2024-05-13",
      "parameters": {
        "temperature": 1.0,
        "seed": 820288
      }
    },
    "system_prompt": {
      "type": "custom",
      "variables": {},
      "content": "This is base Agent prompt."
    },
    "max_iterations": 10
  },
  "contexts": [
    {
      "type": "file",
      "description": "Some file context description",
      "url": "files/mybucket/file_to_convert.png"
    },
    {
      "type": "user-defined",
      "description": "Some user context description",
      "content": "Content of user defined context"
    }
  ],
  "tool_sets": [
    {
      "name": "Location rest-api toolset",
      "type": "rest-api",
      "authorization": {
        "type": "api_key",
        "key": "<API_KEY>",
        "name": "api_key",
        "location": "query"
      },
      "tools": [
        {
          "rest_api_method_info": {
            "method_url": "https://geocode.maps.co/search",
            "method_type": "get"
          },
          "display": {
            "stage": {
              "name": "Get GEO code: "
            }
          },
          "open_ai_tool": {
            "type": "function",
            "function": {
              "name": "geo_code",
              "description": "To get geo information (lat, lon, etc.) for the address, or city, or location",
              "parameters": {
                "type": "object",
                "properties": {
                  "q": {
                    "type": "string",
                    "description": "location you want to get geo information about",
                    "parameter_info": {
                      "type": "query",
                      "key": "q"
                    },
                    "display": {
                      "stage": {
                        "show_value_in_stage_title": true
                      }
                    }
                  }
                },
                "required": [
                  "q"
                ]
              }
            }
          }
        }
      ]
    },
    {
      "name": "dial-deployment-tool-set",
      "type": "dial-deployment",
      "description": "Set with DIAL deployments tools",
      "tools": [
        {
          "type": "predefined-tool",
          "template_name": "dial_rag"
        },
        {
          "type": "deployment-tool",
          "display": {
            "stage": {
              "name": "Image Generation: "
            }
          },
          "deployment": {
            "deployment_id": "dall-e-3"
          },
          "open_ai_tool": {
            "type": "function",
            "function": {
              "name": "image_generation_tool",
              "description": "**Image generator** Generates image based on the provided description.\n\n## Instructions:\n- Use that tool when user asks to generate an image based on the description or to visualize some text or information.\n- Choose the best size from available options based on user request or image type. For specific size requests, use the closest supported option.\n- When the tool returns a markdown image URL, always include it in your response and follow it with a brief description.\n\n## Restrictions:\n- Never use this tool for data or numerical information visualization.",
              "parameters": {
                "type": "object",
                "properties": {
                  "query": {
                    "type": "string",
                    "description": "Extensive description of the image that should be generated.",
                    "display": {
                      "stage": {
                        "show_value_in_stage_title": true,
                        "name": "**Prompt:** "
                      }
                    }
                  },
                  "size": {
                    "type": "string",
                    "description": "The size of the generated image. ",
                    "enum": [
                      "1024x1024",
                      "1024x1792",
                      "1792x1024"
                    ],
                    "default": "1024x1024",
                    "display": {
                      "stage": {
                        "name": "**Image size:** "
                      }
                    }
                  },
                  "style": {
                    "type": "string",
                    "description": "The style of the generated image. Must be one of vivid or natural. Vivid causes the model to lean towards generating hyper-real and dramatic images. Natural causes the model to produce more natural, less hyper-real looking images.",
                    "enum": [
                      "natural",
                      "vivid"
                    ],
                    "default": "natural",
                    "display": {
                      "stage": {
                        "name": "**Image style:** "
                      }
                    }
                  },
                  "quality": {
                    "type": "string",
                    "description": "The quality of the image that will be generated. `hd` creates images with finer details and greater consistency across the image.",
                    "enum": [
                      "standard",
                      "hd"
                    ],
                    "default": "standard",
                    "display": {
                      "stage": {
                        "name": "**Image quality:** "
                      }
                    }
                  }
                },
                "required": [
                  "query",
                  "size",
                  "style",
                  "quality"
                ]
              }
            }
          },
          "attachment": {
            "propagate_types_to_choice": [
              "image/*"
            ]
          },
          "fallback_configuration": {
            "strategies": [
              {
                "type": "continue"
              }
            ]
          }
        },
        {
          "type": "predefined-tool",
          "template_name": "web_search"
        }
      ]
    },
    {
      "type": "predefined",
      "template_name": "py_interpreter"
    },
    {
      "name": "mcp-toolset",
      "description": "Set with MCP tools",
      "type": "mcp",
      "mcp_server_info": {
        "url": "https://remote.mcpservers.org/fetch/mcp",
        "protocol": "streamable_http",
        "authorization": null
      }
    }
  ]
}
```

</details>

## Main Configuration Structure

| Field        | Required | Type         | Description                                                                                                                                           | Available Values | Default Value |
|--------------|----------|--------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|------------------|---------------|
| orchestrator | Yes      | Object       | Configurations for Agent (model, system prompt, etc.). [Orchestrator configuration](#orchestrator-configuration)                                      | -                | -             |
| contexts     | Yes      | List[Object] | The list of contexts. [Contexts configuration](#contexts-configuration)                                                                               | -                | -             |
| tool_sets    | Yes      | List[Object] | The list of tool sets. Toolset contains tools with their configurations that groped by some type. [Tool sets configuration](#tool-sets-configuration) | -                | -             |
| features     | No       | Object       | Per-app feature overrides (file loading, external URL egress, stage display, dial files, etc.). [Features configuration](#features-configuration)      | -                | `{}`          |
| skills       | No       | List[Object] | Optional list of DIAL prompt / DIAL skill resources. [Skills configuration](#skills-configuration)                                                    | -                | `null`        |
| hooks        | No       | List[Object] | `[Preview]` Config-driven synthetic tool-call hooks. [Hooks configuration](#hooks-configuration)                                                      | -                | `null`        |
| tool_defaults | No      | Object       | Defaults applied to every tool call (e.g. timeout). [Tool defaults configuration](#tool-defaults-configuration)                                       | -                | `{}`          |
| conversation_starters | No | Object    | Conversation starter chips. [Conversation starters](#conversation-starters-configuration). Deprecated top-level `starters` still accepted. | -                | `null`        |

### Orchestrator configuration

| Field          | Required | Type    | Description                                                                                              | Available Values | Default Value |
|----------------|----------|---------|----------------------------------------------------------------------------------------------------------|------------------|---------------|
| deployment     | Yes      | Object  | The DIAL deployment configuration. See [Deployment configuration](#deployment-configuration)             | -                | -             |
| system_prompt  | Yes      | Object  | The configuration for the system prompt. See [System prompt configuration](#system-prompt-configuration) | -                | -             |
| max_iterations | No       | Integer | The max count of orchestrator(agent) operations. -1 value for infinite                                   | Integer          | 15            |
| attachment_strategy | No  | Object  | How the orchestrator receives request-scoped attachments. See [Attachment strategy](#attachment-strategy-configuration) | - | `null` |
| tool_discovery | No       | Object  | `[Preview]` Dynamic tool discovery configuration. See [Tool discovery configuration](#tool-discovery-configuration) | -   | `null`        |

#### Attachment strategy configuration

Opt-in. When unset (`null`), the orchestrator does not receive admin/user attachments on the native
path (USER `image/*` still passes through; other MIMEs appear as XML metadata only).

| Field  | Required | Type   | Description | Default |
|--------|----------|--------|-------------|---------|
| `type` | Yes      | String | Only `lazy_on_demand` today — attachments load via `internal_attachments_get_content` on demand (MIME-gated by the orchestrator deployment's `input_attachment_types`) | `lazy_on_demand` |

```json
{
  "orchestrator": {
    "deployment": { "deployment_id": "gpt-4o" },
    "attachment_strategy": { "type": "lazy_on_demand" }
  }
}
```

See [docs/agent.md — Orchestrator attachment strategies](./agent.md#orchestrator-attachment-strategies).

#### Deployment configuration

| Field      | Required | Type   | Description                                                                                                                      | Available Values          | Default Value |
|------------|----------|--------|----------------------------------------------------------------------------------------------------------------------------------|---------------------------|---------------|
| name       | Yes      | String | The DIAL deployment name to be used for the agent                                                                                | Any valid deployment name | -             |
| parameters | No       | Object | The parameters to configure Agent model, [See Request parameters](https://dialx.ai/dial_api#operation/sendChatCompletionRequest) | -                         | `null`        |

<details>
<summary><b>Deployment configuration JSON sample</b></summary>

Sample:

```json
{
  "deployment": {
    "name": "gpt-4o-2024-08-06",
    "parameters": {
      "temperature": 1.1,
      "seed": 820288
    }
  }
}
```

With custom fields sample:

```json
{
  "deployment": {
    "name": "us.anthropic.claude-3-7-sonnet-20250219-v1",
    "parameters": {
      "temperature": 1.0,
      "custom_fields": {
        "configuration": {
          "betas": [
            "token-efficient-tools-2025-02-19"
          ]
        }
      }
    }
  }
}
```

</details>

#### System prompt configuration

| Field     | Required                    | Type                 | Description                                                      | Available Values | Default Value |
|-----------|-----------------------------|----------------------|------------------------------------------------------------------|------------------|---------------|
| type      | Yes                         | String               | The type of the System prompt                                    | `dial`, `custom` | -             |
| variables | Yes                         | Dict[String, String] | Dict with variables that should be replaced in the system prompt | -                | -             |
| content   | Yes (if `type` is `custom`) | String               | The system prompt itself                                         | -                | -             |

<details>
<summary><b>System prompt configuration JSON sample</b></summary>

Custom system prompt:

```json
{
  "system_prompt": {
    "type": "custom",
    "variables": {
      "reason_of_life": "42"
    },
    "content": "This is base Agent prompt. The reason of life is {reason_of_life}"
  }
}
```

</details>

#### Tool discovery configuration

`[Preview]` Requires `ENABLE_PREVIEW_FEATURES=true`. When enabled, toolsets withheld from the initial LLM payload
(see the per-toolset `deferred` field in [Tool sets configuration](#tool-sets-configuration)) are surfaced on demand
via the `internal_tool_search` meta-tool (referred to as "tool search" below), which routes the query to the matching
tool schemas through an isolated LLM call.

| Field                  | Required | Type    | Description                                                                                                                                                | Available Values | Default Value |
|------------------------|----------|---------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------|---------------|
| enabled                | No       | Boolean | Enable dynamic tool discovery. When `true`, toolsets with `deferred: true` are withheld from the initial LLM payload and surfaced via the `internal_tool_search` meta-tool. | -                 | `false`       |
| service_model          | No       | String  | DIAL deployment used for the anonymous routing call inside `internal_tool_search`. Falls back to the orchestrator's own deployment when omitted.                      | -                 | -             |
| min_tools_for_deferral | No       | Integer | Minimum number of tools in a toolset for deferral to apply. Toolsets smaller than this threshold are promoted to eager loading even when `deferred: true`. Deployment-wide default set by `MIN_TOOLS_FOR_DEFERRAL`. | -    | `10`          |

<details>
<summary><b>Tool discovery configuration JSON sample</b></summary>

```json
{
  "orchestrator": {
    "deployment": { "name": "gpt-4o" },
    "tool_discovery": {
      "enabled": true,
      "service_model": "gpt-4o-mini",
      "min_tools_for_deferral": 5
    }
  }
}
```

</details>

See [Dynamic Tool Discovery design doc](docs/designs/dynamic_tool_discovery.md) for the full behavioral reference.

### Contexts configuration

Contexts are a discriminated union on `type`. Each entry is one of the shapes below.

#### User-defined context (`type: user-defined`)

| Field   | Required | Type   | Description                    | Default Value |
|---------|----------|--------|--------------------------------|---------------|
| type    | Yes      | String | Must be `user-defined`         | -             |
| content | Yes      | String | Inline context text            | -             |

#### File context (`type: file`)

| Field       | Required | Type   | Description                                              | Default Value |
|-------------|----------|--------|----------------------------------------------------------|---------------|
| type        | Yes      | String | Must be `file`                                           | -             |
| url         | Yes      | String | Relative DIAL file URL (e.g. `files/{bucket}/{path}`)    | -             |
| description | No       | String | Optional description for the agent                       | `null`        |

#### Folder context (`type: folder`)

Requires `ENABLE_PREVIEW_FEATURES=true`. When preview is off, folder entries are stripped from
`contexts` at request validation.

On every request the folder is expanded (files and subfolders, up to `max_depth`) into the
`internal_attachments_available_context` response so newly uploaded files become discoverable
without editing the manifest. Folder expansion does **not** require `features.dial_files`.

| Field       | Required | Type    | Description                                                                 | Default Value |
|-------------|----------|---------|-----------------------------------------------------------------------------|---------------|
| type        | Yes      | String  | Must be `folder`                                                            | -             |
| url         | Yes      | String  | Relative DIAL folder URL; **must end with `/`**                              | -             |
| description | No       | String  | Optional folder-level description                                           | `null`        |
| max_depth   | No       | Integer | Max recursion depth when expanding (1–10)                                   | `10`          |
| mime        | No       | String  | Folder MIME marker                                                          | `application/vnd.dial.metadata+json` |

<details>
<summary><b>Contexts configuration JSON sample</b></summary>

User-defined context:

```json
{
  "type": "user-defined",
  "content": "Content of user defined context"
}
```

File context:

```json
{
  "type": "file",
  "description": "Some file context description",
  "url": "files/{bucket}/{path}/{name}"
}
```

Folder context (preview):

```json
{
  "type": "folder",
  "description": "Shared team docs",
  "url": "files/{bucket}/shared-docs/",
  "max_depth": 5
}
```

</details>

### Features configuration

Per-app feature overrides under the manifest's `features` object. All fields are optional; unset
fields fall back to the deployment-wide defaults configured via environment variables (where
applicable). Preview-gated fields require `ENABLE_PREVIEW_FEATURES=true`; otherwise they are
nullified at request validation.

Omitting `features` (or setting `{}`) still constructs the default `Features` object — time
awareness stays **on**, and nested objects like `file_loading` / `stage_display` use their defaults.
Setting `"features": null` turns off those defaults (no timestamp feature, no per-app dial-files /
external-fetch overrides; stage display falls back to `info` unless `DEFAULT_STAGE_DISPLAY_LEVEL` is set).

| Field                    | Required | Type           | Preview | Description                                                                                                                                                                  | Default Value                          |
|--------------------------|----------|----------------|---------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------|
| `timestamp`              | No       | Object or null | No      | Time awareness - the agent knows the current time and tool results carry production timestamps. `null` disables it. See [Timestamp configuration](#timestamp-configuration). | `{"injection_strategy": "tool_call"}` |
| `file_loading`           | No       | Object         | No      | Per-app file download size limit. See [File loading configuration](#file-loading-configuration).                                                                           | `{}`                                   |
| `external_url_fetch`     | No       | Object         | No      | Per-app override for fetching external (non-DIAL) URLs. See [External URL fetch configuration](#external-url-fetch-configuration).                                           | `{}`                                   |
| `stage_display`          | No       | Object         | No      | Which tool-execution stages appear in the DIAL UI. See [Stage display configuration](#stage-display-configuration).                                                          | `{"level": "info"}`                    |
| `dial_files`             | No       | Object or null | No      | Built-in DIAL workspace file tools. `null` (default) disables them. See [DIAL files configuration](#dial-files-configuration).                                               | `null`                                 |
| `web_fetch`              | No       | Object or null | **Yes** | Built-in `internal_web_fetch` tool. See [Web fetch configuration](#web-fetch-configuration).                                                                                 | `null`                                 |
| `representation_tooling` | No       | Object or null | **Yes** | Tools that control how the agent surfaces output (e.g. add attachment to the answer). See [Representation tooling](#representation-tooling-configuration).                   | `null`                                 |

#### Timestamp configuration

Enables [time awareness](./time_awareness.md): the current timestamp is injected at every user
turn, a `current_timestamp` tool is registered for timezone conversion, and every tool response is
annotated with the time it was produced.

The feature is **enabled by default** - omitting `features` entirely, or omitting the `timestamp`
key, yields the default configuration below. Set `"timestamp": null` to turn it off for an app; the
tool, transformers, and metadata enricher are then not registered at all.

| Field                | Required | Type   | Description                                                                                                | Available Values | Default Value |
|----------------------|----------|--------|----------------------------------------------------------------------------------------------------------------|------------------|---------------|
| `injection_strategy` | No       | String | How the current timestamp reaches the model. `tool_call` injects a synthetic `current_timestamp` tool-call and result immediately before the last user message. | `tool_call`      | `tool_call`   |

`tool_call` is the only strategy available today, so you can leave the field out — `{}` behaves
exactly like `{"injection_strategy": "tool_call"}`. Other strategies may be added in the future.

<details>
<summary><b>Timestamp configuration JSON sample</b></summary>

Enable with the default strategy, stated explicitly:

```json
{
  "features": {
    "timestamp": {
      "injection_strategy": "tool_call"
    }
  }
}
```

Disable time awareness for this app:

```json
{
  "features": {
    "timestamp": null
  }
}
```

</details>

#### File loading configuration

| Field        | Required | Type            | Description                                                                                                                                 | Default Value |
|--------------|----------|-----------------|---------------------------------------------------------------------------------------------------------------------------------------------|---------------|
| `size_limit` | No       | Integer or null | Max bytes for a single file download. `null` defers to env `DEFAULT_FILE_LOADING_SIZE_LIMIT` (default 10 MiB). Must be `> 0` when set.     | `null`        |

```json
{
  "features": {
    "file_loading": {
      "size_limit": 5242880
    }
  }
}
```

#### External URL fetch configuration

External URL fetching is gated by **two tiers** that compose: an admin tier (env vars under
`EXTERNAL_URL_FETCH_*`, see [Environment Variables](#environment-variables)) and a builder tier
(this `features.external_url_fetch` object). The admin tier is a hard cap — a per-app override
can only narrow it, never expand it. The deployment-handoff branch (DIAL deployments advertising
`features.url_attachments`) is never gated: the deployment fetches the URL itself, so no
QuickApps egress happens.

Builder-tier fields:

| Field            | Required | Type            | Description                                                                                                                                                                                                                                                                | Default Value |
|------------------|----------|-----------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------|
| `enabled`        | No       | Boolean or null | Per-app override of the on/off gate. `null` (default) defers to the admin env switch. `false` opts this app out even when the admin allows. `true` is a no-op when admin allows; the admin gate is a hard cap.                                                              | `null`        |
| `host_allowlist` | No       | Array[String] or null | Per-app override of the allowed hosts. `null` (default) defers to the admin env var. A non-empty list **narrows** the admin list (intersection) — a host must be in both lists to be allowed. An explicit empty list locks this app out of all hosts. Patterns: exact host (`example.com`) or `*.example.com` for any subdomain. | `null`        |

<details>
<summary><b>External URL fetch configuration JSON sample</b></summary>

Opt this app out even when the admin allows external fetches:

```json
{
  "features": {
    "external_url_fetch": {
      "enabled": false
    }
  }
}
```

Narrow the admin allowlist for a high-trust app (admin permits `example.com` and `partner.io`,
this app only allows `example.com`):

```json
{
  "features": {
    "external_url_fetch": {
      "host_allowlist": ["example.com"]
    }
  }
}
```

</details>

See [`docs/file_transfer.md`](./file_transfer.md) for the full pipeline (URL classification,
SSRF envelope, deployment dispatch table, error messages and agent retry behaviour).

#### Stage display configuration

Controls which tool-execution stages are surfaced in the DIAL UI. The deployment-wide env
`DEFAULT_STAGE_DISPLAY_LEVEL`, when set, **wins over** every app's `features.stage_display.level`.

| Field   | Required | Type   | Description                                                                 | Available Values                         | Default Value |
|---------|----------|--------|-----------------------------------------------------------------------------|------------------------------------------|---------------|
| `level` | No       | String | Visibility threshold                                                        | `none`, `error`, `info`, `debug`         | `info`        |

| Value   | Behavior                                                              |
|---------|-----------------------------------------------------------------------|
| `none`  | No stages at all, not even for errors                                 |
| `error` | Stages only for failed tool calls                                     |
| `info`  | Regular tool calls and errors (default)                               |
| `debug` | All tool calls, including internal/system ones                        |

```json
{
  "features": {
    "stage_display": {
      "level": "debug"
    }
  }
}
```

#### DIAL files configuration

Opt in to the built-in workspace file tools (`internal_file_*`). Omit `dial_files` or set it to
`null` to leave file tools off. Setting `"dial_files": {}` enables **all** tools with defaults.

| Field                      | Required | Type                         | Preview | Description                                                                                                                                 | Default Value |
|----------------------------|----------|------------------------------|---------|---------------------------------------------------------------------------------------------------------------------------------------------|---------------|
| `enabled_tools`            | No       | `"all"` or Array[String]     | No      | Which tools to expose. Short names: `list`, `read_lines`, `search`, `find`, `write`, `edit`, `delete`, `copy`, `move`.                    | `"all"`       |
| `agent_home_dir`           | No       | String                       | No      | Relative sub-directory under appdata used as the root for relative paths. Must end with `/`; no `files/…`, leading `/`, or `..`. Empty = appdata root. | `""`          |
| `max_files_scanned`        | No       | Integer (`≥ 1`)              | No      | Folder-mode `search` cap: max files downloaded/scanned per call before truncation.                                                          | `50`          |
| `tool_call_result_offload` | No       | Object or null               | **Yes** | Offload oversized tool responses to a DIAL file. See below. Requires `read_lines` and `search` in `enabled_tools`.                          | defaults (see below) |

##### Tool-call result offload

Nested under `features.dial_files.tool_call_result_offload`. Requires `ENABLE_PREVIEW_FEATURES=true`.
Env defaults: `TOOL_CALL_RESULT_OFFLOAD__*`.

| Field            | Required | Type          | Description                                                                                          | Default Value |
|------------------|----------|---------------|------------------------------------------------------------------------------|---------------|
| `enabled`        | No       | Boolean       | Whether to offload oversized tool responses                                                          | env `TOOL_CALL_RESULT_OFFLOAD__ENABLED_BY_DEFAULT` (`true`) |
| `size_threshold` | No       | Integer (`> 0`) | Byte threshold above which a response is offloaded                                                 | env `TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD` (`40000`) |
| `excluded_tools` | No       | Array[String] | **Additional** tool names exempt from offload (additive). `internal_file_read_lines`, `internal_file_search`, and `read_skill` are always excluded. | env list (default empty) |

```json
{
  "features": {
    "dial_files": {
      "enabled_tools": "all",
      "agent_home_dir": "workspace/",
      "tool_call_result_offload": {
        "enabled": true,
        "size_threshold": 40000
      }
    }
  }
}
```

#### Web fetch configuration

Requires `ENABLE_PREVIEW_FEATURES=true`. When enabled, exposes `internal_web_fetch`: fetch an
external `http(s)` resource inline (truncated to `max_inline_size`) or persist it under the
agent home via `save_path`. Egress uses the same two-tier policy as
[External URL fetch](#external-url-fetch-configuration).

If `web_fetch.enabled` is `true` while external URL fetching is disabled (admin
`EXTERNAL_URL_FETCH_ENABLED=false`, or this app set `features.external_url_fetch.enabled=false`),
initialization fails with a hard `ToolInitializationException` — fix the egress policy or remove
`features.web_fetch`.

| Field              | Required | Type    | Description                                                                 | Default Value |
|--------------------|----------|---------|-----------------------------------------------------------------------------|---------------|
| `enabled`          | No       | Boolean | Expose `internal_web_fetch`                                                 | `false`       |
| `max_inline_size`  | No       | Integer (`> 0`) | Byte cap on decoded inline text; larger text is truncated with a notice. Binary must use `save_path`. | env `TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD` (`40000`) |

```json
{
  "features": {
    "web_fetch": {
      "enabled": true
    }
  }
}
```

#### Representation tooling configuration

Requires `ENABLE_PREVIEW_FEATURES=true`. Omit or set `null` to disable the whole section.
Set to `{}` to enable with defaults.

| Field            | Required | Type    | Description                                                              | Default Value |
|------------------|----------|---------|--------------------------------------------------------------------------|---------------|
| `add_attachment` | No       | Boolean | Expose `internal_representation_add_attachment` (promote any URL into the answer's attachments) | `true`        |

```json
{
  "features": {
    "representation_tooling": {
      "add_attachment": true
    }
  }
}
```

### Skills configuration

Optional top-level `skills` array. Merged with predefined skills at request time. See
[docs/skills.md](./skills.md) for behaviour, precedence, and skill invocation.

| Type          | Preview | Fields | Description |
|---------------|---------|--------|-------------|
| `dial-prompt` | No      | `url`  | DIAL prompt as a skill (`prompts/<bucket>/<path>`). |
| `dial-skill`  | **Yes** | `url`  | DIAL skill resource folder with `SKILL.md` (`skills/<bucket>/<path>`). Requires `ENABLE_PREVIEW_FEATURES=true` and DIAL Core ≥ 0.48.0. |

```json
{
  "skills": [
    { "type": "dial-prompt", "url": "prompts/public/my-prompt" },
    { "type": "dial-skill", "url": "skills/public/my-skill" }
  ]
}
```

### Hooks configuration

Requires `ENABLE_PREVIEW_FEATURES=true`. Top-level `hooks` array injects synthetic tool-call pairs
at named orchestrator seams. See
[docs/designs/config_driven_hooks.md](docs/designs/config_driven_hooks.md).

| Field              | Required | Type   | Description | Default |
|--------------------|----------|--------|-------------|---------|
| `kind`             | Yes      | String | Only `"tool_call"` today | - |
| `event`            | Yes      | String | Only `"on_request_start"` wired today | - |
| `toolset_name`     | No       | String | Prefix for REST/MCP tools; omit for DIAL deployment / internal | `null` |
| `tool_name`        | Yes      | String | Tool name within the toolset (or exact function name) | - |
| `arguments`        | No       | Object | Arguments forwarded to the tool | `{}` |
| `frequency`        | No       | String | `"always"` or `"append_if_changed"` | `append_if_changed` |
| `name`             | No       | String | Optional hook label | `null` |
| `refresh_condition`| No       | Object | Optional TTL refresh (`{"kind":"ttl","ttl_minutes":N}`) | `null` |

### Tool defaults configuration

| Field              | Required | Type            | Description | Default |
|--------------------|----------|-----------------|-------------|---------|
| `timeout_seconds`  | No       | Number or null  | Timeout for all tool calls in this app (`> 0`, `≤ 3600`). `null` defers to env `DEFAULT_TOOL_TIMEOUT_SECONDS`, then client library defaults. | `null` |

```json
{
  "tool_defaults": {
    "timeout_seconds": 60
  }
}
```

### Conversation starters configuration

Top-level `conversation_starters` configures the starter chips shown in Chat before the first
message.

| Field                         | Required | Type    | Description | Default |
|-------------------------------|----------|---------|-------------|---------|
| `intro_text`                  | No       | String  | Text above the starter buttons | `"Select an action"` |
| `chat_message_input_disabled` | No       | Boolean | If `true`, users can only start via starter buttons (input disabled) | `false` |
| `auto_submit`                 | No       | Boolean | If `true`, clicking a starter sends immediately; if `false`, text is only filled into the input | `true` |
| `starters`                    | Yes      | Array   | Non-empty list of `{ "title", "text" }` chips | - |

```json
{
  "conversation_starters": {
    "intro_text": "Pick a starting point",
    "auto_submit": true,
    "starters": [
      { "title": "Summarize", "text": "Summarize the attached document." },
      { "title": "Translate", "text": "Translate the last user message to English." }
    ]
  }
}
```

> **Deprecated:** top-level `starters: ["…"]` (string list) is still accepted but will be removed.
> Migrate to `conversation_starters`.

### Localized toolset names and descriptions

Toolset `name` and `description` accept either a plain string or a locale map
`{"en": "…", "ru": "…"}`. Resolution uses the incoming `Accept-Language` header (or the header
named by `PROXY_LANGUAGE_HEADER`), falling back to `en`, then any map entry. The generated app
schema advertises `dial:defaultLocale` so the Chat configurator can offer locale-aware inputs.

### Tool sets configuration

Most toolset types also accept a `deferred` field (Boolean, default `true`): `[Preview]` when true or unset, and
[Tool discovery configuration](#tool-discovery-configuration) is enabled, the toolset's tool schemas are withheld
from the initial LLM payload and discovered on demand via the `internal_tool_search` meta-tool. Set to `false` to
keep a specific toolset always eager. Currently honored by REST API, MCP, and Internal toolsets; DIAL deployment and
DIAL app toolsets accept the field but do not yet act on it.

#### RestApiToolSet Configuration

| Field         | Required | Type                                                                                                                                                                                                | Description                               | Default Value |
|---------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------|---------------|
| name          | Yes      | String or locale map (`{"en":"…","ru":"…"}`)                                                                                                                                                              | Toolset name. Plain string or localized map; see [Localized toolset names](#localized-toolset-names-and-descriptions). | -             |
| description   | No       | String or locale map                                                                                                                                                                                    | Toolset description (same localization rules as `name`).          | `null`        |
| enabled       | No       | Boolean                                                                                                                                                                                             | Whether the toolset is enabled.           | `true`        |
| type          | Yes      | String                                                                                                                                                                                              | The type of the tool set.                 | `rest-api`    |
| authorization | No       | One of `BasicAuthorization`, `BearerAuthorization`, <br/>`ClientIdSecretAuthorization`, `ApiKeyAuthorization`, `null`</br> <br>See [Authorization configuration](#authorization-configuration)</br> | Authorization configuration for REST API. | `null`        |
| tools         | Yes      | Array of `RestApiTool` or `PredefinedToot`                                                                                                                                                          | List of REST API tool configurations.     | -             |

#### DialDeploymentToolSet Configuration

| Field       | Required | Type                                              | Description                                  | Default Value     |
|-------------|----------|---------------------------------------------------|----------------------------------------------|-------------------|
| name        | Yes      | String                                            | The name of the tool set.                    | -                 |
| description | No       | String                                            | The description of the tool set.             | `null`            |
| enabled     | No       | Boolean                                           | Whether the toolset is enabled.              | `true`            |
| type        | Yes      | String                                            | The type of the tool set.                    | `dial-deployment` |
| tools       | Yes      | Array of `DialDeploymentTool` or `PredefinedTool` | List of DIAL deployment tool configurations. | -                 |

#### PredefinedToolSet Configuration

| Field         | Required | Type           | Description                                                                                                                                                                                                              | Default Value |
|---------------|----------|----------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------|
| type          | Yes      | String         | The type of the tool set.                                                                                                                                                                                                | `predefined`  |
| template_name | Yes      | String         | Name of the predefined template.                                                                                                                                                                                         | -             |
| override      | No       | Object         | Optional JSON Merge Patch (RFC 7396) applied to the resolved toolset template before validation. Patches must not target the `type` discriminator at any depth. See [docs/chathub.md](./chathub.md) for ChatHub recipes. | `null`        |

#### PredefinedTool Configuration

| Field         | Required | Type           | Description                                                                                                                                                                                                            | Default Value     |
|---------------|----------|----------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------|
| type          | Yes      | String         | The type indicating this is a tool template reference.                                                                                                                                                                 | `predefined-tool` |
| template_name | Yes      | String         | The name of the tool template file (without extension).                                                                                                                                                                | -                 |
| enabled       | No       | Boolean        | Whether the tool is enabled.                                                                                                                                                                                           | `true`            |
| override      | No       | Object         | Optional JSON Merge Patch (RFC 7396) applied to the resolved tool template before validation. Patches must not target the `type` discriminator at any depth. See [docs/chathub.md](./chathub.md) for ChatHub recipes. | `null`            |

#### MCPToolSet Configuration

| Field                  | Required | Type               | Description                                                              | Default Value |
|------------------------|----------|--------------------|--------------------------------------------------------------------------|---------------|
| name                   | Yes      | String             | The name of the tool set.                                                | -             |
| description            | No       | String             | The description of the tool set.                                         | `null`        |
| enabled                | No       | Boolean            | Whether the toolset is enabled.                                          | `true`        |
| type                   | Yes      | String             | The type of the tool set.                                                | `mcp`         |
| mcp_server_info        | Yes      | MCPServerInfo      | MCP server info. See [MCPServerInfo structure](#mcpserverinfo-structure) | -             |
| allowed_tools          | No       | Array of String    | Allowed MCP tool names from the server                                   | `null`        |
| resources              | No       | MCPResourcesConfig | MCP resource exposure config. See [MCP resources configuration](#mcp-resources-configuration). | `null` (disabled) |
| attachment             | No       | AttachmentConfig   | See also: [AttachmentConfig](#attachment-configuration)                  | -             |
| fallback_configuration | No       | ToolFallbackConfig | See also: [Tool fallback configuration](#tool-fallback-configuration)    | -             |

##### MCPServerInfo structure:

| Field         | Required | Type                                                                                                                                                                                                   | Description           | Default Value |
|---------------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------|---------------|
| url           | Yes      | String                                                                                                                                                                                                 | URL of the MCP server | -             |
| protocol      | Yes      | one of the String `sse` or `streamable_http`                                                                                                                                                           | Protocol              | -             |
| authorization | No       | One of `BearerAuthorization`, `MCPApiKeyAuthorization`, <br/>`ClientIdSecretAuthorization`, `BasicAuthorization`, `null`</br> <br>See [Authorization configuration](#authorization-configuration)</br> | Authorization         | -             |

#### DialMCPToolSet Configuration

| Field                  | Required | Type                   | Description                                                           | Default Value |
|------------------------|----------|------------------------|-----------------------------------------------------------------------|---------------|
| name                   | Yes      | String                 | The name of the tool set.                                             | -             |
| description            | No       | String                 | The description of the tool set.                                      | `null`        |
| enabled                | No       | Boolean                | Whether the toolset is enabled.                                       | `true`        |
| type                   | Yes      | String                 | The type of the tool set.                                             | `dial-mcp`    |
| dial_id                | Yes      | String                 | The Dial ID associated with this MCP toolset.                         | -             |
| transport              | Yes      | String `HTTP` or `SSE` | MCP protocol                                                          | `HTTP`        |
| allowed_tools          | No       | Array of String        | Allowed MCP tool names from the server                                | `null`        |
| resources              | No       | MCPResourcesConfig     | MCP resource exposure config. See [MCP resources configuration](#mcp-resources-configuration). | `null` (disabled) |
| attachment             | No       | AttachmentConfig       | See also: [AttachmentConfig](#attachment-configuration)               | -             |
| fallback_configuration | No       | ToolFallbackConfig     | See also: [Tool fallback configuration](#tool-fallback-configuration) | -             |

#### DialAppToolSet Configuration

Use `DialAppToolSet` to reference a DIAL application or deployment by its id and have QuickApps choose the
transport automatically at initialization time. If the deployment advertises MCP (`features.mcp == true`),
**all** MCP tools it publishes are surfaced as first-class QuickApp tools over the path
`/v1/toolset/{deployment_id}/mcp` (current DIAL Core behaviour; this will move to
`/v1/deployments/{deployment_id}/mcp` once the matching DIAL Core change ships). Otherwise the toolset
falls back to the existing chat-completion path (single synthetic `query` tool per deployment), matching
`DialDeploymentSimpleTool` behaviour.

This differs from `DialMCPToolSet` semantically: `DialMCPToolSet` points at a DIAL *toolset* resource
(identified by `dial_id`), while `DialAppToolSet` points at a DIAL *deployment/application* (identified by
`deployment_id`). Both currently hit the same `/v1/toolset/{id}/mcp` path prefix in DIAL Core, but the ids
have different semantics and will diverge once the deployment-scoped endpoint lands.

| Field                  | Required | Type               | Description                                                                                                                                                                                | Default Value |
|------------------------|----------|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------|
| name                   | Yes      | String             | The name of the tool set. Used as the tool-name prefix on the MCP branch; on the chat-completion fallback branch the synthetic tool name is derived from the deployment id, so this field has no effect on the agent-visible name. | -             |
| description            | No       | String             | The description of the tool set.                                                                                                                                                           | `null`        |
| enabled                | No       | Boolean            | Whether the toolset is enabled.                                                                                                                                                            | `true`        |
| type                   | Yes      | String             | The type of the tool set.                                                                                                                                                                  | `dial-app`    |
| deployment_id          | Yes      | String             | The DIAL deployment or application id.                                                                                                                                                     | -             |
| transport              | No       | One of `auto`, `mcp`, `chat-completion` | Routing override. `auto` (default): MCP if the deployment advertises `features.mcp`, otherwise chat completion. `mcp`: force MCP — initialization fails if `features.mcp` is not advertised. `chat-completion`: force chat completion — metadata fetch is skipped. | `auto`        |
| allowed_tools          | No       | Array of String    | MCP branch only: whitelist the subset of MCP tool names that reach the agent. Ignored (with a warning) on the chat-completion fallback branch.                                             | `null`        |
| attachment             | No       | AttachmentConfig   | Propagated on both branches. See also: [AttachmentConfig](#attachment-configuration)                                                                                                       | -             |
| fallback_configuration | No       | ToolFallbackConfig | Propagated on both branches. See also: [Tool fallback configuration](#tool-fallback-configuration)                                                                                         | -             |
| conversation_mode      | No       | Object             | Resumable conversation for the **chat-completion** branch only; ignored (with a warning) on MCP. See [Conversation mode](#conversation-mode)                                              | `null`        |

#### MCP resources configuration

Applies to both `MCPToolSet` and `DialMCPToolSet`. Disabled (`null`) by default.

| Field   | Required | Type                        | Description                                                                                                                                                              | Default Value |
|---------|----------|-----------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------|
| enabled | No       | Boolean                     | Whether to expose MCP resources from this toolset to the agent.                                                                                                         | `false`       |
| items   | No       | Array of `MCPResourceConfig` or null | Resources to expose. `null` = expose all resources the server declares (all lazy). Provide a list to restrict to specific URIs and/or mark some as eager.  | `null`        |

##### MCPResourceConfig structure

| Field  | Required | Type    | Description                                                                                                                                                                             | Default Value |
|--------|----------|---------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------|
| uri    | Yes      | String  | URI of the resource as declared by the MCP server.                                                                                                                                      | -             |
| eager  | No       | Boolean | Pre-fetch this resource at init time and inject its content as a synthetic `read_mcp_resource` tool call pair before the first LLM invocation. Useful for small reference documents that the model should always have in context. | `false` |

When `enabled` is `true`:

- Each declared resource gets a **card** in the system prompt (name, URI, MIME type, description) so the LLM knows what is available.
- A built-in `read_mcp_resource` tool is registered, allowing the LLM to fetch resource content on demand.
- Resources marked `eager: true` are fetched at startup and their content is injected automatically — the LLM receives them without needing to call the tool explicitly. On subsequent turns the injection is skipped so the same resource is not duplicated in the conversation history.

<details>
<summary><b>MCP resources configuration JSON sample</b></summary>

Expose all resources the server declares (lazy, fetched on demand):

```json
{
  "type": "mcp",
  "name": "my-toolset",
  "mcp_server_info": { "url": "https://example.com/mcp", "protocol": "streamable_http" },
  "resources": { "enabled": true }
}
```

Expose only specific resources, one pre-loaded eagerly:

```json
{
  "type": "mcp",
  "name": "my-toolset",
  "mcp_server_info": { "url": "https://example.com/mcp", "protocol": "streamable_http" },
  "resources": {
    "enabled": true,
    "items": [
      { "uri": "urn://docs/intro", "eager": true },
      { "uri": "urn://docs/api-reference" }
    ]
  }
}
```

</details>

#### InternalToolSet Configuration

| Field       | Required | Type                                        | Description                      | Default Value |
|-------------|----------|---------------------------------------------|----------------------------------|---------------|
| name        | Yes      | String                                      | The name of the tool set.        | -             |
| description | No       | String                                      | The description of the tool set. | `null`        |
| enabled     | No       | Boolean                                     | Whether the toolset is enabled.  | `true`        |
| type        | Yes      | String                                      | The type of the tool set.        | `internal`    |
| tools       | Yes      | Array of `InternalTool` or `PredefinedTool` | Tools with their configurations. | -             |

#### Authorization configuration

##### BasicAuthorization

| Field    | Required | Type           |
|----------|----------|----------------|
| type     | Yes      | String `basic` |
| username | Yes      | String         |
| password | Yes      | Boolean        |

##### BearerAuthorization

| Field | Required | Type            |
|-------|----------|-----------------|
| type  | Yes      | String `bearer` |
| token | Yes      | String          |

##### ClientIdSecretAuthorization

| Field         | Required | Type                      | Description      |
|---------------|----------|---------------------------|------------------|
| type          | Yes      | String `client_id_secret` | Type of the auth |
| client_id     | Yes      | String                    | client id        |
| client_secret | Yes      | String                    | client secret    |
| token_url     | Yes      | String                    | token url        |
| scope         | No       | Array of String           | scope list       |
| aud           | No       | Array of String           | aud list         |

##### ApiKeyAuthorization

| Field    | Required | Type                           | Description                        |
|----------|----------|--------------------------------|------------------------------------|
| type     | Yes      | String `api_key`               | Type of the auth                   |
| key      | Yes      | String                         | client id                          |
| name     | Yes      | String                         | name of the api key param          |
| location | Yes      | Enum `header`, `query`, `body` | location of the api key in request |

##### MCPApiKeyAuthorization

The same as ApiKeyAuthorization but for mcp location is not configurable and always is `header`.

| Field | Required | Type             | Description               |
|-------|----------|------------------|---------------------------|
| type  | Yes      | String `api_key` | Type of the auth          |
| key   | Yes      | String           | client id                 |
| name  | Yes      | String           | name of the api key param |

### Tool configuration

| Field                  | Required                             | Type   | Description                                                                                                                                                                               | Available Values | Default Value |
|------------------------|--------------------------------------|--------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------|---------------|
| open_ai_tool           | Yes                                  | Object | Extended OpenAI Spec configuration for tool. See [Expended Open AI configuration](#open-ai-tool-configuration)                                                                            | -                | -             |
| attachment             | No                                   | Object | Tool attachments configuration. See [Attachment configuration](#attachment-configuration)                                                                                                 | -                | `null`        |
| deployment             | Yes (if `type` is `dial-deployment`) | Object | The DIAL deployment configuration. See [Deployment configuration](#deployment-configuration)                                                                                              | -                | -             |
| rest_api_method_info   | Yes (if `type` is `rest-api`)        | Object | REST API method information configuration. See [REST API method information configuration](#rest-api-method-information-configuration)                                                    | -                | -             |
| display                | No                                   | Object | Representation (display) configuration for tool execution results. See [Display configuration](#display-configuration), See [Tool stage configuration](#display-tool-stage-configuration) | -                | `null`        |
| fallback_configuration | No                                   | Object | Tools fallback configuration. If not present will always raise Error. See [Tool fallback configuration](#tool-fallback-configuration)                                                     | -                | `null`        |
| propagate_annotations_to_choice | No                          | Boolean | **Preview.** Only for `deployment-tool` and `dial-deployment-simple`. Propagate citation annotations returned by the deployment to the app's answer. See [Citation annotations](#citation-annotations)               | `true`, `false`  | `null`        |
| conversation_mode               | No                          | Object  | Resumable subagent conversation. Applies to `deployment-tool`, `dial-deployment-simple`, and `dial-app` (chat-completion branch only). See [Conversation mode](#conversation-mode) | - | `null` |
| content_propagation             | No                          | Object  | Header / **deprecated** history propagation. Prefer `conversation_mode`. See [Content propagation](#content-propagation-deprecated-history-flag) | - | `null` |

#### Conversation mode

When `conversation_mode.resumable` is `true`, the deployment tool issues a `session_id` on the
first call, accepts it on follow-ups, and the backend threads prior `[user, assistant]` history
(including the subagent's internal tool-execution state) for that session. When `false` or omitted,
each call is independent.

| Field       | Required | Type    | Description | Default |
|-------------|----------|---------|-------------|---------|
| `resumable` | No       | Boolean | Enable resumable subagent conversations | `false` |

Runtime details when `resumable` is `true`:

- The tool schema gains an optional `session_id` argument (not forwarded to the subagent).
- On the first call the backend assigns `session_id` from the tool-call id and appends
  `[session_id: …]` to the tool result so the orchestrator can reuse it.
- Follow-up calls should pass that `session_id` back; omitting it falls back to tool-name-only
  history matching (same pooling behaviour as the old `propagate_history` path).

```json
{
  "type": "deployment-tool",
  "deployment": { "deployment_id": "my-subagent" },
  "conversation_mode": { "resumable": true }
}
```

On `dial-app` toolsets, `conversation_mode` applies only when the toolset resolves to the
chat-completion branch; it is ignored (with a warning) on the MCP branch.

#### Content propagation (deprecated history flag)

| Field               | Required | Type          | Description | Default |
|---------------------|----------|---------------|-------------|---------|
| `propagate_history` | No       | Boolean       | **Deprecated.** Use `conversation_mode.resumable: true`. Still accepted; will be removed in a future release. | `false` |
| `propagate_headers` | No       | Array[String] | Headers to propagate to the DIAL deployment; `null` uses defaults | `null` |

#### Citation annotations

A DIAL application used as a deployment tool can return citation annotations under
`choices[].delta.custom_fields.annotations`, with in-text `<cit data-id="..."></cit>` anchors in its answer
text. Set `propagate_annotations_to_choice: true` on that tool to forward them to your app's answer.

Annotations are forwarded exactly as the deployment returned them. When any tool enables the flag,
the orchestrator is additionally instructed to copy every `<cit data-id="..."></cit>` anchor verbatim from tool
responses into its own answer, so the anchors the annotations point at stay in the text.

This is a preview feature: it requires `ENABLE_PREVIEW_FEATURES=true`, and DIAL Chat does not
render annotations yet.

```json
{
  "type": "dial-deployment-simple",
  "deployment_id": "dial-document",
  "propagate_annotations_to_choice": true
}
```

#### REST API method information configuration

| Field       | Required | Type                                       | Description |
|-------------|----------|--------------------------------------------|-------------|
| method_url  | Yes      | String                                     | url         |
| method_type | Yes      | String Enum `get`, `post`, `put`, `delete` | method      |

#### Open AI tool configuration

| Field    | Required | Type   | Description                                                                                                        | Available Values | Default Value |
|----------|----------|--------|--------------------------------------------------------------------------------------------------------------------|------------------|---------------|
| type     | No       | String | Will be set as `function` by default. Required, according to DIAL spec                                             | -                | `function`    |
| function | Yes      | Object | Extended version of function from DIAL spec. See [Open AI function configuration](#open-ai-function-configuration) | -                | -             |

<details>
<summary><b>Open AI tool configuration JSON sample</b></summary>

```json
{
  "type": "function",
  "function": {
    "name": "rag_search_tool",
    "description": "Performs RAG search in text files and returns llm answer based on the search.Always used when user asks for information from attached files.Can perform search in multiple attachments.",
    "parameters": {
      "type": "object",
      "properties": {
        "prompt": {
          "type": "string",
          "description": "RAG search prompt"
        },
        "attachment_urls": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "List of attachment names for RAG search. If not 100% confident which attachment to use - do not provide this parameter at all."
        }
      },
      "required": [
        "prompt",
        "attachment_urls"
      ]
    }
  }
}
```

</details>

## Open AI function configuration

[See Dial Function parameters](https://dialx.ai/dial_api#operation/sendChatCompletionRequest)

| Field       | Required | Type   | Description                                                                                                                 | Available Values | Default Value |
|-------------|----------|--------|-----------------------------------------------------------------------------------------------------------------------------|------------------|---------------|
| name        | Yes      | String | Unique self-descriptive name that will be used by Agent to call tool                                                        | -                | -             |
| description | Yes      | String | Description (prompt), that will be used by Agent to distinguish where to use this particular tool. Max length is 1024 chars | -                | -             |
| parameters  | Yes      | Object | Extended version of Open AI JSON schema tool parameters. See [Parameters configuration](#parameters-configuration)          | -                | -             |

## Parameters configuration

| Field      | Required | Type          | Description                                                                                                       | Available Values | Default Value |
|------------|----------|---------------|-------------------------------------------------------------------------------------------------------------------|------------------|---------------|
| type       | No       | String        | Will be set as `object` by default. Required, according to DIAL spec                                              | -                | `object`      |
| properties | No       | Object        | Mixin of tool properties and additional configurations. See [Properties configuration](#properties-configuration) | -                | `{}`          |
| required   | Yes      | Array[Object] | Here can be listed the properties names that are required when Agent will call a tool                             | -                | -             |

<details>
<summary><b>Parameters configuration JSON sample</b></summary>

Original Open AI parameters configuration

```json
{
  "parameters": {
    "type": "object",
    "properties": {
      "prompt": {
        "type": "string",
        "description": "RAG search prompt"
      },
      "attachment_urls": {
        "type": "array",
        "items": {
          "type": "string"
        },
        "description": "List of attachment names for RAG search. If not 100% confident which attachment to use - do not provide this parameter at all."
      }
    },
    "required": [
      "prompt",
      "attachment_urls"
    ]
  }
}
```

Mixin of Open AI and QuickApp parameters configuration

```json
{
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "RAG search prompt",
        "display": {
          "stage": {
            "name": "Prompt",
            "show_value_in_stage_title": true
          }
        }
      },
      "attachment_urls": {
        "type": "array",
        "items": {
          "type": "string"
        },
        "description": "List of attachment names for RAG search. If not 100% confident which attachment to use - do not provide this parameter at all.",
        "display": {
          "stage": {
            "ignore": true
          }
        },
        "parameter_info": {
          "key": "attachments",
          "type": "body"
        }
      }
    },
    "required": [
      "query",
      "attachment_urls"
    ]
  }
}

```

</details>

## Properties configuration

| Field    | Required | Type   | Description                                                                                                                                        | Available Values | Default Value |
|----------|----------|--------|----------------------------------------------------------------------------------------------------------------------------------------------------|------------------|---------------|
| `{name}` | Yes      | Object | `{name}` is self-descriptive property name (`{name}` should be replaced with property name). See [Property configuration](#property-configuration) | -                | -             |

## Property configuration

More detailed for default parameters [JSON Schema spec](https://json-schema.org/understanding-json-schema/reference)

| Field          | Required                           | Custom | Type          | Description                                                                                                                                                                                                 | Available Values                                                             | Default Value |
|----------------|------------------------------------|--------|---------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|---------------|
| type           | Yes                                | No     | String        | Property type. See                                                                                                                                                                                          | `object`, `array`, `string`, `number`, `integer`, `boolean`, `null`, `const` | -             |
| description    | Yes                                | No     | String        | Description that will help Agent to understand what values should be passed. Max length is 1024 chars                                                                                                       | -                                                                            | -             |
| items          | Yes (if `type` is `array`)         | No     | Object        | Here can be passed types that array can apply                                                                                                                                                               | `object`, `array`, `string`, `number`, `integer`, `boolean`, `null`, `const` | -             |
| required       | Yes (if `type` is `object`)        | No     | Array[Object] | Here can be listed the properties names that are required when Agent will call a tool                                                                                                                       | -                                                                            | -             |
| display        | No                                 | Yes    | Object        | Representation (display) configuration for tool execution results. See [Display configuration](#display-configuration), See [Display parameter stage configuration](#display-parameter-stage-configuration) | -                                                                            | -             |
| parameter_info | Yes (only for `rest-api` toolsets) | Yes    | Object        | Additional information about the parameter. See [Parameter info configuration](#parameter-info-configuration)                                                                                               | -                                                                            | -             |

## Display configuration

| Field | Required | Type   | Description                                                                                                                                                                                                                            | Default Value |
|-------|----------|--------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------|
| stage | No       | Object | Representation of tool execution results and parameter values in stage. See [Display tool stage configuration](#display-tool-stage-configuration), See [Display parameter stage configuration](#display-parameter-stage-configuration) | -             |

## Display tool stage configuration

| Field | Required | Type    | Description                                                                    | Available Values | Default Value |
|-------|----------|---------|--------------------------------------------------------------------------------|------------------|---------------|
| name  | No       | String  | The tool name that will be used as title for stage                             | -                | `null`        |
| show  | No       | Boolean | Whether to show stage (and tools execution results) when tool is called or not | `true`, `false`  | `true`        |

<details>
<summary><b>Display tool stage configuration JSON sample</b></summary>

Show stage with name `RAG search: `

```json
{
  "display": {
    "stage": {
      "name": "RAG search: "
    }
  }
}
```

Do not show tool execution in stage

```json
{
  "display": {
    "stage": {
      "show": false
    }
  }
}
```

</details>

## Display parameter stage configuration

| Field                     | Required | Type    | Description                                                                                                                                                                     | Available Values                     | Default Value |
|---------------------------|----------|---------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------|---------------|
| ignore                    | No       | Boolean | Whether to show parameter with value in the stage content. If `false` the parameter and its value will be ignored                                                               | `true`, `false`                      | `false`       |
| show_value_in_stage_title | No       | Boolean | Whether to show parameter value in the stage title. Useful, when need to make a brief overview of what the Agent is trying to when call a tool                                  | `true`, `false`                      | `false`       |
| name                      | No       | String  | If present then will be used instead of original name, otherwise will be used original name                                                                                     | -                                    | `null`        |
| prefix                    | No       | String  | The prefix to be added after parameter name and before parameter value                                                                                                          | -                                    | `null`        |
| suffix                    | No       | String  | The suffix to be added after parameter value                                                                                                                                    | -                                    | `null`        |
| replaced_value_info       | No       | String  | The replaced parameter value that will shown in the stage content. If `null` then will be used original value. If replacement is used the `prefix` and `suffix` will be ignored | -                                    | `null`        |
| format                    | No       | String  | The format of the parameter value. If present then the value will be wrapped in ```{format} {parameter value}```                                                                | `markdown`, `python`, `json`, etc... | `null`        |

<details>
<summary><b>Display parameter stage configuration JSON sample</b></summary>

Configuration sample:

```json
{
  "display": {
    "stage": {
      "name": "Prompt",
      "show_value_in_stage_title": true,
      "prefix": "Before value...",
      "suffix": "... After value.",
      "format": "text"
    }
  }
}
```

Configuration sample with replaced value:

```json
{
  "display": {
    "stage": {
      "name": "**Open session:** ",
      "replaced_value_info": "**New session will be opened!**"
    }
  }
}
```

Do not show parameter with value in stage while tool call:

```json
{
  "display": {
    "stage": {
      "ignore": true
    }
  }
}
```

</details>

## Parameter info configuration

| Field | Required | Type   | Description                                                       | Available Values                 | Default Value |
|-------|----------|--------|-------------------------------------------------------------------|----------------------------------|---------------|
| type  | Yes      | String | The element type of REST request                                  | `query`, `url`, `body`, `header` | -             |
| key   | Yes      | String | Name of the element in request [`query`, `url`, `body`, `header`] | -                                | -             |

<details>
<summary><b>Parameter info configuration JSON sample</b></summary>

```json
{
  "parameter_info": {
    "key": "attachments",
    "type": "body"
  }
}
```

</details>

## Attachment configuration

| Field                     | Required | Type          | Description                                                                                                          | Available Values                             | Default Value |
|---------------------------|----------|---------------|----------------------------------------------------------------------------------------------------------------------|----------------------------------------------|---------------|
| supported_types           | No       | Array[String] | List of supported attachment MIME types                                                                              | `*/*`(all), `image/png`, `image/jpeg`, etc.. | `[*/*]`       |
| propagate_types_to_choice | No       | Array[String] | List of supported attachment MIME types that will be shown in main chat (propagated from tool call result to choice) | `*/*`(all), `image/png`, `image/jpeg`, etc.. | `[]`          |
| media_type_substitution   | No       | dict[str, str] | Maps original MIME type to substitute. Key is a original mime_type, value is desired mime type. | `*/*`(all), `image/png`, `image/jpeg`, etc.. | `{}` |

<details>
<summary><b>Parameter info configuration JSON sample</b></summary>

```json
{
  "supported_types": [
    "*/*"
  ],
  "propagate_types_to_choice": [
    "image/png",
    "image/jpeg",
    "application/vnd.plotly.v1+json"
  ],
  "media_type_substitution": {
    "application/json": "application/vnd.plotly.v1+json"
  }
}
```

</details>

## Tool Fallback Configuration

The `fallback_configuration` field allows you to define strategies for handling tool execution errors.

### `ToolFallbackConfig` Structure

| Field                  | Required | Type                 | Description                          | Available Values          | Default Value |
|------------------------|----------|----------------------|--------------------------------------|---------------------------|---------------|
| strategies             | Yes      | Array[StrategyModel] | List of fallback handling strategies | See strategy models below | `[{"type": "continue"}]` |
| display_error_in_stage | No       | Boolean              | Whether to show the exception text in the tool stage (vs a generic error notification). Timeouts always show the error text. | `true`, `false` | `true` |

### Strategy Models

1. **HardStopStrategyModel** (`type: hard_stop`) — Terminates the agent loop. `FallbackAgentStopException`
   propagates through the orchestrator and the user receives a generic "agent was stopped" message.
   No content is sent to the LLM.
2. **ContinueStrategyModel** (`type: continue`) — The agent continues execution. The actual tool
   error text is **always** forwarded to the LLM as the tool-result content. Optionally appends
   `instructions` when a `trigger_on` condition matches. Catch-all strategies (`trigger_on` omitted)
   ignore `instructions` — only the error text is sent.

> **Deprecated:** `type: stop` is a deprecated alias for `type: hard_stop` (same halt behaviour).
> Replace with `type: hard_stop`; a warning is logged at runtime.
>
> **Deprecated:** `type: retry` is a deprecated alias for `type: continue` and behaves identically.
> Replace with `type: continue`; a warning is logged at runtime.

### Common Strategy Fields

| Field        | Required | Type                      | Description                                                                                                             | Default Value                         |
|--------------|----------|---------------------------|-------------------------------------------------------------------------------------------------------------------------|---------------------------------------|
| type         | Yes      | Enum `hard_stop` or `continue` (plus deprecated `stop`, `retry`) | The type of the strategy                                                                                |                                       |
| trigger_on   | No       | Object                    | Condition that triggers this strategy                                                                                   | triggers on all exceptions (catch-all) |
| instructions | No       | String                    | Additional instructions appended to the error text when this strategy matches via `trigger_on`. Ignored on catch-all (`trigger_on` omitted). | —                                     |

> **Deprecated:** `forward_tool_error_message` is a no-op. The tool error message is now always
> forwarded to the LLM. Remove this field from your configs; it is ignored at runtime and a warning
> is logged when it is set to `true`.

### `TriggerOn` Structure

| Field          | Required | Type                       | Description                               | Default Value |
|----------------|----------|----------------------------|-------------------------------------------|---------------|
| type           | Yes      | Enum  "contains", "equals" | The type of matching to perform           | -             |
| value          | Yes      | String                     | The error message text to match against   | -             |
| case_sensitive | No       | Boolean                    | Whether matching should be case-sensitive | `false`       |

<details>
<summary><b>Example Of Strategies Configuration</b></summary>

```json
{
  "fallback_configuration": {
    "display_error_in_stage": true,
    "strategies": [
      {
        "type": "hard_stop",
        "trigger_on": {
          "type": "contains",
          "value": "quota exceeded",
          "case_sensitive": false
        }
      },
      {
        "type": "continue",
        "trigger_on": {
          "type": "contains",
          "value": "rate limit",
          "case_sensitive": false
        },
        "instructions": "Wait a moment and retry with a smaller request."
      },
      {
        "type": "continue"
      }
    ]
  }
}
```

The first strategy terminates the agent loop on a quota error. The second strategy forwards the
rate-limit error text to the LLM with additional instructions. The final catch-all forwards any
other error text as-is.

</details>

### Behavior Notes

- If no fallback configuration is provided, the default behaviour is to forward the error text to
  the LLM and continue (`ContinueStrategyModel` catch-all).
- Strategies are evaluated in the order they appear in the array. The first matching strategy is used.
- A `hard_stop` (or deprecated `stop`) strategy raises `FallbackAgentStopException`, which terminates
  the agent loop immediately. The LLM does not receive any tool-result content for that call; the
  user sees a generic "agent was stopped" message.
- A `continue` strategy always forwards the actual tool error text to the LLM as the tool-result
  content. When `trigger_on` matches and `instructions` is set, the instructions are appended
  after the error text.
- `instructions` on a catch-all strategy (no `trigger_on`) are **deprecated and ignored**. A
  warning is logged at startup when such a configuration is detected. To preserve instruction
  injection, add a `trigger_on` matcher.
- For `ToolTimeoutError`, implicit catch-all strategies are skipped and a built-in timeout message
  is used instead. Explicit `trigger_on: contains("timed out")` strategies still pre-empt the
  built-in. See [Configurable Tool Timeouts](docs/designs/configurable_timeouts.md).

## Forwarding headers

Incoming request headers whose names start with `X-` (case-insensitive) are automatically forwarded to all outbound
calls made during that chat completion. No configuration is required.

- **Orchestrator (Azure OpenAI):** forwarded headers are sent on each chat completion request.
- **MCP tools:** forwarded headers are merged into the HTTP/SSE headers used when connecting to MCP servers.
- **DIAL deployment tools:** forwarded headers are sent as `extra_headers` when calling DIAL chat completions.
- **REST API tools:** forwarded headers are merged into the outgoing HTTP request headers.

Use this for tracing (e.g. `X-Request-Id`, `X-Correlation-Id`), multi-tenancy (`X-Tenant-Id`), or any custom header
your gateways or downstream services expect.

## Environment Variables

| Variable                                   | Default                                                         | Required | Description                                                                                                  |
|--------------------------------------------|-----------------------------------------------------------------|----------|----------------------------------------------------------------------------------------------------------------|
| **DIAL Core**                              |                                                                 |          |                                                                                                              |
| `DIAL_URL`                                 | —                                                               | Yes      | URL of the DIAL Core API                                                                                     |
| `DIAL_API_VERSION`                         | `2025-01-01-preview`                                            | No       | API version for DIAL Core API                                                                                |
| `APP_SCHEMA_ID`                            | `https://mydial.epam.com/custom_application_schemas/quickapps2` | No | Full application type schema `$id` emitted in the generated app schema. When unset, the built-in default is used. |
| `DIAL_INTERACTIVE_LOGIN_TIMEOUT_SECONDS`   | `120.0`                                                         | No       | Wall-clock timeout (seconds) waiting for the user to complete interactive sign-in when an MCP toolset returns 401 / an external-service sign-in challenge. See [docs/agent.md](./agent.md) (Interactive login). |
| **Proxy**                                  |                                                                 |          |                                                                                                              |
| `PROXY_LANGUAGE_HEADER`                    | `accept-language`                                               | No       | Name of the incoming HTTP request header that carries the locale for UI display (stage name localization). Override when a reverse proxy rewrites the standard `Accept-Language` header before forwarding the request. |
| **Logging**                                |                                                                 |          |                                                                                                              |
| `DIAL_SDK_LOG_FORMAT`                      | `text`                                                          | No       | Console log output format: `text` (human-readable) or `json` (escape-safe, one record per line). See [docs/logging.md](./logging.md). |
| `DIAL_SDK_TEXT_LOG_FORMAT`                 | [see docs/logging.md](./logging.md)                          | No | Custom `%`-style format string for `text` output. Unset (default) keeps the built-in format with the conditional OTEL trace block. |
| `DIAL_SDK_JSON_LOG_FORMAT`                 | [see docs/logging.md](./logging.md)                          | No | Custom template for `json` output — a JSON document whose string leaves are `%`-style format strings, values escaped via `json.dumps`. |
| `LOG_LEVEL`                                | `INFO`                                                          | No       | Root logger level (all loggers except quickapp)                                                              |
| `QUICKAPP_LOG_LEVEL`                       | `INFO`                                                          | No       | Log level for quickapp loggers                                                                               |
| `LOG_PAYLOADS`                             | `false`                                                         | No       | Emit payload content (message bodies, tool-call arguments, tool/LLM response bodies) at DEBUG. When `false`, no payload content is logged at **any** level and the payload-capable third-party loggers (`openai`/`httpx`/`httpcore`) are capped at INFO. **Local development only** — see [Payload Logging](#payload-logging). |
| `LOG_PAYLOADS_MAX_LENGTH`                  | `2000`                                                          | No       | Per-field character cap applied to each payload value when `LOG_PAYLOADS=true`; longer values are truncated. Inert when `LOG_PAYLOADS=false`. |
| **Agent**                                  |                                                                 |          |                                                                                                              |
| `DEFAULT_AGENT_MAX_ITERATIONS`             | `15`                                                            | No       | Maximum number of orchestrator iterations (`-1` for infinite)                                                |
| `DEFAULT_ORCHESTRATOR_DEPLOYMENT_ID`       | —                                                               | No       | Default DIAL deployment id used as the orchestrator model when a QuickApp manifest omits `orchestrator.deployment`. Also surfaces as the JSON-schema `default` for that field so DIAL Core can pre-fill new manifests. Apps can override per-app. |
| `SHOW_USAGE_STATISTICS`                    | `false`                                                         | No       | Include usage statistics in chat completion stream                                                           |
| `SHOW_EXECUTION_TIME_STAGE`                | `false`                                                         | No       | Show execution time stage in the UI                                                                          |
| **Python Interpreter**                     |                                                                 |          |                                                                                                              |
| `PY_INTERPRETER_LOCAL_RUN`                 | `false`                                                         | No       | Run PyInterpreter locally instead of via DIAL Core API                                                       |
| `PY_INTERPRETER_URL`                       | *(falls back to DIAL_URL)*                                      | No       | URL of the PyInterpreter service                                                                             |
| `PY_INTERPRETER_API_KEY`                   | —                                                               | No       | API key for local-run PyInterpreter                                                                          |
| `PY_INTERPRETER_DEFAULT_SESSION_ID`        | —                                                               | No       | Default session ID for the PyInterpreter                                                                     |
| `PY_INTERPRETER_CLIENT_MAX_RETRIES`        | `3`                                                             | No       | Max retries for PyInterpreter client requests                                                                |
| **Tool Timeouts**                          |                                                                 |          |                                                                                                              |
| `DEFAULT_TOOL_TIMEOUT_SECONDS`             | `300.0`                                                         | No       | Deployment-wide default timeout (seconds, `0 < x ≤ 3600`) applied to every tool call (deployment, REST API, MCP, Python interpreter). Apps can override per-app via `tool_defaults.timeout_seconds`. |
| `DEFAULT_FILE_LOADING_SIZE_LIMIT`          | `10485760`                                                      | No       | Deployment-wide default maximum size (in bytes) for files the agent downloads. Apps can override per-app via `features.file_loading.size_limit`. |
| **Stage Display**                          |                                                                 |          |                                                                                                              |
| `DEFAULT_STAGE_DISPLAY_LEVEL`              | —                                                               | No       | Deployment-wide override for stage visibility threshold (`none`, `error`, `info`, `debug`; case-insensitive). When set, wins over every app's `features.stage_display.level`. Unset (default) defers to the per-app config, which defaults to `info`. |
| **DIAL Files — Tool-Response Offload**     |                                                                 |          |                                                                                                              |
| `TOOL_CALL_RESULT_OFFLOAD__ENABLED_BY_DEFAULT` | `true`                                                          | No       | Default value of the per-app `enabled` flag (`features.dial_files.tool_call_result_offload.enabled`). Apps override per-app; `enabled: false` disables offload for that app. |
| `TOOL_CALL_RESULT_OFFLOAD__SIZE_THRESHOLD` | `40000`                                                         | No       | Default byte threshold above which a tool-call response is offloaded to a DIAL file. Apps override per-app via `features.dial_files.tool_call_result_offload.size_threshold`. |
| `TOOL_CALL_RESULT_OFFLOAD__EXCLUDED_TOOLS` | `[]`                                                            | No       | Default JSON list of **additional** tool names exempt from offloading. The read-back tools (`internal_file_read_lines`, `internal_file_search`) are always excluded regardless of this value, so a large read-back slice is never re-offloaded. Apps add more per-app via `features.dial_files.tool_call_result_offload.excluded_tools`. |
| **External URL Egress**                    |                                                                 |          |                                                                                                              |
| `EXTERNAL_URL_FETCH_ENABLED`                 | `false`                                                         | No       | Admin cap on fetching external (non-DIAL) URLs. When `false` (default), no app may fetch external URLs regardless of its manifest; the deployment-handoff branch (deployments with `features.url_attachments`) is unaffected. Apps can opt out per-app via `features.external_url_fetch.enabled=false` even when the admin allows. |
| `EXTERNAL_URL_FETCH_HOST_ALLOWLIST`        | —                                                               | No       | Comma-separated allowlist of host patterns for external URL fetches. Unset (default) means no admin-level host restriction. Patterns: exact host (`example.com`) or `*.example.com` for any subdomain. Re-checked on every redirect hop. Per-app `features.external_url_fetch.host_allowlist` narrows further (intersection) but never expands. |
| `EXTERNAL_URL_FETCH_MAX_REDIRECTS`         | `5`                                                             | No       | Maximum HTTP redirects on external URL fetches. Each hop is SSRF-checked. Hard ceiling 10.                   |
| `EXTERNAL_URL_FETCH_CONNECT_TIMEOUT_SECONDS` | `5.0`                                                           | No       | TCP connect timeout (seconds) for external URL fetches. Read/write/pool timeouts use the resolved tool timeout. |
| **Dynamic Tool Discovery** `[Preview]`     |                                                                 |          |                                                                                                              |
| `MIN_TOOLS_FOR_DEFERRAL`                   | `10`                                                            | No       | Deployment-wide minimum toolset size for deferral to apply. Toolsets with fewer tools than this threshold are promoted to eager loading even when `deferred=true`. Apps override per-app via `orchestrator.tool_discovery.min_tools_for_deferral`. Requires `ENABLE_PREVIEW_FEATURES=true`. |
| **Skills**                                 |                                                                 |          |                                                                                                              |
| `DIAL_SKILLS_FILE_MAX_BYTES`               | `262144`                                                        | No       | Cap on a single file read from a DIAL skill resource, `SKILL.md` included. Must exceed the largest manifest you expect: an over-cap manifest drops the skill. See [docs/skills.md](docs/skills.md). |
| `DIAL_SKILLS_MAX_FILES`                    | `200`                                                           | No       | Maximum bundled files advertised to the agent per DIAL skill resource; beyond it the listing is truncated     |
| `DIAL_SKILLS_LISTING_MAX_PAGES`            | `10`                                                            | No       | Maximum file-listing pages followed per DIAL skill resource, bounding a server-supplied cursor                |
| `SKILL_INVOCATION_MAX_SKILLS`              | `10`                                                            | No       | Maximum distinct skills a user may have invoked from the messages of one conversation (`custom_content.skills`), counted newest first. Each one adds a `<skill>` block to the system prompt and one DIAL Core fetch per turn; beyond the cap the oldest picks stop being registered. Preview-gated. See [docs/skills.md](docs/skills.md). |
| **Feature Gating**                         |                                                                 |          |                                                                                                              |
| `ENABLE_PREVIEW_FEATURES`                  | `false`                                                         | No       | Enable preview features across the deployment (schema visibility + runtime activation)                       |
| **Templates**                              |                                                                 |          |                                                                                                              |
| `PREDEFINED_EXTRA_PATHS`                   | —                                                               | No       | JSON list of directories layered on top of built-in predefined content (later entries override earlier ones) |
| `CONFIG_PROMPT_MAPPING`                    | *(built-in mapping)*                                            | No       | JSON mapping of predefined system prompts to DIAL Core deployments                                           |
| **Observability**                          |                                                                 |          |                                                                                                              |
| `OTEL_SERVICE_NAME`                        | `quickapps`                                                     | No       | Service name stamped on all exported telemetry (traces, metrics, logs)                                       |
| `OTEL_TRACES_EXPORTER`                     | —                                                               | No       | Set to `otlp` to enable tracing and export spans over OTLP/gRPC. Instruments the FastAPI server and outgoing HTTP clients (`httpx`, `requests`, `aiohttp`, `urllib`) and stamps trace context onto log records — see [docs/logging.md](./logging.md). |
| `OTEL_METRICS_EXPORTER`                    | —                                                               | No       | Comma-separated metric exporters: `otlp` (push over OTLP/gRPC) and/or `prometheus` (serve a scrape endpoint). Enables FastAPI and system/process metrics.  |
| `OTEL_LOGS_EXPORTER`                       | —                                                               | No       | Set to `otlp` to export log records (INFO and above) over OTLP/gRPC alongside console output — see [docs/logging.md](./logging.md). |
| `OTEL_EXPORTER_OTLP_ENDPOINT`              | `http://localhost:4317`                                         | No       | OTLP/gRPC collector endpoint shared by trace, metric, and log export. One of the [standard OpenTelemetry SDK variables](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/), which the underlying exporters honor as usual (per-signal endpoints, headers, timeouts, resource attributes, …). |
| `OTEL_EXPORTER_PROMETHEUS_PORT`            | `9464`                                                          | No       | Port of the Prometheus scrape endpoint (effective only with `prometheus` in `OTEL_METRICS_EXPORTER`)         |
| **Scripts & Tests**                        |                                                                 |          |                                                                                                              |
| `REMOTE_DIAL_URL`                          | —                                                               | No       | URL of the remote DIAL Core, used only by `generate_dial_config` script and e2e/integration tests            |
| `REMOTE_DIAL_API_KEY`                      | —                                                               | No       | API key of the remote DIAL Core, used only by `generate_dial_config` script and e2e/integration tests        |

### Deprecated Environment Variables

> [!CAUTION]
> These variables still work but will be removed in a future major version.

| Variable                        | Replacement                                                        | Description                                                                                                                  |
|---------------------------------|--------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| `PREDEFINED_BASE_PATH`          | `PREDEFINED_EXTRA_PATHS`                                           | If set alone, treated as a single extra layer on top of the built-in content                                                 |
| `PY_INTERPRETER_CLIENT_TIMEOUT` | `DEFAULT_TOOL_TIMEOUT_SECONDS` or `tool_defaults.timeout_seconds`  | When set, still controls the PyInterpreter client timeout (seconds, default `60.0`), but the unified tool-timeout settings are preferred. |
| `LOG_FORMAT`                    | `DIAL_SDK_TEXT_LOG_FORMAT` or `DIAL_SDK_LOG_FORMAT=json`           | When set, still controls the `text` output format (and wins over the replacements); a warning is emitted at startup. See [docs/logging.md](./logging.md). |
| `LOG_DATE_FORMAT`               | —                                                                  | Still honored alongside `LOG_FORMAT`; going forward the timestamp format is fixed to `%Y-%m-%d %H:%M:%S` (the previous default). |
| `OTEL_PYTHON_LOG_CORRELATION`   | — *(automatic)*                                                    | Deprecated by aidial-sdk; a warning is emitted at startup. Trace fields are stamped onto log records whenever tracing is enabled, so the switch is redundant — and setting it installs OTel's legacy root-logger format, which double-logs SDK records and bypasses this service's console formatting. See [docs/logging.md](./logging.md). |

**Notes:**

- Variables listed above are a superset used across development and deployment modes. Some variables (e.g.
  `REMOTE_DIAL_*`) are only used when running the full local stack via docker-compose or during testing.
- Telemetry is opt-in: when none of `OTEL_TRACES_EXPORTER` / `OTEL_METRICS_EXPORTER` / `OTEL_LOGS_EXPORTER`
  is set, OpenTelemetry is not initialized at all.
- For a standalone Quick Apps deployment the essential variable is only `DIAL_URL`
- For PyInterpreter tool setup
  see: [DIAL Core](https://github.com/epam/ai-dial-core), [PyInterpreter](https://github.com/epam/ai-dial-code-interpreter).

### Log Format Configuration

Moved to [docs/logging.md](./logging.md), which covers the text and JSON output modes, format
customization, OTEL trace correlation, and OTLP log export.

### Payload Logging

By policy, logs carry **structure** — roles, counts, sizes, names, ids, statuses, durations, HTTP codes,
header **names**, and URLs stripped to scheme/host/path — and never **content**: message bodies, tool-call
argument values, tool/LLM response bodies, attachment content, header **values**, or URL query strings. This
holds at every level, DEBUG included, so raising verbosity during an incident never brings conversation
content into the logs.

`LOG_PAYLOADS=true` is the single, explicit exception: it re-enables the payload-bearing DEBUG records (message
context, tool-call arguments, raw responses), each field truncated to `LOG_PAYLOADS_MAX_LENGTH`, and lifts the
INFO cap on the wire-level third-party loggers (`openai`, `httpx`, `httpcore`). Every payload record is prefixed
with a `[payload]` marker so these lines can be found — or excluded — with a single filter. Forwarded header **values** are
never logged, even with the switch on. The switch is additive to the level — content appears only when
`QUICKAPP_LOG_LEVEL=DEBUG` **and** `LOG_PAYLOADS=true`.

> [!CAUTION]
> `LOG_PAYLOADS` is intended for **local development only**. It writes conversation content and wire-level
> third-party payloads to the log pipeline (including any OTLP export). Do **not** enable it in shared or
> production environments.
