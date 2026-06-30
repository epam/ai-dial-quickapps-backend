---
name: quickapps-editor-issue
description: Use when the user wants to draft or file a GitHub feature-request issue for the Quick Apps 2.0 **editor** — the no-code app-builder UI that lives in the epam/ai-dial-chat repo ("create an issue for the quickapps editor", "draft a chat feature request for quick apps", "file an editor issue for the X toggle", "/quickapps-editor-issue"). Reach for it whenever a backend QuickApps capability needs an editor surface (a new toggle/field in the configurator) and the issue should follow ai-dial-chat's feature-request template, the `[Quick app 2.0] Feature: …` naming, a Config-mapping JSON snippet, and cross-repo references to ai-dial-quickapps-backend issues — even if the user only says "we should expose X in the editor".
allowed-tools: Read Grep Glob LSP Write Edit AskUserQuestion Bash(gh issue list:*) Bash(gh issue view:*) Bash(gh issue create:*) Bash(gh issue edit:*) Bash(gh repo view:*) Bash(git remote:*) Bash(make dump_app_schema:*)
argument-hint: "[feature description]"
arguments: feature
model: opus
effort: high
---

# quickapps-editor-issue

Turn a QuickApps **backend capability** into a crisp, conceptual **feature request for the editor** (the Quick Apps 2.0 configurator UI in `epam/ai-dial-chat`). The job is almost always the same shape: the backend already supports something (an attachment strategy, a file-tools feature, an external-fetch flag), but there's no control for it in the editor, so a builder can only enable it by hand-editing the app's JSON. This skill produces the issue that asks the FE team to add that control — investigated, correctly named, with the exact config the toggle must write.

The hard part isn't the prose — it's getting the **contract** right: which backend config field the control maps to, the exact ON/OFF JSON, whether visibility is gated on the orchestrator model's metadata, and which editor section it belongs in. Investigate both repos before writing a word.

## Two repos

| Role | Repo | Local source |
|---|---|---|
| **Backend** (config models, the capability) | `epam/ai-dial-quickapps-backend` | this repo — `src/quickapp/` |
| **Editor / FE** (where the issue is filed) | `epam/ai-dial-chat` | must be available locally (e.g. user ran `/add-dir …/ai-dial-chat`) |

If the `ai-dial-chat` working dir isn't available, say so and ask the user to add it — the FE mapping (section, config type, model-metadata signal) can't be verified without it, and a guessed mapping is worse than none.

## This skill files a real, public GitHub issue

Creating an issue is outward-facing and notifies watchers. **Always draft first, show the user the full draft, and get a confirmation before `gh issue create`.** Invoking the skill is permission to *investigate and draft*; it is not blanket permission to publish until the user okays the draft (or explicitly said "create it"). Drafts are cheap and revisable; published issues are not.

## When to use

- "Create / draft / file an issue (or feature request) for the QuickApps editor", or `/quickapps-editor-issue`.
- A backend feature shipped (or is shipping) and needs an editor toggle/field, e.g. "let builders turn on X from the configurator".

Do **not** use this for: backend issues (those go in `ai-dial-quickapps-backend` with a different template — see [`mcp-session-persistence.md`](../../../claude/issues/mcp-session-persistence.md) for that style), bug reports, or PRs (`quickapps-create-pr`).

## Workflow

Copy this checklist into your response and tick as you go:

```
Editor-issue progress:
- [ ] Clarified the feature (control, default, scope, editor section)
- [ ] Backend: config field + exact ON/OFF JSON found
- [ ] Backend: model-metadata gate identified (or confirmed none)
- [ ] Backend: related issues found (gh search)
- [ ] FE: editor section + QuickApp2Config field + model-metadata signal confirmed
- [ ] Draft written to claude/issues/chat/<name>.md (template + naming + Config mapping)
- [ ] User confirmed the draft
- [ ] Issue created with gh; refs/labels/section verified; local draft synced
```

Consult [`references/repo-map.md`](references/repo-map.md) for the concrete file locations in both repos — but treat them as starting points and confirm with LSP/Grep, since both codebases move.

