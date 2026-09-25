<h1 align="center">
         Quick Apps (2.0)
    </h1>
    <p align="center">
        <p align="center">
        <a href="https://dialx.ai/">
          <img src="https://dialx.ai/logo/dialx_logo.svg" alt="About DIALX">
        </a>
    </p>
<h4 align="center">
    <a href="https://discord.gg/ukzj9U9tEe">
        <img src="https://img.shields.io/static/v1?label=DIALX%20Community%20on&message=Discord&color=blue&logo=Discord&style=flat-square" alt="Discord">
    </a>
</h4>

Quick Apps (2.0) is a composer for building DIAL applications from reusable tools and integrations. It lets you
declaratively compose new DIAL applications by wiring DIAL-native tools, REST APIs, and MCP servers with any LLM
registered in DIAL Core acting as the orchestrator. Publishing a Quick App produces a DIAL application record managed by
Core.

## Quick highlights

- Compose applications by wiring tools and an LLM orchestrator via JSON-schema–validated manifests.
- Advanced flow controls: fallbacks, parallel tool execution, loops and retries.
- Native DIAL tools plus external REST and MCP integrations.
- Any LLM available in DIAL Core (Azure OpenAI, Anthropic, Vertex AI, etc.).

## Feature Lifecycle

Some features are released as **Preview** before becoming **Stable**:

| Stage       | Meaning                                                                                              |
|-------------|------------------------------------------------------------------------------------------------------|
| **Preview** | Available for use but may change in breaking ways without a major version bump. Feedback is welcome. |
| **Stable**  | Covered by semantic versioning — breaking changes require a major version bump.                      |

Features in Preview are marked with a `[Preview]` tag in documentation.

## Documentation

| Document | Description |
|----------|-------------|
| [Local development](docs/local-development.md) | Setup, run (docker / standalone), format, lint, tests |
| [Configuration](CONFIGURATION.md) | App manifest reference and environment variables |
| [Documentation hub](docs/README.md) | Reading order, capability map, index of guides |
| [Contributing](CONTRIBUTING.md) | Contribution guidelines |

> For configuration questions, use [CONFIGURATION.md](CONFIGURATION.md). Design docs under `docs/designs/` explain *why*; guides under `docs/` explain *how*.
> Reading order and the full capability map live in the [documentation hub](docs/README.md).

## Quick start

```bash
make init_venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install_dev
cp .env.template .env       # set at least DIAL_URL — see CONFIGURATION.md
make generate_dial_config
python3 ./src/quickapp/app.py
```

Full options (docker-compose stack, standalone against an existing Core, utils, tests):
**[Local development](docs/local-development.md)**.

## More

For more information about DIAL and its components, visit the [DIAL documentation](https://dialx.ai/docs). Join the DIAL
community on [Discord](https://discord.gg/ukzj9U9tEe) for support and collaboration.
