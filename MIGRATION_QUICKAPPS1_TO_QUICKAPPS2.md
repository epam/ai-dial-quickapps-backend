# Migration Guide: QuickApps (old) → Quick Apps 2.0 (new)

This guide helps migrate your applications from **QuickApps** (old) to **Quick Apps 2.0** (new). The new version uses a
different configuration model, schema, and deployment identifiers. Use this document to map your existing app config to
the new structure and avoid common pitfalls.

## Overview

| Aspect              | QuickApps 1 (Old)                                                           | Quick Apps 2.0 (New)                                                                                                                   |
|---------------------|-----------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| **Schema ID**       | `https://mydial.epam.com/custom_application_schemas/quickapps`              | `https://mydial.epam.com/custom_application_schemas/quickapps2`                                                                        |
| **Config shape**    | Flat `applicationProperties` (temperature, instructions, model, tool sets)  | Nested: `orchestrator`, `contexts`, `tool_sets`                                                                                        |
| **Model / agent**   | `model`, `temperature`, `instructions` at top level                         | Under `orchestrator.deployment` and `orchestrator.system_prompt`                                                                       |
| **RAG / documents** | `document_relative_url` + built-in `query_document` tool                    | `contexts` (type `file`) + predefined tool `dial_rag` in a tool set                                                                    |
| **Tools**           | `web_api_toolset`, `mcp_toolset`, `applications_as_tools`, `client_toolset` | Single `tool_sets` array: for toolsets of different types: rest-api, dial-deployment, mcp, predefined, etc. (no client/external tools) |
| **API / endpoints** | Completion and configuration under `quick_apps` deployment                  | Same idea; endpoint paths may differ—use schema and Core config for your environment                                                   |

After migration, register the app in DIAL Core with `applicationTypeSchemaId` set to the **Quick Apps 2.0** schema and
put the migrated JSON under `applicationProperties` as shown below.

---

## 1. Prerequisites and deployment

- **Core/Chat versions**: Quick Apps 1 required Core ≥ 0.28.0 and Chat ≥ 0.29.0. For Quick Apps 2.0, use the versions
  required by the current Quick Apps 2 backend and [README](./README.md).
- **Schema in Core**: Add the **Quick Apps 2.0** application type schema to DIAL Core (e.g. from `make dump_app_schema`
  or the hosted quickapps2 schema). 
- **Chat**: Ensure the chat component has Quick Apps 2.0 enabled (e.g. `ENABLED_FEATURES` including the appropriate
  quick-apps flag and any host/schema IDs your setup uses). See project README and deployment docs.