### 1. Clarify the feature

Pin down, asking only what's genuinely ambiguous (infer the rest from the backend):
- **The control**: a toggle (most common), a field, a selector?
- **Default state** (e.g. off by default) and **scope** — what's in scope *now* vs deferred. Builders and reviewers care a lot about "just the on/off switch, per-option selection later".
- **Editor section** it belongs in: Orchestrator · Context & Tools · Agent Skills · User Attachments · Conversation Starters · Agent Settings. State it explicitly in the issue — reviewers triage by section.

### 2. Investigate the backend (this repo)

Find the **config field** the control maps to and its **exact JSON shape**. Config models are Pydantic under `src/quickapp/config/` — `application.py` holds `ApplicationConfig` → `OrchestratorConfig` and `Features`; feature-specific shapes live in siblings (e.g. `dial_files.py`, `orchestrator_attachment_strategy.py`). Use LSP `goToDefinition`/`findReferences`, not guesswork. When unsure of the serialized key, the generated app schema is ground truth (`make dump_app_schema`, then read the dumped schema).

Determine:
- **ON value and OFF value** — the precise field path and value. A discriminated model serializes as `{ "type": "<discriminator>" }`; an absent feature is usually `null`/omitted. Trace how the backend reads it (often "field present → feature on; `None` → off").
- **Model-metadata gate** — does the capability only work for certain orchestrator models? Look for reads of the orchestrator deployment's DialCore metadata (e.g. `input_attachment_types` via `core/agent/orchestrator_capabilities.py`). If so, that becomes the FE's **conditional-visibility** rule.
- **Maturity** — is it a `PreviewField`? If yes, ask the user whether to frame the issue as GA or preview; preview status changes over time, so don't assert it on your own.
- **Related backend issues** to reference:
  `gh issue list --repo epam/ai-dial-quickapps-backend --search "<keywords> in:title,body" --state all --limit 15 --json number,title,state`
  Open the strongest 2 with `gh issue view` and confirm they actually motivate or define the feature before citing them.

### 3. Map it to the editor (ai-dial-chat)

Confirm three things in the FE so the issue is actionable (see [`references/repo-map.md`](references/repo-map.md) for paths):
- **Section** — the `FormCollapsibleSection` in `QuickApp2Form.tsx` and its i18n key (e.g. `ContextAndTools`).
- **Config type** — the field's home in `QuickApp2Config` (`apps/chat/src/types/quick-apps.ts`): the `orchestrator` object, or `features`, etc.
- **Model-metadata signal** (only if step 2 found a gate) — the FE field that mirrors the backend one. Backend `input_attachment_types` surfaces as `inputAttachmentTypes` on the model entity (`apps/chat/src/types/models.ts`, mapped in `utils/server/map-core-entity.ts`); the selected model is `modelsMap[modelId]` via `ModelsSelectors.selectModelsMap`. Phrase the rule against that, e.g. *show only when `modelsMap[modelId]?.inputAttachmentTypes?.length`*.

Note the toggle pattern (`ToggleSwitchField` + react-hook-form `Controller`; see existing `timestamp` / `codeInterpreter`) so the FE dev has a reference — but keep FE implementation detail out of the issue body itself.

### 4. Draft the issue → `claude/issues/chat/<descriptive-kebab>.md`

Follow ai-dial-chat's **feature-request template** (`.github/ISSUE_TEMPLATE/02_feature_request.yml` in that repo) — sections **Description**, **Use case/motivation**, **Related issues**, **Confidential information**. Conventions this team expects:

