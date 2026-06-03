---
name: quickapps-release-notes
description: Use when the user asks to enhance, refine, polish, or "look at" the release notes for a tag — typically a fresh CI-generated pre-release (e.g. `0.8.0-rc.1`) or a stable cut. Reads the auto-generated notes off the GitHub release, classifies and rewrites each bullet in this project's editorial voice, builds the `Deployment Changes` section from `README.md` / `CONFIGURATION.md` / PR bodies, and saves a draft to `claude/release-notes/`. When the target is a stable cut (e.g. `0.8.0`) and its `-rc.*` pre-releases already carry enhanced notes, it assembles the stable draft by merging those rc notes — reusing their approved wording — instead of re-deriving every bullet from the raw stable notes. Never edits GitHub directly.
allowed-tools: Read Grep Glob LSP Bash(gh release view:*) Bash(gh release list:*) Bash(gh pr view:*) Bash(gh pr list:*) Bash(gh pr diff:*) Bash(git log:*) Bash(git show:*) Bash(git diff:*) Bash(git tag:*) Bash(git rev-parse:*) Bash(date:*) Write(claude/release-notes/*) Bash(mkdir -p claude/release-notes)
argument-hint: "[tag]"
arguments: tag
model: opus
effort: xhigh
context: fork
agent: general-purpose
---

# QuickApps release-notes enhancer

The CI publishes a release for every tag with bullets that are just the PR titles. Those bullets carry a lot of dirt — conventional-commit prefixes (`feat:`, `fix(area):`), branch slugs (`async-dial-instead-of-dial-core-client`), misfiled items (a `feat(file-loader)` landing under `Other` because the title started with `feat(`), and a `## Other` section that mixes consumer-relevant items with pure internal refactors. The releases visible at `https://github.com/epam/ai-dial-quickapps-backend/releases` from `0.6.0` through `0.8.0-rc.0` are what those raw notes look like after a human editorial pass. This skill reproduces that pass.

You are running in a forked, isolated context. Read and research freely — only the final summary you return reaches the main conversation. All file writes happen in this fork; the draft lands at `claude/release-notes/<tag>-draft.md`.

## When to use

- "Enhance the release notes for `0.8.0-rc.1`"
- "Look at the latest pre-release notes and refine them"
- "Help me adjust release notes for the current rc"
- "The CI just published `<tag>`, make it readable"

Do **not** trigger on requests like "what changed in 0.7.0?" — that is a recall question, not a notes-editing task.

## Inputs

`tag` = `$tag` — the GitHub release tag to enhance (e.g. `0.8.0-rc.1`, `0.9.0`). If empty, pick the most recent tag from `gh release list --limit 5` and confirm with the user before editing.

## Mode selection

After resolving the tag, decide which path to follow:

- **Merge path** — the target is a **stable** `X.Y.Z` (no `-rc` suffix) *and* one or more `X.Y.Z-rc.*` pre-releases exist whose release bodies are **already enhanced**. A stable's notes are exactly the union of its pre-releases plus whatever landed after the last rc, and those rc bodies have already been through this editorial pass — so assemble the stable draft by merging them and reserve fresh work for the post-last-rc commits. This is what "enhance `0.8.0`" means once the rc notes are done. Follow the **Merge path** section below.
- **From-scratch path** — everything else: any `-rc.N` target, a stable with no pre-releases, or a stable whose rc bodies are still raw CI output. Process every bullet from the raw notes via the **Workflow** steps below.

To tell whether an rc body is enhanced or raw, sample one (`gh release view <X.Y.Z-rc.0> --json body`): enhanced bullets read as `* <Capitalized clause> — <why> #<issue> (#<PR>)` with `—` em-dashes, backticked identifiers, and `[Preview]` tags; raw CI bullets still carry conventional-commit prefixes (`feat:`, `fix(scope):`) or `snake_case_branch_slugs`.

## Workflow (from-scratch path)

These steps process every bullet from the raw GitHub notes. For a stable cut whose `-rc.*` notes are already enhanced, use the **Merge path** section instead (it reuses these steps only for the post-last-rc delta).

### 1. Resolve target and reference styles

1. `gh release view <tag> --json body,name,tagName` — capture the raw CI notes.
2. `gh release list --limit 10` — locate the previous tag of the same kind (last stable for a stable release, the predecessor `rc` for a delta `rc.N+1`).
3. `gh release view <prev-stable-tag> --json body` and `gh release view <prev-rc-tag> --json body` (when relevant) — these are the style anchors. The user has repeatedly insisted **"keep the same format as the latest stable release"** and **"your notes are too verbose"** — match the terseness of those notes, not your own instincts. One line per bullet.
4. `git tag --list | sort -V` + `git log <prev-tag>..<tag> --oneline` — full commit list for the range, so you can spot hotfix commits the CI dropped because they had no PR.

### 2. Pull source context for each bullet

For every bullet in the raw notes:

1. Parse out the trailing `#<issue> (#<PR>)` or `(#<PR>)`. If only a PR number is present, that's the canonical reference; if both, keep `#<issue> (#<PR>)` order.
2. `gh pr view <PR> --json title,body,labels` — read the PR body, not just the title. The body is where the *why* and the *what-it-replaces* live; the title is usually too compressed.
3. For bullets without a PR number (`* fix tests`, `* application mcp endpoint path`, `* Merge remote-tracking branch ...`), find the commit with `git log <prev-tag>..<tag> --oneline | grep -i <keywords>` and `git show <hash>` — these are usually hotfix commits that should fold into a related entry, not stand alone.
4. If a PR body references a doc under `docs/designs/` or `docs/`, skim it for the headline framing.

### 3. Cross-check `README.md` / `CONFIGURATION.md` / source for deployment changes

The `Deployment Changes` section is built from primary sources, not PR titles:

- `git diff <prev-tag>..<tag> -- README.md CONFIGURATION.md` — env-var additions/removals/renames.
- For any env var that lands in the section, verify the **canonical name** by reading the actual settings class via LSP (`goToDefinition` on the field, or `Grep` the codebase). Past releases have caught typos like `file_loader` vs the canonical `file_loading` this way — the PR body said one thing, the code said another, code wins.
- Confirm defaults and bounds by reading the settings class.

### 4. Classify each bullet (move things between sections, drop the noise)

The raw notes' `## Features` / `## Fixes` / `## Other` partition is unreliable because CI keys it off the conventional-commit prefix in the PR title. Reclassify by the change's actual user impact:

| Where CI put it | Where it belongs | Rule |
|---|---|---|
| `Other` starting with `feat(...)` | `Features` | A feat that lost its slot to a scope prefix. |
| `Other` starting with `fix(...)` | `Fixes` | Same, for fix. |
| `Features` / `Fixes` for a pre-release-only regression | `Fixes` with note "(affects pre-release users of \<feature\> only)" | Don't surface a transient bug as a feature. |
| `Other` for a security CVE bump | `Fixes` | Security items are user-relevant. |
| Multiple PRs / hotfix commits on one feature | one folded entry under the appropriate section | Cite the commit hashes or PR numbers in parens. |

**Drop these from the notes entirely** — they have no consumer-visible effect:

- Pure renames of internal classes (`chore: rename CompletionResult to ToolCallResult`).
- Package re-layouts (`chore: split common exceptions into a package`).
- Internal pipeline refactors (`chore: make … pipelines async`, `chunk processing refactoring`).
- Client-library swaps that don't change behavior (`async-dial-instead-of-dial-core-client`).
- Claude Code agent setup / docs / skill scaffolding (`init claude documentation`, `add design review skill`).
- Integration-test additions or test-module realignments that don't change product behavior.
- `Merge remote-tracking branch …` commits.
- CI-only changes (release-candidate branching) **unless** a maintainer needs to know — then keep under `Other` with a one-line rationale.

**Keep in `Other`** — items maintainers or operators care about even if they're not features:

- Security-adjacent dependency bumps (`bump authlib`, `bump urllib3`).
- Forwarded-headers / auth-handling checks.
- Issue templates, tech-debt template (visible to contributors).

If you find yourself unsure whether to drop a bullet, ask: *would a customer reading these notes care that this happened?* If no, drop it.

### 5. Rewrite each kept bullet

The raw form is `* <conventional-prefix>: <branch-slug> #<issue> (#<PR>)`. Rewrite to:

```
* <Active-voice description of what changed> — <brief why-it-matters or what-it-replaces> #<issue> (#<PR>)
```

Rules in order of importance:

1. **One line per bullet.** No multi-paragraph descriptions. The user has explicitly flagged "too verbose" in prior runs. If you need more detail, save it to the companion editorial-notes file (see §8), not the main draft.
2. **Drop the conventional prefix** (`feat:`, `fix:`, `chore:`, `fix(time-awareness):`). Replace with prose.
3. **Drop branch-style slugs.** `async-dial-instead-of-dial-core-client` → `Replace dial-core client with async-dial`. The PR title is the prompt, not the output.
4. **Use a `—` em-dash for the "why" clause**, not a hyphen or colon — that's the consistent house style across 0.6.x–0.8.x.
5. **Backticks for code identifiers**: env vars (`DEFAULT_TOOL_TIMEOUT_SECONDS`), file paths, config field names (`features.timestamp`), class names, schema keys.
6. **Preserve issue + PR refs at the end** in `#<issue> (#<PR>)` order, or `(#<PR>)` when there is no issue. Don't strip them — these notes ship as the GitHub release body where the numbers auto-link.
7. **Prefix with `[Preview]`** for preview-gated features.
8. **Flag regressions explicitly**: `(regression fix)` for items restoring previously-working behavior.
9. **Quote CVE IDs verbatim** for security upgrades: `Upgrade musl to 1.2.5-r23 to address CVE-2026-40200`.
10. **For features that graduate to GA**, lead with `Graduate <feature> to GA — <gate that's removed>`.

#### Example transformations

Each pair is `raw CI` → `enhanced`. Backticks in the enhanced form denote code identifiers in the actual output.

```
# Adding a "what changed" clause and the [Preview] tag:
- * DIAL prompts as skills #229 (#230)
+ * [Preview] Configure agent skills sourced from DIAL prompts via the new `skills` config field #229 (#230)

# Replacing a vague title with the concrete mechanism, dropping `feat:`:
- * feat: Remove hash from tool naming #200 (#206)
+ * Deterministic, human-readable tool names — replaces SHA-256 hash suffixes with `{toolset_name}_{tool_name}` prefixing #200 (#206)

# Removing `fix:` and the bare `(253)` mistake, restoring the issue ref:
- * fix: add forwarding the auth token to orchestrator model (253) (#254)
+ * Forward the incoming request's auth token to the orchestrator model #253 (#254)

# Marking a regression fix and naming the precise gap:
- * restore bearer token forwarding for deployment tools (#250)
+ * Restore bearer-token forwarding for DIAL deployment tools and tolerate a missing `Authorization` header (regression fix) (#250)

# Graduations: lead with "Graduate <X> to GA" and name the lifted gate:
- * graduate Time Awareness feature to GA (#290)
+ * Graduate Time Awareness feature to GA — `features.timestamp` is no longer gated by `ENABLE_PREVIEW_FEATURES` #288 (#290)

# Reclassified (raw had it in Other because of `feat(scope):` prefix):
- * feat(file-loader): make agent file download size limit configurable (#274)
+ * Configurable agent file-download size limit — replaces the hardcoded 10 MiB cap in `DialFileService` with `DEFAULT_FILE_LOADING_SIZE_LIMIT` (deployment-wide) and `features.file_loading.size_limit` (per-app override) (#274)

# Folded orphan hotfix commits into a related fix entry:
- * application mcp endpoint path     (orphan commit, no PR)
- * fix tests                          (orphan commit, no PR)
+ * Correct DIAL App MCP endpoint path — `DialAppToolSet`'s MCP branch was hitting `/v1/toolset/{id}/mcp`; corrected to `/v1/deployments/{id}/mcp` (affects pre-release users of the new `dial-app` toolset only) (`eb664c0`, `1500580`)
```

### 6. Build the `Deployment Changes` section

Add this section **only** when the range introduces at least one env-var, behavioral, or schema change. Pick subsections — include only the ones with entries:

```markdown
## Deployment Changes

### New environment variables
<table: Variable | Default | Description>

### Deprecated environment variables
> [!CAUTION]
> Still works, but will be removed in future versions.
<table: Variable | Replacement | Description>

### Removed environment variables
<table: Variable | Reason>

### Behavioral changes
> [!NOTE]
> <one-line explaining the behavioral shift, e.g. preview→GA graduations>
- **<Feature>** — <field / module> (#<PR>)

### DIAL Configuration changes
> [!IMPORTANT]
> <one-line stating the operator-facing change>
>
> **Required migration** (#<PR>):
>
> 1. **Remove** <the legacy config block in DIAL Core / external system>.
> 2. **Add** <the new config block(s)> to <exact location, e.g. `applicationTypeSchemas` entry>. Apply the snippet from PR #<PR> verbatim.

**Don't enumerate sub-properties of a single block.** Name the top-level config key the operator is pasting in — and stop there. Inner fields, nested sub-properties, or values that ship inside that block are not separate operator actions; they are payload the operator gets for free by copying the snippet. Mentioning them at the same level as the parent block misleads the reader into thinking they are independent additions. If a key matters enough to flag, it must be a peer of the block being added — verify nesting against the actual schema snippet (read the PR diff) before listing it.

### Schema deprecations
> [!CAUTION]
> Still accepted in app manifests, but will be removed in future versions (#<PR>).
<table: Legacy key | Replacement | Affected config model>
```

#### Which subsection: telling Behavioral, DIAL Configuration, and Schema deprecations apart

These three look adjacent but answer different operator questions:

- **Behavioral changes** — *"How does the deployed QuickApps service behave differently at runtime?"* Preview→GA graduations, default values changing, error-handling shifts. Operator does nothing; the change is automatic on upgrade. Uses `> [!NOTE]`.
- **DIAL Configuration changes** — *"What must I change in DIAL Core's configuration (or another external system) for this release to work?"* Schema/route migrations that operators must apply by hand outside this repo. Uses `> [!IMPORTANT]` and a numbered **Required migration** list with literal config keys. Don't bury this in Behavioral changes — operators will miss it.
- **Schema deprecations** — *"What keys in the app manifest are being renamed/removed?"* Inside-repo schema evolution; the JSON schema still accepts legacy keys via aliases. Uses `> [!CAUTION]` and a table.

If a change requires the operator to touch a config file outside this repo (DIAL Core's `aidial.config.json`, an `applicationTypeSchemas` block, helm values), it belongs in **DIAL Configuration changes** with a concrete remove/add migration list, never in Behavioral changes.

**Crucial — what does *not* belong here**: app-config-only fields (per-app `features.*` overrides, new manifest fields). Those changes belong in the **Features** bullet body where they're introduced. `Deployment Changes` is for operator-facing concerns: env vars, behavioral shifts, external-config migrations, schema-level deprecations. The user explicitly dropped an "App config additions" subsection during the `0.7.0-rc.0` pass with the message *"app config - not deployment changes. drop it"* — respect that boundary.

For the env-var tables, the description column comes from `CONFIGURATION.md` when it exists there; otherwise from the settings class docstring. Cite bounds (`> 0`, `0 < x ≤ 3600`) verbatim from the validator.

### 7. Pre-release / delta handling

If the target is `<X.Y.Z>-rc.N` with `N ≥ 1`:

- The release covers only what changed since the previous rc — do **not** consolidate or rewrite the predecessor's notes. Each pre-release tag has its own GitHub release page; the consolidation happens at the stable cut (see the **Merge path** section).
- Drop sections that have no entries in the delta (e.g. no `Deployment Changes` if no env vars or schema changes landed in this rc).
- Do **not** prepend a "Delta since <prev-rc>" pointer at the top. The CI doesn't emit one, the previously-shipped rc notes don't carry one, and the `-rc.N` version suffix already signals what the release is. Adding a header just creates editorial noise the user has to clean up.

### 8. Save the draft (and optional editorial companion)

Create `claude/release-notes/` if missing, then write:

- **`claude/release-notes/<tag>-draft.md`** — the final notes, ready to paste into the GitHub release body. No preamble, no commentary — just the headings and bullets.
- **`claude/release-notes/<tag>-editorial-notes.md`** *(optional)* — only when there are non-obvious calls worth surfacing to the user:
  - Rename mapping (raw bullet → enhanced bullet) for items where the rewrite is non-trivial.
  - List of items dropped, with one-line reason per item.
  - Open questions for the user (e.g. "Should `#236` CI workflow PR stay under Other? It's invisible to consumers but visible to release maintainers.").
  - Any place the source-of-truth diverged from the PR body (e.g. canonical env-var name).

### 9. Verify nothing was pushed to GitHub

This skill **never** runs `gh release edit`, `gh release create`, or any write operation against the repo. The user explicitly directed: *"Everything should be drafted in local files. Don't push anything or change anything in GitHub."* Draft files are the only output. If the user later asks you to apply, that is a separate, explicit request.

## Merge path — assembling a stable cut from enhanced rc notes

A stable `X.Y.Z` ships exactly what its `X.Y.Z-rc.*` pre-releases shipped, plus whatever landed between the last rc and the stable tag. Each rc release body has **already** been through this skill — every bullet is classified, rewritten, and deduped within its own delta. Re-deriving all of that from the raw stable notes throws away wording the user already approved and invites drift. So reuse the rc bullets and reserve fresh work for the post-last-rc commits only.

The raw stable GitHub notes still matter here — not as a bullet source, but as the authoritative **inventory** of what's in the release, so you can prove nothing slipped through the merge.

### M1. Gather the rc chain and the stable inventory

1. `gh release list --limit 30` — every `X.Y.Z-rc.*` tag for this version (ordered `rc.0`, `rc.1`, …) and the previous stable `X.Y'.Z'`.
2. `gh release view <X.Y.Z-rc.N> --json body` for each rc — these enhanced bodies are the bullet source.
3. `gh release view <X.Y.Z> --json body` — the raw stable notes, used as an inventory checklist. Skip if the stable release isn't published yet and use the git range below as the inventory instead.
4. `git log <prev-stable>..<X.Y.Z> --oneline` (full range) and `git log <last-rc>..<X.Y.Z> --oneline` — the second is the **post-last-rc delta**, the only commits no rc has seen.

### M2. Confirm the rc bodies are enhanced

Sample each (see *Mode selection* for the enhanced-vs-raw tell). If one rc is still raw, enhance that rc's delta first — Steps 2–6 over `git log <prev-rc>..<rc>` — before merging it. If most rcs are raw, abandon the merge and run the whole from-scratch **Workflow** on the stable instead.

### M3. Union the bullets

Collect the `Features`, `Fixes`, and `Other` bullets from every rc body. **Copy the enhanced wording exactly — do not re-fetch the PR or rewrite it.** The editorial work is already done; your job is assembly, not re-authoring. Preserve each bullet's trailing `#<issue> (#<PR>)` references character-for-character as the rc wrote them — don't re-parenthesize, reorder, or normalize them (a stray `#283` → `(#283)` is exactly the kind of drift that creeps in when copying by eye).

For ordering, follow the established stable layout rather than a rigid rc-by-rc concatenation: lead with `[Preview]` and headline features, keep related items together, and place GA graduations and minor enhancements last. Ordering is low-stakes and the user reviews it — don't agonize, but don't fragment the list strictly by rc either.

### M4. Deduplicate and consolidate across the rc boundary

The rcs were edited in isolation, so the union needs reconciliation:

- **A feature touched by more than one rc** — introduced in one rc, refined in a later one (same `#PR`/`#issue`, or a follow-up PR on the same feature) — collapses to one bullet with the most complete wording. Cite both PR numbers in parens when each carried real change.
- **Pre-release-only regression fixes → drop.** When an rc bullet fixes something that broke *within this version's own pre-release cycle* — it carries an `(affects pre-release users of <feature> only)` marker, or it's an orphan `hotfix:` commit patching a feature first shipped in an earlier rc of this same version — leave it out. A consumer upgrading from the previous stable never saw the broken intermediate state, so that feature's own bullet already describes the working result. Fixes for bugs that existed in the *previous stable* are real fixes — keep those. *Example: the `dial-app` toolset shipped in rc.0 and an endpoint-path hotfix corrected it before stable; the stable notes describe the working toolset and omit the hotfix.*
- **Merge the `Deployment Changes` subsections** — union all `New environment variables` rows into one table; carry over every `DIAL Configuration changes` migration and `Schema deprecations` table; combine `Behavioral changes` into a single block. If two rcs list the same env var with different defaults or descriptions, reconcile to one row and verify the canonical name/default from source (§6 rule — code wins over PR bodies).

### M5. From-scratch pass on the post-last-rc delta only

For the commits in `git log <last-rc>..<X.Y.Z>` (M1.4), run Steps 2–6 of the from-scratch **Workflow** — parse refs, read PR bodies, classify, drop the noise, rewrite, and pull any new deployment changes — then fold the survivors into the unioned sections and tables. If the delta is empty, skip this step; the merge is just the reconciled rc union.

### M6. Reconcile against the stable inventory

Walk every PR/issue number in the raw stable notes (M1.3). Each must resolve to exactly one of:

- **kept** — present in the unioned rc bullets,
- **new** — handled by the M5 delta pass, or
- **dropped** — an internal item the rc passes already excluded. Re-apply §4's drop rules, and **don't resurrect** something the rcs deliberately left out just because it's missing from the union (those internal refactors were dropped on purpose, not overlooked).

Anything that fits none of these three is a genuine gap — surface it in the editorial companion rather than guessing.

### M7. Save

Write the assembled notes to `claude/release-notes/<tag>-draft.md` in the standard Output format. In `claude/release-notes/<tag>-editorial-notes.md`, record: the rcs merged (tag → bullet counts), cross-rc dedup/folds, pre-release-only fixes dropped, post-last-rc delta items added, and any inventory gaps from M6.

## Output format

The file saved to `claude/release-notes/<tag>-draft.md` follows this shape exactly:

```markdown
## Features

* <one bullet per change>

## Fixes

* <one bullet per change>

## Other

* <only consumer- or maintainer-relevant items>

## Deployment Changes

### New environment variables
<table>

### Deprecated environment variables
> [!CAUTION]
> …
<table>

### Behavioral changes
> [!NOTE]
> …
- <item>

### DIAL Configuration changes
> [!IMPORTANT]
> …
>
> **Required migration** (#<PR>):
> 1. **Remove** …
> 2. **Add** … Apply the snippet from PR #<PR> verbatim.

### Schema deprecations
> [!CAUTION]
> …
<table>
```

Section order: `Features` → `Fixes` → `Other` → `Deployment Changes`. Subsections inside `Deployment Changes` appear in the order: New env vars → Deprecated env vars → Removed env vars → Behavioral changes → DIAL Configuration changes → Schema deprecations.

A delta `rc` release uses the same shape — no preamble paragraph, no header pointing at the previous rc. A merged stable cut (**Merge path**) uses this same shape too; it just sources its bullets from the rc notes plus the post-last-rc delta rather than from the raw stable notes.

## Return to the main conversation

Return a short summary — five lines or fewer. Include:

- The draft path (`claude/release-notes/<tag>-draft.md`).
- Counts of bullets per section after enhancement.
- Reclassifications that happened (e.g. "moved 2 from Other → Features, 1 from Other → Fixes").
- Items dropped (count, with one example).
- Whether a `Deployment Changes` section was added and which subsections.
- Any open questions for the user (env-var name disagreement between PR body and source, ambiguous categorization).

For a **Merge path** run, report instead: which rcs were merged, the section counts after merging, cross-rc dedup/folds, pre-release-only fixes dropped, and what the post-last-rc delta added (or that it was empty).

Example (from-scratch):

> Drafted `claude/release-notes/0.8.0-rc.1-draft.md`. 5 Features, 3 Fixes, 4 Other. Reclassified 1 from Other → Features (`feat(file-loader)`) and 1 from Other → Fixes (`fix(time-awareness)`). Dropped 3 internal items (rename, package split, merge commit). Added Deployment Changes with New env vars + Behavioral changes (Time Awareness GA). One open: PR body says `file_loader` but code calls it `file_loading` — used the code name; flagged in editorial notes.

Example (merge):

> Drafted `claude/release-notes/0.8.0-draft.md` by merging rc.0 (6F/4Fx/6O), rc.1 (7F/3Fx/2O), rc.2 (2F). Result: 15 Features, 7 Fixes, 8 Other. Merged 3 env-var rows into one table; combined Behavioral changes (Time Awareness + DIAL Prompt Skills GA) and carried over the #319 DIAL Configuration migration and the #287 schema deprecations. Dropped the `dial-app` endpoint-path hotfix (pre-release-only). Post-rc.2 delta was empty. One open: #304 `prefetch orchestrator capabilities` — kept or internal? flagged in editorial notes.

## Safety rails

- **Never edit GitHub.** No `gh release edit`, no `gh release create`. Drafts only.
- **Never invent items.** Every kept bullet maps to a PR or a commit hash in the range.
- **Never silently rename or drop a PR reference.** The bullet ends with the canonical `#<issue> (#<PR>)` so links resolve on the release page.
- **Verify canonical names from source**, not from PR bodies. Past PR descriptions have used pre-rename names; the code is the source of truth.
- **Each rc page stands alone; the stable cut consolidates them.** When the target is a `-rc.N`, never pull sibling-rc notes into it. When the target is the **stable cut** and the rc notes are already enhanced, merging them is the expected path (**Merge path**) — but only ever write the local stable draft; never edit or overwrite the individual rc release pages on GitHub.
- **Match the terseness of the predecessor's notes.** If they're one-liners, your bullets are one-liners. The user has flagged verbose drafts twice; defer to the established style.

## Maintenance

Conventions drift as the project grows. If you notice a pattern in the raw CI notes that this skill doesn't handle (a new section the CI emits, a new conventional-commit scope that misroutes items, a recurring rewrite the user keeps asking for), surface it in your return summary and offer to update this `SKILL.md`. The user can confirm before any edit lands.
