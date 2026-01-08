# Quick Apps (2.0)

[![DIALX Community on Discord](https://img.shields.io/static/v1?label=DIALX%20Community%20on&message=Discord&color=blue&logo=Discord&style=flat-square)](https://discord.gg/ukzj9U9tEe)

[![DIALX](https://dialx.ai/dialx_logo.svg)](https://dialx.ai/)

Quick Apps (2.0) is a composer for building DIAL applications from reusable tools and integrations. It lets you
declaratively compose new DIAL applications by wiring DIAL-native tools, REST APIs, and MCP servers with any LLM
registered in DIAL Core acting as the orchestrator. Publishing a Quick App produces a DIAL application record managed by
Core.

## Quick highlights

- Compose applications by wiring tools and an LLM orchestrator via JSON-schema–validated manifests.
- Advanced flow controls: fallbacks, parallel tool execution, loops and retries.
- Native DIAL tools plus external REST and MCP integrations.
- Any LLM available in DIAL Core (Azure OpenAI, Anthropic, Vertex AI, etc.).

## Table of contents

- Quick start
    - [Local development](#local-development)
    - [Setup & Run](#run)
- Configuration
    - [Configuration model](#configuration-model)
    - [Orchestrator configuration](#orchestrator-configuration)
    - [Contexts & Tool sets](#contexts-configuration)
    - [Tool fallback & attachments](#tool-fallback-configuration)
- [Environment variables](#environment-variables)
- [Agent configuration (examples)](#agent-configuration)
- [E2E & Integration tests](#e2e--integration-tests)

## What it does

* Composes applications by wiring tools and an LLM orchestrator through declarative configuration.
* Orchestrates execution with advanced flow controls: fallback strategies, parallel tool execution, loops, and retries.
* Integrates natively with DIAL tools and supports external REST APIs and MCP servers.
* Uses any LLM registered in DIAL Core (e.g., Azure OpenAI, Anthropic, Vertex AI, Google)

## Configuration model

Quick Apps are defined by a JSON-schema–validated manifest.
Schema reference:

* Generated locally via: make dump_app_schema
* Hosted reference: https://mydial.epam.com/custom_application_schemas/quickapps2

## Environment Variables

| Variable                                 | Required | Description                                                                                                                | Available Values | Default Value              |
|------------------------------------------|----------|----------------------------------------------------------------------------------------------------------------------------|------------------|----------------------------|
| DIAL_URL                                 | No       | URL for the DIAL service                                                                                                   | URL string       | `"http://localhost:8090"`  |
| DIAL_API_VERSION                         | No       | API version for LLM models access                                                                                          | String           | `2024-05-01-preview`       |
| PY_INTERPRETER_LOCAL_RUN                 | No       | Run the PyInterpreter locally or use the DIAL Core API                                                                     | `true`, `false`  | `false`                    |
| PY_INTERPRETER_URL                       | No       | The URL of the PyInterpreter service or DIAL Core API                                                                      | URL string       | `http://localhost:8080`    |
| PY_INTERPRETER_API_KEY                   | No       | API key for local run of the PyInterpreter                                                                                 | String           | `null`                     |
| PY_INTERPRETER_DEFAULT_SESSION_ID        | No       | Default session ID for the PyInterpreter                                                                                   | String           | `null`                     |
| PY_INTERPRETER_ADDITIONAL_HANDLING_MODEL | No       | Model used for additional handling in the PyInterpreter                                                                    | String           | `"gpt-4o-mini-2024-07-18"` |
| PY_INTERPRETER_CLIENT_TIMEOUT            | No       | Timeout for the PyInterpreter client requests in seconds                                                                   | Float            | `60.0`                     |
| PY_INTERPRETER_CLIENT_MAX_RETRIES        | No       | Maximum number of retries for the PyInterpreter client requests                                                            | Integer          | `3`                        |
| OTEL_SERVICE_NAME                        | No       | The name of the service for OpenTelemetry tracing and metrics                                                              | String           | `"quickapps"`              |
| REMOTE_DIAL_URL                          | No       | The URL of the remote DIAL used only by the `generate_dial_config` script and e2e/integration tests                        | URL string       | `null`                     |
| REMOTE_DIAL_API_KEY                      | No       | The API KEY of the remote DIAL used only by the `generate_dial_config` script and e2e/integration tests                    | String           | `null`                     |
| PREDEFINED_BASE_PATH:                    | No       | Specifies the base path to the predefined configurations/templates files for the application.                              | String           | `config/predefined`        |
| SHOW_USAGE_STATISTICS                    | No       | Flag to show the "Usage statistics" stage per user message.                                                                | `true`, `false`  | `false`                    |
| DEFAULT_AGENT_MAX_ITERATIONS             | No       | Default vale for the server for the max count of orchestrator(agent) operations.                                           | Integer          | 15                         |
| CONTENT_DOWNLOADER_FILE_SIZE_LIMIT       | No       | Internal tool file size limitation. It is used to download files from DIAL to pass content as MCP attachment. Bytes count. | Integer          | 20971520                   |
| SHOW_EXECUTION_TIME_STAGE                | No       | Flag to show time execution stage                                                                                          | `true`, `false`  | `false`                    |

+ Clarifications:
+
    - Variables marked in this table are the superset used across development and deployment modes. Some variables are
      only used when running the full local stack via docker-compose (for example container-specific hostnames or UI
      service variables). Others are specific to the Helm/cluster deployment (see helm/development.yaml).
+
    - Important variables for a standalone Quick Apps deployment (no docker-compose) are primarily:
+
    - DIAL_URL — URL of the DIAL Core API that Quick Apps will call (must be reachable from Quick Apps).
+
    - DIAL_API_KEY — if your DIAL Core requires API key auth.
+
    - PREDEFINED_BASE_PATH — if you use predefined configurations/templates.
+
    - REMOTE_DIAL_URL and REMOTE_DIAL_API_KEY are used by the generate_dial_config script and e2e/integration tests and
      typically do not affect normal runtime behavior of standalone Quick Apps.
+
    - When following the docker-compose route, use the compose-provided hostnames (example DIAL inside
      containers: http://core:8080); when deploying in Kubernetes/Helm use service DNS names as shown in
      helm/development.yaml.

## Local Development

### Pre-requisites

1. Install Make
    - macOS: usually preinstalled.
    - Windows: see https://gnuwin32.sourceforge.net/packages/make.htm or use Chocolatey.
    - Ensure `make` is in PATH (`which make`).

2. Install Python 3.11
    - macOS (Homebrew): `brew install python@3.13`
    - Official downloads: https://www.python.org/downloads/
    - Ensure `python3.13` (or `python3`) is in PATH (`python3.13 --version`).

3. Install Poetry (https://python-poetry.org/)
    - macOS: consider using `pipx` for installation.
    - Windows: use the official Poetry installer.
    - Ensure `poetry` is available (`poetry --version`).

### Setup

1. Clone the repository
2. Create and activate virtual environment

    ```bash
    make init_venv
    source .venv/bin/activate
    ```

3. Install dev dependencies

    ```bash
    make install_dev
    ```

4. Create `.env` file in the root of the project. Copy `.env.template` files and fill the values for secrets.

     ```bash
     cp .env.template .env
     ```
5. Generate DIAL configuration files:

    ```bash
    make generate_dial_config
    ```

   This command will generate two files in `docker_compose_files/core/configuration/generated/`:
    - `models.json` - contains the models configuration for DIAL.
    - `application-schemas.json` - contains the QuickApps schema.

### Run

- Option A — Full local stack (docker-compose)
    - Use this if you want to bring up DIAL Core, chat UI, redis, themes and adapters locally for end-to-end development
      and testing.
    - This docker-compose setup launches multiple services and uses internal hostnames (for example core, redis,
      themes). Example:

      ```bash
      docker compose up -d
      ```

    - Notes:
        - When running via docker-compose the compose files set service hostnames (for example DIAL URL inside
          containers is http://core:8080). Those container-internal hostnames are not valid from your host machine — use
          the exposed ports (for example http://localhost:8090) when calling services from the host.
        - Some environment variables in the repo (e.g. adapter or chat-specific variables) are only relevant for the
          full stack docker-compose setup and may be ignored when you deploy Quick Apps standalone.

- Option B — Quick Apps standalone (connect to an existing DIAL Core)
    - Use this when you already have a DIAL Core instance available (local, staging, or cloud). You do NOT need to run
      core, chat, redis, themes, or adapter containers to deploy Quick Apps.
    - Steps:
        1. Create and fill your .env (or set environment variables) with the fields required by Quick Apps. At minimum
           ensure:
            - DIAL_URL points to your DIAL Core API endpoint (example: https://core.example.com or http://core:8080
              depending on your environment).
            - If required by your DIAL Core instance, set DIAL_API_KEY or other auth variables.
            - PREDEFINED_BASE_PATH if you rely on predefined templates/toolsets.
        2. Deploy Quick Apps backend (for cluster deployments see helm/development.yaml). When deploying via Helm the
           file helm/development.yaml contains an example DIAL_URL and other production-ready env hints.
        3. Register the application in DIAL Core
            - Add the Quick App schema generated by `make dump_app_schema` to the Core configuration so Core knows the
              Quick App application schema. For Helm create/update a ConfigMap or mount the generated file under the
              path referenced by PREDEFINED_BASE_PATH so Core can load it.
            - Ensure the chat UI has the Quick Apps feature enabled. Verify the chat service (or your ai-dial-chat
              deployment) includes `quick-apps` in its ENABLED_FEATURES flags so the UI will surface Quick Apps.
    - Notes:
        - Quick Apps will act as a client of DIAL Core; it must be able to reach the DIAL Core API (DIAL_URL) and, if
          required, present credentials (DIAL_API_KEY).
        - Registering on the DIAL Core side can be done by adding the application JSON to Core configuration or via your
          Core management UI — ensure the application record points to the Quick Apps service as appropriate.

### Utils

1. Format the code:

    ```bash
    make format
    ```

2. Run linters:

    ```bash
    make lint
    ```

3. To automatically apply black and isort on commit, enable PreCommit:

   ```bash
   make install_pre_commit_hooks
   ```

   This command will set up the git hook scripts.

## Agent Configuration:

<details> 
<summary><b>Configuration JSON Sample</b></summary>

The project contains predefined configs of application and predefined tools

* [Sample application](config/examples/applications.json).
* [Chat-hub application](config/examples/chat-hub-openai.json).
* [Predefined Tools/Toolsets](config/predefined).

<br>Here's a full example of configuration:

```json
{
  "orchestrator": {
    "deployment": {
      "name": "gpt-4o-2024-05-13",
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
      "url": "https://dial-core.example.com"
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
            "name": "dall-e-3"
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

### Orchestrator configuration

| Field          | Required | Type    | Description                                                                                              | Available Values | Default Value |
|----------------|----------|---------|----------------------------------------------------------------------------------------------------------|------------------|---------------|
| deployment     | Yes      | Object  | The DIAL deployment configuration. See [Deployment configuration](#deployment-configuration)             | -                | -             |
| system_prompt  | Yes      | Object  | The configuration for the system prompt. See [System prompt configuration](#system-prompt-configuration) | -                | -             |
| max_iterations | No       | Integer | The max count of orchestrator(agent) operations. -1 value for infinite                                   | Integer          | 15            |

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

### Contexts configuration

| Field       | Required                          | Type   | Description                                            | Available Values       | Default Value |
|-------------|-----------------------------------|--------|--------------------------------------------------------|------------------------|---------------|
| type        | Yes                               | String | The context type                                       | `user-defined`, `file` | -             |
| description | Yes                               | String | The context description                                | -                      | -             |
| content     | Yes (if `type` is `user-defined`) | String | The context content                                    | -                      | -             |
| url         | Yes (if `type` is `file`)         | String | The URL to the file where file with content is located | -                      | -             |

<details> 
<summary><b>Contexts configuration JSON sample</b></summary>

User-defined context:

```json
{
  "type": "user-defined",
  "description": "Some user context description",
  "content": "Content of user defined context"
}
```

The context loaded by URL:

```json
{
  "type": "file",
  "description": "Some file context description",
  "url": "https://some_url"
}

```

</details>

### Tool sets configuration

#### RestApiToolSet Configuration

| Field         | Required | Type                                                                                                                                                                                                | Description                               | Default Value |
|---------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------|---------------|
| name          | Yes      | String                                                                                                                                                                                              | The name of the tool set.                 | -             |
| description   | No       | String                                                                                                                                                                                              | The description of the tool set.          | `null`        |
| enabled       | No       | Boolean                                                                                                                                                                                             | Whether the toolset is enabled.           | `true`        |
| type          | Yes      | String                                                                                                                                                                                              | The type of the tool set.                 | `rest-api`    |
| authorization | No       | One of `BasicAuthorization`, `BearerAuthorization`, <br/>`ClientIdSecretAuthorization`, `ApiKeyAuthorization`, `null`</br> <br>See [Authorization configuration](#Authorization-configuration)</br> | Authorization configuration for REST API. | `null`        |
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

| Field         | Required | Type   | Description                      | Default Value |
|---------------|----------|--------|----------------------------------|---------------|
| type          | Yes      | String | The type of the tool set.        | `predefined`  |
| template_name | Yes      | String | Name of the predefined template. | -             |

#### MCPToolSet Configuration

| Field                  | Required | Type               | Description                                                              | Default Value |
|------------------------|----------|--------------------|--------------------------------------------------------------------------|---------------|
| name                   | Yes      | String             | The name of the tool set.                                                | -             |
| description            | No       | String             | The description of the tool set.                                         | `null`        |
| enabled                | No       | Boolean            | Whether the toolset is enabled.                                          | `true`        |
| type                   | Yes      | String             | The type of the tool set.                                                | `mcp`         |
| mcp_server_info        | Yes      | MCPServerInfo      | MCP server info. See [MCPServerInfo structure](#mcpserverinfo-structure) | -             |
| allowed_tools          | No       | Array of String    | Allowed MCP tool names from the server                                   | `null`        |
| attachment             | No       | AttachmentConfig   | See also: [AttachmentConfig](#attachment-configuration)                  | -             |
| fallback_configuration | No       | ToolFallbackConfig | See also: [Tool fallback configuration](#tool-fallback-configuration)    | -             |

##### MCPServerInfo structure:

| Field         | Required | Type                                                                                                                                                                                                   | Description           | Default Value |
|---------------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------|---------------|
| url           | Yes      | String                                                                                                                                                                                                 | URL of the MCP server | -             |
| protocol      | Yes      | one of the String `sse` or `streamable_http`                                                                                                                                                           | Protocol              | -             |
| authorization | No       | One of `BearerAuthorization`, `MCPApiKeyAuthorization`, <br/>`ClientIdSecretAuthorization`, `BasicAuthorization`, `null`</br> <br>See [Authorization configuration](#Authorization-configuration)</br> | Authorization         | -             |

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
| attachment             | No       | AttachmentConfig       | See also: [AttachmentConfig](#attachment-configuration)               | -             |
| fallback_configuration | No       | ToolFallbackConfig     | See also: [Tool fallback configuration](#tool-fallback-configuration) | -             |

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
| display                | No                                   | Object | Representation (display) configuration for tool execution results. See [Display configuration](#display-configuration), See [Tool stage configuration](#Display-tool-stage-configuration) | -                | `null`        |
| fallback_configuration | No                                   | Object | Tools fallback configuration. If not present will always raise Error. See [Tool fallback configuration](#tool-fallback-configuration)                                                     | -                | `null`        |

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

More detailed for default parameters [JSON Schema spec](#https://json-schema.org/understanding-json-schema/reference)

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
  ]
}
```

</details>

## Tool Fallback Configuration

The `fallback_configuration` field allows you to define strategies for handling tool execution errors.

### `ToolFallbackConfig` Structure

| Field      | Required | Type                 | Description                          | Available Values          | Default Value |
|------------|----------|----------------------|--------------------------------------|---------------------------|---------------|
| strategies | Yes      | Array[StrategyModel] | List of fallback handling strategies | See strategy models below | -             |

### Strategy Models

There are two types of strategy models that can be used:

1. **StopStrategyModel** - The agent stops execution
2. **ContinueStrategyModel** - The agent continues execution, attempting to call another suitable tool or give an answer
   based on its own knowledge.

### Common Strategy Fields

| Field                                     | Required | Type                      | Description                                       | Default Value                         |
|-------------------------------------------|----------|---------------------------|---------------------------------------------------|---------------------------------------|
| type                                      | Yes      | Enum `stop` or `continue` | The type of the strategy                          |                                       |
| trigger_on                                | No       | Object                    | Condition that triggers this strategy             | by default triggers on all exceptions |
| instructions (for continue strategy only) | No       | String                    | Instructions to the agent what to do on exception |                                       |
| display_error_in_stage                    | No       | Boolean                   | Whether to display the error in the stage         | `true`                                |

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
    "strategies": [
      {
        "type": "stop",
        "trigger_on": {
          "type": "contains",
          "value": "connection error",
          "case_sensitive": false
        }
      },
      {
        "type": "continue",
        "instructions": "try to call tool 'web_search' to find the answer",
        "trigger_on": {
          "type": "equals",
          "value": "Something went wrong during tool execution",
          "case_sensitive": false
        },
        "display_error_in_stage": false
      }
    ]
  }
}
```

</details>

### Behavior Notes

- If no Fallback strategy for tool provided, the default behaviour is to continue with predefined instructions
- Strategies are evaluated in the order they appear in the array
- The first strategy with a matching trigger condition is used

## E2E & Integration tests

To run E2E tests or Integration tests, refer to the [E2E Testing Documentation](./src/tests/README.md).