- **Environment**: Old env vars like `API_VERSION`, `TEMPERATURE_FALLBACK`, `SYSTEM_PROMPT_FALLBACK`,
  `RAG_DEPLOYMENT_NAME` are replaced by the Quick Apps 2.0 configuration and env (e.g. `DIAL_URL`, `DIAL_API_VERSION`).
  See [README](./README.md#environment-variables) and [CONFIGURATION](./CONFIGURATION.md).

---

## 2. Configuration structure mapping

Quick Apps 1 used a flat set of properties. Quick Apps 2.0 requires three main blocks: **orchestrator**, **contexts**,
and **tool_sets**.

### 2.1 Orchestrator (model, system prompt, iterations)

| QuickApps 1                        | Quick Apps 2.0                                   | Notes                                                                                                                |
|------------------------------------|--------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `model` (string or ConditionGroup) | `orchestrator.deployment.name`                   | Use the deployment name (e.g. model id). Conditional model selection may require different handling—see notes below. |
| `temperature`                      | `orchestrator.deployment.parameters.temperature` | Same semantics.                                                                                                      |
| (none)                             | `orchestrator.deployment.parameters`             | Add other model parameters (e.g. `seed`) as needed.                                                                  |
| `instructions`                     | `orchestrator.system_prompt`                     | See below.                                                                                                           |
| (none)                             | `orchestrator.max_iterations`                    | Optional; default 15. Set if you need a cap.                                                                         |

**System prompt migration**

- Quick Apps 1: single string `instructions`.
- Quick Apps 2.0: object with `type`, `variables`, and (for custom) `content`.

Typical migration:

```json
{
  "system_prompt": {
    "type": "custom",
    "variables": {},
    "content": "<paste your QuickApps 1 'instructions' here>"
  }
}
```

If you used variable substitution in instructions, map those into `variables` and reference them in `content` (e.g.
`{variable_name}`).

**Conditional model (`model` as ConditionGroup in QuickApps 1)**  
Quick Apps 2.0 config in this codebase is deployment-based (single `orchestrator.deployment.name`). If your QuickApps 1
app used `ConditionGroup` for dynamic model selection, you need to either fix a single deployment in 2.0 or
implement/request support for conditional deployment selection in the new backend.

---

### 2.2 Contexts (replacing document_relative_url and static context)

Quick Apps 1 used `document_relative_url` (and optionally instructions) to give the agent access to documents. Quick
Apps 2.0 uses a **contexts** array.

| QuickApps 1                               | Quick Apps 2.0                                       | Notes                                                                                                                |
|-------------------------------------------|------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `document_relative_url` (string or array) | One or more `contexts` with `type: "file"`           | Use the URL pattern `https://<DIAL_URL>/v1/files/<path>/<name>` (replace `<DIAL_URL>` with your DIAL Core base URL). |
| Static text / instructions in prompt      | `contexts` with `type: "user-defined"` and `content` | Use for fixed text context.                                                                                          |

**File context URL pattern**

For file contexts, use:

```
https://<DIAL_URL>/v1/files/<path>/<name>
```

Replace `<DIAL_URL>` with your DIAL Core API base URL (e.g. `https://core.example.com` or `http://core:8080`). The path
and name should match how the file is stored in DIAL (e.g. the same path you used in QuickApps 1 `document_relative_url`
after the `files/` prefix).

**Example: single document**

QuickApps 1:

```json
"document_relative_url": "files/abc123/doc.docx"
```

Quick Apps 2.0:

```json
"contexts": [
  {
    "type": "file",
    "description": "Document for RAG",
    "url": "https://<DIAL_URL>/v1/files/abc123/doc.docx"
  }
]
```

**Example: multiple documents**

Turn each element of `document_relative_url` into one `type: "file"` context with the appropriate `url` (using the
pattern above) and a `description`.

If you have no documents and no static context, use an empty array: `"contexts": []`.

---

### 2.3 Tool sets (web_api_toolset, mcp_toolset, applications_as_tools)

Quick Apps 1 had separate arrays: `web_api_toolset`, `mcp_toolset`, `applications_as_tools`. Quick Apps 2.0 has a single
**tool_sets** array; each item has a `type` and type-specific fields.

#### 2.3.1 REST / Web API tools

- **QuickApps 1**: `web_api_toolset` with either:
    - **WebApiToolsetInfo**: `tool_endpoints` + `auth_info`, or
    - **RestApiToolset**: `type: "rest-api"`, `name`, `authorization`, `tools` (each tool: `rest_api_method_info` +
      `open_ai_tool`).

- **Quick Apps 2.0**: Use a tool set with `type: "rest-api"`. Structure is very similar to the old **RestApiToolset**.

Migration steps:

1. For each QuickApps 1 **RestApiToolset** item, add one object to `tool_sets` with `type: "rest-api"`, same `name`,
   `authorization`, and `tools`. Tool shape (`rest_api_method_info` + `open_ai_tool`) can usually be reused; add
   `display` / `parameter_info` if you need stage or parameter behavior (see [CONFIGURATION](./CONFIGURATION.md)).
2. For each **WebApiToolsetInfo** (tool_endpoints + auth_info), convert each endpoint into a **rest-api** tool:
    - `method_url` / `method_type` → `rest_api_method_info`.
    - Build an `open_ai_tool.function` (name, description, parameters) from the endpoint's name, description, and
      parameters. Map parameter location (query vs body) with `parameter_info` (`type`: `query`, `body`, etc., and
      `key`).

Auth mapping:

- Old `auth_info.auth_type: "apikey"` → `authorization.type: "api_key"` with `key`, `name`, and `location` (e.g. `query`
  or `header`).
- Old OBO auth → map to `client_id_secret` or the appropriate 2.0 auth type per [CONFIGURATION](./CONFIGURATION.md).

#### 2.3.2 MCP tools

- **QuickApps 1**: `mcp_toolset` array of objects with `name`, `type: "mcp"`, `mcp_server_info`, `allowed_tools`.
- **Quick Apps 2.0**: Same idea under `tool_sets`: one entry per MCP server with `type: "mcp"`, `name`,
  `mcp_server_info` (url, protocol, authorization), and optional `allowed_tools`.

Migration: For each QuickApps 1 MCP toolset entry, add one `tool_sets` entry with `type: "mcp"` and the same `name`,
`mcp_server_info`, and `allowed_tools`. Protocol and auth types are aligned (e.g. `sse`, `streamable_http`; bearer,
api_key, etc.).

#### 2.3.3 Other applications as tools (applications_as_tools)

- **QuickApps 1**: `applications_as_tools` — list of application IDs or ConditionGroups to use other DIAL apps as tools.
- **Quick Apps 2.0**: Use a **dial-deployment** tool set. You can reference predefined tools (e.g. RAG, image
  generation, web search) by `template_name`, or define deployment tools that call specific DIAL deployments.

To mimic "application X as tool":

- If there is a **predefined template** for that use (e.g. `dial_rag`, `web_search`, `image_generation`), add a tool set
  with `type: "dial-deployment"` and a tool like `{"type": "predefined-tool", "template_name": "..."}`.
- If you need to call a specific deployment or app by id/name, configure a deployment tool with the appropriate
  `deployment` and `open_ai_tool` (see [CONFIGURATION](./CONFIGURATION.md) and samples in the repo). There is no direct
  1:1 field for ConditionGroup-based application selection; you may need one tool set per app or to align with how Quick
  Apps 2.0 exposes deployments.

#### 2.3.4 RAG (query_document) in Quick Apps 2.0

- **QuickApps 1**: RAG was implied by `document_relative_url`; tool name `query_document`.
- **Quick Apps 2.0**: Add the predefined RAG tool in a **dial-deployment** tool set and provide document context via *
  *contexts** (see 2.2).

Example:

```json
{
  "name": "dial-deployment-tool-set",
  "type": "dial-deployment",
  "tools": [
    {
      "type": "predefined-tool",
      "template_name": "dial_rag"
    }
  ]
}
```

Ensure your `contexts` include the correct `type: "file"` entries with URLs in the form
`https://<DIAL_URL>/v1/files/<path>/<name>`. Instructions in the system prompt should still tell the agent to use the
RAG tool and to ground answers in the provided documents.

#### 2.3.5 Client toolset (client_toolset) — not supported in Quick Apps 2.0

- **QuickApps 1**: `client_toolset` — external client tools; when called, the chain stopped and the client had to return
  results with `intermediate_steps_to_restore`.
- **Quick Apps 2.0**: **Client/external tools are not supported.** There is no equivalent for `client_toolset`. If your
  QuickApps 1 app relied on client tools, you must remove or replace that functionality (e.g. with server-side tools,
  MCP, or rest-api tool sets) when migrating to 2.0.

---

## 3. Fields that stay on the DIAL application record

These are not part of the Quick Apps 2.0 JSON schema inside `applicationProperties`; they remain on the **application**
record in DIAL Core (or in the chat/Core config that defines the app). The UI uses these values (e.g. to show starter
buttons).

- **display_name** / **displayName** — Application display name.
- **description** — Application description.
- **starters** — Suggested starter prompts. Keep them on the application record; the UI shows buttons or similar
  controls based on these values.
- **attachments_in_stage** — If supported by the product, this is typically an application-level or feature flag, not
  inside the Quick App manifest.

So: migrate only the **Quick App–specific** config (orchestrator, contexts, tool_sets) into `applicationProperties`;
leave display name, description, starters, and attachment behavior on the application record.

---

## 4. Minimal before/after example

**QuickApps 1 (conceptual)**

```json
{
  "applicationTypeSchemaId": "https://mydial.epam.com/custom_application_schemas/quickapps",
  "applicationProperties": {
    "temperature": 0.8,
    "instructions": "You are a weather assistant.",
    "model": "gpt-4o-2024-05-13",
    "document_relative_url": "files/abc/weather-doc.docx",
    "starters": [
      "What to wear in London?"
    ],
    "web_api_toolset": [
      {
        "name": "geo-api",
        "type": "rest-api",
        "authorization": {
          "type": "api_key",
          "key": "...",
          "name": "api_key",
          "location": "query"
        },
        "tools": [
          {
            "rest_api_method_info": {
              "method_url": "https://geocode.maps.co/search",
              "method_type": "get"
            },
            "open_ai_tool": {
              "type": "function",
              "function": {
                "name": "geo_code",
                "description": "Get geo info for an address.",
                "parameters": {
                  "type": "object",
                  "properties": {
                    "q": {
                      "type": "string",
                      "description": "Address"
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
      }
    ]
  }
}
```

**Quick Apps 2.0 (migrated)**

```json
{
  "applicationTypeSchemaId": "https://mydial.epam.com/custom_application_schemas/quickapps2",
  "applicationProperties": {
    "orchestrator": {
      "deployment": {
        "name": "gpt-4o-2024-05-13",
        "parameters": {
          "temperature": 0.8
        }
      },
      "system_prompt": {
        "type": "custom",
        "variables": {},
        "content": "You are a weather assistant."
      }
    },
    "contexts": [
      {
        "type": "file",
        "description": "Weather document for RAG",
        "url": "https://<DIAL_URL>/v1/files/abc/weather-doc.docx"
      }
    ],
    "tool_sets": [
      {
        "name": "geo-api",
        "type": "rest-api",
        "authorization": {
          "type": "api_key",
          "key": "...",
          "name": "api_key",
          "location": "query"
        },
        "tools": [
          {
            "rest_api_method_info": {
              "method_url": "https://geocode.maps.co/search",
              "method_type": "get"
            },
            "open_ai_tool": {
              "type": "function",
              "function": {
                "name": "geo_code",
                "description": "Get geo info for an address.",
                "parameters": {
                  "type": "object",
                  "properties": {
                    "q": {
                      "type": "string",
                      "description": "Address",
                      "parameter_info": {
                        "type": "query",
                        "key": "q"
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
        "name": "rag-and-tools",
        "type": "dial-deployment",
        "tools": [
          {
            "type": "predefined-tool",
            "template_name": "dial_rag"
          }
        ]
      }
    ]
  }
}
```

(Keep `starters` and display name/description on the application record as in section 3.)

---

## 5. Checklist

- [ ] Use Quick Apps 2.0 backend and schema; point DIAL Core completion/configuration to the new service.
- [ ] Set `applicationTypeSchemaId` to `https://mydial.epam.com/custom_application_schemas/quickapps2`.
- [ ] Build `orchestrator`: `deployment.name`/`parameters` from `model`/`temperature`; `system_prompt` from
  `instructions`.
- [ ] Migrate `document_relative_url` to `contexts` (type `file`) using URL pattern
  `https://<DIAL_URL>/v1/files/<path>/<name>`; add `user-defined` contexts if needed.
- [ ] Convert every `web_api_toolset` entry to one or more `tool_sets` of type `rest-api` (and add `parameter_info`where
  needed).
- [ ] Convert every `mcp_toolset` entry to a `tool_sets` entry of type `mcp`.
- [ ] Replace RAG usage with `dial_rag` predefined tool + file contexts.
- [ ] Map `applications_as_tools` to dial-deployment tool sets (predefined or deployment tools).
- [ ] Keep display name, description, starters, and attachment options on the application record (UI depends on these
  for e.g. starter buttons).
- [ ] Remove or replace `client_toolset` usage; Quick Apps 2.0 does not support client/external tools.
- [ ] If you use conditional `model` (ConditionGroup), decide on a single deployment or request support for conditional
  selection.
- [ ] Validate the final JSON against the Quick Apps 2.0 schema (e.g. from `make dump_app_schema`).
- [ ] Test in a dev environment before switching production.

---

## 6. References

- New Quick Apps: [README.md](./README.md), [CONFIGURATION.md](./CONFIGURATION.md)
- Old Quick Apps: [quickapp1.md](./quickapp1.md), [quick_apps_explained.md](./quick_apps_explained.md)
- Schema: generate with `make dump_app_schema`; hosted ref:
  `https://mydial.epam.com/custom_application_schemas/quickapps2`