- **Title / H1**: `[Quick app 2.0] Feature: <concise summary>`. This is the repo's convention for planned editor work — confirm it still holds: `gh issue list --repo epam/ai-dial-chat --search "quick app in:title label:enhancement" --state all`.
- **Labels line**: `**Labels:** enhancement, to-be-documented`.
- **Short and conceptual.** Describe behavior and the *why*; name the section; state the ON/OFF effect. Don't paste FE code or file paths into the body.
- **Conditional visibility**: if model-gated, state it plainly (the rule from step 3).
- **Config mapping section** — the part FE devs rely on. Give the exact field and ON/OFF JSON:

  ````markdown
  ## Config mapping

  The toggle reads/writes a single field in the app config (the Quick App 2.0 manifest): `orchestrator.attachment_strategy`.

  **On:**

  ```json
  { "orchestrator": { "attachment_strategy": { "type": "lazy_on_demand" } } }
  ```

  **Off (default):** omit `orchestrator.attachment_strategy` (equivalently, set it to `null`).

  FE: add the field to the `orchestrator` object in `QuickApp2Config`[, and gate visibility on `modelsMap[modelId]?.inputAttachmentTypes?.length`].
  ````
- **Use case/motivation**: one or two sentences — don't write an essay. Lean on the referenced backend issues to carry the context.
- **Related issues**: cross-repo references, one line each:
  `epam/ai-dial-quickapps-backend#179 — <title>: <why it's relevant>`.
  **Always use the full `epam/ai-dial-quickapps-backend#NNN` form**, never bare `#NNN` — a bare number resolves to an ai-dial-chat issue and points at the wrong thing. Both repos are public, so the full form autolinks. Close with: *"Depends on existing backend support for … — no backend change required."*

Worked examples (read these — they're the bar): [`orchestrator-large-files-toggle.md`](../../../claude/issues/chat/orchestrator-large-files-toggle.md) and [`file-tools-toggle.md`](../../../claude/issues/chat/file-tools-toggle.md).

### 5. Create the issue (after the user confirms)

Write a **body file** that strips the H1 title and the `**Labels:**` line (those go to `--title` / `--label`), promotes the section headings to `###` to match the template's rendered form, and keeps the Confidential checkbox. Put it in the scratchpad, not the repo.

```bash
gh issue create \
  --repo epam/ai-dial-chat \
  --title '[Quick app 2.0] Feature: <summary>' \
  --label "enhancement,to-be-documented" \
  --body-file <scratchpad>/issue-body.md
```

Then **verify**: `gh issue view <n> --repo epam/ai-dial-chat` — confirm the `epam/ai-dial-quickapps-backend#NNN` refs resolved, the labels and section read right, and the JSON renders. Keep the local draft in `claude/issues/chat/` in sync with what was published, and report the URL.

To revise an already-published issue, edit the body file and `gh issue edit <n> --repo epam/ai-dial-chat --body-file …`.

## Red flags — stop and reconsider

| Thought | Reaction |
|---|---|
| "I'll reference `#179`" | Bare `#179` = an ai-dial-chat issue. Use `epam/ai-dial-quickapps-backend#179`. |
| "I'll guess the config field / JSON" | No — read the Pydantic model (and `make dump_app_schema` if unsure). The ON/OFF JSON is the contract. |
| "The FE repo isn't added, I'll infer the mapping" | Stop and ask for it. A wrong section/type is worse than asking. |
| "Title: `🚀 Feature request: …`" | That's the community style. Planned editor work uses `[Quick app 2.0] Feature: …`. |
| "Let me explain the motivation in three paragraphs" | Keep it to 1–2 sentences; lean on the referenced backend issues. |
| "It's a PreviewField, I'll call it preview" | Confirm with the user — maturity changes; don't assert it unprompted. |
| "I'll just create it, they asked for an issue" | Draft → show → confirm → create. Publishing is outward-facing. |
| "The capability needs no model" | Check for a model-metadata gate; if there is one, the toggle must be conditionally shown. |

## Common mistakes

- **Bare `#NNN`** in Related issues — silently points at the wrong repo.
- **Config snippet drift** — the JSON in the issue doesn't match the actual model (wrong key, wrong nesting, missing discriminator). Verify against the schema.
- **Missing the section** — reviewers triage by editor section; always name it.
- **Essay-length motivation** — this team prefers references over prose.
- **Stale preview framing** — a feature that went GA still described as preview (or vice-versa).
- **Publishing without confirmation** — always land the draft with the user first.
