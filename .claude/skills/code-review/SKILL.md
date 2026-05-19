---
name: code-review
description: Use before creating a PR or claiming a change is ready (or on explicit user invocation). Self-reviews the current diff against the patterns this team's reviewers consistently flag.
allowed-tools: Read Grep Glob LSP Bash(git diff:*) Bash(git log:*) Bash(git show:*) Bash(git status:*) Bash(git rev-parse:*) Bash(date:*) Bash(gh pr view:*) Bash(gh pr diff:*) Bash(gh pr list:*) Write(docs/reviews/*) Bash(mkdir -p docs/reviews)
argument-hint: "[pr|uncommitted]"
arguments: scope
model: opus
effort: xhigh
context: fork
agent: general-purpose
---

# code-review

Self-review the current diff against the recurring feedback this team's reviewers actually leave. Catches it before they do.

## When to use

- Before `gh pr create`
- After finishing a feature or fix, before claiming "done"
- When the user explicitly asks for a "review", "self-review", or "pre-submit check"

## Arguments

`scope` = `$scope` (one of `pr` | `uncommitted`; if empty, default to `pr`):
- `pr` — review **only committed** changes on the current branch vs `development`. Use exactly:
  `git diff development...HEAD`
  **Do not** run plain `git diff` (no revision range), `git diff --staged`, or include `git status` output. Uncommitted/unstaged files are out of scope.
- `uncommitted` — review **only** working-tree + staged changes (not yet committed). Use exactly:
  `git diff HEAD`
  Do not include committed changes from the branch.

If the resolved diff is empty (or whitespace-only), report **"nothing to review"** and stop — do not write a review file.

## How to run

1. Resolve the diff using **only** the command listed for `$scope` above. If `$scope` is empty, treat it as `pr`. Never mix scopes in one run.
2. Walk the checklist below **per file changed**. For each hit, report: file:line, the rule, and a concrete suggested fix.
3. Group findings as **Blocking** (would get a "change requested") vs **Nit** (would get a `nit:` tag). Render each finding as a markdown checkbox (`- [ ]`) so they can be ticked off as they are addressed.
4. End with a short verdict: ship / fix-then-ship / split.
5. **Save the review** to `docs/reviews/<branch>__<YYYYMMDD-HHMM>.md`:
   - `<branch>`: current branch from `git rev-parse --abbrev-ref HEAD`, with `/` replaced by `-`. Keep prefixes (`feat-`, `fix-`, `chore-`) as-is.
   - `<YYYYMMDD-HHMM>`: short local datetime from `date +%Y%m%d-%H%M`.
   - Create `docs/reviews/` if missing, then write the file (both pre-approved).
   - Surface the review in the chat too — don't rely on the file alone.

When verifying field existence (§9) or whether an identifier still exists after a rename (§6, §8), prefer LSP (`hover`, `goToDefinition`, `findReferences`) over re-reading files. This skill is read-only; navigation tools are too.

Do NOT auto-apply fixes unless the user asks — surface them first.

## The checklist

The single most common review comment is some form of **"why is this here?"** — apply that lens to every new file, field, parameter, import, and comment.

### 1. Necessity — "why is this here?"
- [ ] Any new field, parameter, import, file, or comment that isn't load-bearing? Delete it.
- [ ] Unused subclass parameter required by parent interface? Mark intent explicitly (e.g. `del param`) — don't silently leave it.
- [ ] Self-explanatory code annotated with a redundant comment? Drop the comment.
- [ ] Redundant control flow (e.g. `else` after a branch that already returns/handles)? Drop it.

### 2. PR scope
- [ ] Diff contains unrelated renames, refactors, test scaffolding, or fixtures? Split into a separate PR.
- [ ] Whitespace-only or "replace all" bleed in schemas / design docs? Revert those hunks.

### 3. Module boundaries / imports
- [ ] Upward imports against the documented dependency direction (shared layers must not import from feature layers)? Fix the direction. *Example: `common/` importing from `agent/`.*
- [ ] Reaching into a dependency's internals when its public API exposes the same symbol? Prefer the public surface — even when the internal is re-exported.
- [ ] Sibling feature modules importing each other? Extract shared code into a shared layer.

### 4. DI / Injector
- [ ] Service instantiated directly (`Foo()`) where another site injects it? Unify on constructor injection.
- [ ] New DI binding added? It must be wired into **every** assembly point (prod entry + integration-test container).
- [ ] Duplicate bindings of the same protocol/type? Pick one.

### 5. Settings
- [ ] Any `os.getenv` in app code? **Reject.** Move to a `pydantic-settings` `BaseSettings`. To check if an env var was actually set, use `"field_name" in settings.model_fields_set`.
- [ ] New `import os` solely for env access? Drop it.

### 6. Naming
- [ ] Name leaks the implementation entity rather than describing the feature? Prefer feature-oriented names.
- [ ] Same string appears in code, JSON config, defaults, and error messages? Lift it to a single shared constant and reference it everywhere.
- [ ] Subclass/identifier name doesn't match the actual exposed name (after a rename)? Realign all references.

### 7. Design doc fidelity
- [ ] Touched a feature with a doc under `docs/designs/`? Update the doc body to match what was actually built.
- [ ] Flip the doc's `Status:` line to `Implemented` in the same PR.
- [ ] No broken doc cross-references introduced.
- [ ] Implementation doesn't silently contradict a load-bearing assumption in the doc.

### 8. Schema / cache regeneration
- [ ] Touched a config model? Run `make dump_app_schema` and commit the regenerated artifacts.
- [ ] Renamed a tool that appears in cached LLM tool-call responses? Regenerate and commit those caches.

### 9. Typing & attribute access
- [ ] `Any` used where a concrete type is available? Replace.
- [ ] Value object as `@dataclass`? Use Pydantic `BaseModel` (frozen if immutable).
- [ ] No-op `cast(...)` or `isinstance` check where the type is already known? Drop it.
- [ ] `getattr(obj, "x")` where `obj.x` works? Use direct access.
- [ ] Referencing a field on a typed object? Verify it actually exists on the type (LSP `hover`).

### 10. Decomposition
- [ ] Method handles 2+ distinct phases? Extract each into a named method.
- [ ] Passing a collaborator into a free function that could be a method on that collaborator? Move it.
- [ ] Nested branches that compute a boolean? Extract a one-liner.

### 11. Logging
- [ ] f-strings or pre-formatted strings in `logger.debug/info(...)`? Switch to lazy `%`-form: `logger.debug("msg %s", arg)`.
- [ ] Expensive serialization for debug-only output? Guard with `if logger.isEnabledFor(DEBUG):` or make lazy.
- [ ] Serializing arbitrary config? Use `json.dumps(obj, ensure_ascii=False, default=str)`.

### 12. Security — forwarded headers
- [ ] Forwarded-headers code that sets or defaults an `Authorization` header? It must never carry auth — strip it. A test asserting that scenario should be deleted, not added.

### 13. Subclass / protocol contracts
- [ ] When subclassing a framework/tool base, implement every contract the design doc marks required — don't rely on defaults to fill them in.
- [ ] Adding cross-cutting prompt/middleware injection for a single feature? Justify it; default expectation is "remove".

### 14. Multi-instance protocol state
- [ ] Modeling multi-instance protocol state (interleaved stream deltas, parallel tool calls, concurrent sessions) as a single slot? Key it by id/index and preserve siblings when mutating one entry.

### 15. Pipelines that mix user and admin sources
- [ ] Attachment/file/context pipelines must treat user-provided and admin-configured sources symmetrically — don't silently drop one.
- [ ] Don't re-stream the same bytes to the model on every agent iteration; honor the lazy-loading contract.

## Red flags — stop and reconsider

If you find yourself thinking any of these while reviewing your own change, treat it as a blocker:

| Thought | Reaction |
|---|---|
| "This bit isn't strictly needed but might be useful later" | Delete it — a reviewer will ask "why is this here?" |
| "I'll just sneak this rename in" | No. Separate PR. |
| "It's just one `os.getenv`" | Move to BaseSettings. |
| "I'll update the design doc in a follow-up" | Do it in this PR. |
| "common/ importing from agent/ is fine for now" | It is not. Fix the direction. |
| "The cached tool-call responses still work" | If you renamed a tool, regenerate caches. |
| "`Any` is fine here" | Use the concrete type. |

## Output format

The file saved to `docs/reviews/` and the in-chat summary share this layout:

```markdown
# Code review — <branch> ($scope)

_Generated: <YYYY-MM-DD HH:MM>_

## Blocking
- [ ] `path/to/file.py:42` — §<N> <rule name>: <what's wrong>. Suggested: <fix>.
- [ ] ...

## Nits
- [ ] `path/to/file.py:88` — §<N> <rule name>: <what's wrong>. Suggested: <fix>.

## Scope / structure
- [ ] split-PR concerns, missing schema regen, design-doc updates, etc.

## Verdict
<ship | fix-then-ship | split>
```

Every finding is a checkbox — the author ticks them off as fixes land.

## Maintenance

This checklist drifts as conventions evolve. At the start of every review run, check freshness:

```bash
git log -1 --since='7 days ago' --format=%h -- .claude/skills/code-review/SKILL.md
```

- **Non-empty output** → fresh. Skip; don't load `references/REFRESHING.md`.
- **Empty output** → stale. Tell the user "the review checklist hasn't been refreshed in over a week; refresh recommended" and offer to run it. Load [references/REFRESHING.md](references/REFRESHING.md) **only** if the user agrees.

Refresh is always separate from the review run — never block reviewing on a stale checklist.
