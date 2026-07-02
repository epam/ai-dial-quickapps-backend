# Repo map — where to look

Concrete anchors for the investigation. **Starting points, not gospel** — both codebases move, so confirm each with LSP `goToDefinition`/`findReferences` or Grep before relying on it. If a path has drifted, search by symbol name (they're more stable than paths).

## Backend — `epam/ai-dial-quickapps-backend` (this repo, `src/quickapp/`)

**Config models (the field the toggle maps to):**
- `src/quickapp/config/application.py` — the manifest root. `ApplicationConfig` → `orchestrator: OrchestratorConfig`, `features: Features`, `contexts`, `tool_sets`, …
  - `OrchestratorConfig` — `deployment`, `system_prompt`, `max_iterations`, `propagate_stages`, `attachment_strategy`.
  - `Features` — `timestamp`, `file_loading`, `external_url_fetch`, `stage_display`, `dial_files`.
- Feature-specific shapes sit in siblings under `config/`, e.g. `config/dial_files.py` (`DialFilesConfig`), `config/orchestrator_attachment_strategy.py` (`LazyOnDemandAttachmentStrategy`).
- **Serialized JSON is ground truth**: `make dump_app_schema`, then read the dumped schema to confirm exact keys / discriminator values / nesting.

**How a field gates behavior** — read the module that consumes it to learn the ON/OFF semantics (e.g. `dial_files_tooling/dial_files_tooling_module.py` returns no tools when `features.dial_files is None`; the lazy strategy under `orchestrator_attachment_strategies/lazy_on_demand/` activates only when `attachment_strategy` is set).

**Model-metadata gate** — `src/quickapp/core/agent/orchestrator_capabilities.py` wraps the orchestrator deployment's DialCore metadata; `input_attachment_types` is the common gate (does the model accept attachments at all). This is the backend half of the FE conditional-visibility rule.

**Related issues:** `gh issue list --repo epam/ai-dial-quickapps-backend --search "<keywords> in:title,body" --state all`.

## Editor / FE — `epam/ai-dial-chat` (`apps/chat/`)

**Editor form & sections:**
- `apps/chat/src/components/AppsEditor/EditorForm/QuickApp2Form/QuickApp2Form.tsx` — the configurator. Sections are `FormCollapsibleSection`s (Orchestrator, Context & Tools, Agent Skills, User Attachments, Conversation Starters, Agent Settings).
- Section labels / i18n: `apps/chat/src/constants/i18n.ts` (`MarketplaceI18nKeys`, e.g. `ContextAndTools`, `ContextAndToolsDescription`).

**Config type (where the new field goes):**
- `apps/chat/src/types/quick-apps.ts` — `QuickApp2Config` (the serialized manifest: `orchestrator`, `features`, `contexts`, `tool_sets`, …).
- Form schema / validation: `apps/chat/src/components/AppsEditor/form.ts` (`QuickApp2Schema`) — boolean toggles like `timestamp`, `codeInterpreter`, `chatMessageInputDisabled` live here.

**Toggle pattern (reference for the FE dev, keep out of the issue body):**
- `apps/chat/src/components/Common/ToggleSwitch/ToggleSwitch.tsx`; used as `ToggleSwitchField = withLabel(ToggleSwitch)` inside a react-hook-form `Controller`. Existing examples: `timestamp`, `codeInterpreter` in `QuickApp2Form.tsx`.

**Model metadata (conditional visibility):**
- `apps/chat/src/types/models.ts` — `DialAIEntity` (has `inputAttachmentTypes?`, `maxInputAttachments?`, `features?`), `DialAIEntityModel` (extends it; adds `limits`, `tokenizer`, `mcp`, …), `DialAIEntityFeatures` (`temperature`, `systemPrompt`, `urlAttachments`, `folderAttachments`, `tools`, `mcp`, …).
- `apps/chat/src/utils/server/map-core-entity.ts` — maps DialCore's snake_case (`input_attachment_types`) → camelCase (`inputAttachmentTypes`).
- Read the selected model in a component via `ModelsSelectors.selectModelsMap` → `modelsMap[modelId]`; feature helpers in `apps/chat/src/utils/app/models.ts` (`doesModelAllowTemperature`, `doesAgentSupportMcp`, …).

## Templates & conventions

- Feature-request template: `.github/ISSUE_TEMPLATE/02_feature_request.yml` (ai-dial-chat) → Description / Use case/motivation / Related issues / Confidential information.
- Naming for planned editor work: `[Quick app 2.0] Feature: …`; labels `enhancement, to-be-documented`. Verify against live issues: `gh issue list --repo epam/ai-dial-chat --search "quick app in:title label:enhancement" --state all`.

## Worked examples (the bar to clear)

- `claude/issues/chat/orchestrator-large-files-toggle.md` → published as `epam/ai-dial-chat#7524` (model-gated toggle, Orchestrator section).
- `claude/issues/chat/file-tools-toggle.md` → published as `epam/ai-dial-chat#7525` (plain on/off toggle, Context & Tools section).
