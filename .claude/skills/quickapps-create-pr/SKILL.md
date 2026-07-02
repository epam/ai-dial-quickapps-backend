---
name: quickapps-create-pr
description: Use when the user asks to "create a PR", "open a pull request", "raise a PR", "ship this", or "/quickapps-create-pr" in this repo. Drives the project's end-to-end PR flow — feature branch, conventional-commit title/body, the pre-PR format+lint gate, push, and `gh pr create --base development` with the repo's PR template filled in.
allowed-tools: Read Grep Glob LSP Write(./tmp/*) Bash(git status:*) Bash(git diff:*) Bash(git log:*) Bash(git rev-parse:*) Bash(git branch:*) Bash(git checkout:*) Bash(git switch:*) Bash(git stash:*) Bash(git add:*) Bash(git commit:*) Bash(git push:*) Bash(gh pr create:*) Bash(gh pr view:*) Bash(gh pr list:*) Bash(make format:*) Bash(make lint:*) Bash(make test:*) Bash(date:*) Bash(mkdir:*)
argument-hint: "[issue-number]"
arguments: issue
model: opus
effort: high
---

# quickapps-create-pr

Take the change on the current working tree all the way to an open pull request, the way this team does it: a `<type>/<desc>` branch, a Conventional-Commits title and a "why"-first body, the format+lint gate green, then `gh pr create --base development` with the repo's template filled in.

This skill **mutates state** (commits, pushes, opens a PR). Run it in the main conversation — never in a fork. Invoking it *is* the user's authorization to commit and push the current change; you still **always** show the proposed branch name, commit title, and PR body and get a quick confirmation before the commit, and you never force-push or touch `development` directly.

## When to use

- The user says "create a PR", "open/raise a pull request", "ship this", or runs `/quickapps-create-pr`.
- A feature or fix is finished and ready to submit.

Do **not** use this to push half-finished work, to commit on `development`, or to amend/force-push an existing PR branch.

## Arguments

`issue` = `$issue` (optional GitHub issue number). If provided, it seeds the branch name and the `fixes #<n>` line. If empty, look for an issue number in the user's message or the diff/commit; if you find a likely one, confirm it with the user. Otherwise leave `fixes #` blank for the author to fill.

## Preflight

1. **List everything that changed:** `git status --short` (includes untracked) and `git diff --stat`. If the tree is clean **and** nothing is committed on the branch beyond the base, report "nothing to PR" and stop.

2. **Scope the change — this is the load-bearing step.** A working tree routinely holds *several parallel, unrelated changes* (e.g. a `create-pr-skill` edit **and** an unrelated `review-skill` edit sitting dirty at the same time). Decide exactly which paths belong to **the change this PR is about** — the one named in the user's request / this session — and treat every other modified or untracked path as **out of scope**. Write the in-scope path list down and reuse it verbatim when staging (Step 3). When the tree mixes scopes, list the in-scope files back to the user and confirm before staging anything. Never assume "everything dirty belongs to this PR."

3. **Branch must match the change.** `git rev-parse --abbrev-ref HEAD`:
   - On `development`/`main`/`master`, **or on a branch that belongs to a *different* change** → put this change on its own branch (Step 1), cut from `development`, carrying only the in-scope files. Do **not** pile this change onto an unrelated feature branch just because you happen to be sitting on it.
   - Reuse the current branch only if it already belongs to *this* change (e.g. an already-pushed branch you're adding follow-up commits to).

4. Decide the branch name (Step 1's convention), then check for an existing PR: `gh pr list --head <branch> --state open`. If one exists, tell the user and stop — this skill opens new PRs, it doesn't update them.

> When the in-scope files are tangled into a branch/commit that also holds parallel work, isolate them first: branch off `development` and bring over only the in-scope paths (`git checkout <other-branch> -- <in-scope-path>`, or stash the rest with `git stash push -- <out-of-scope-path>`). Verify with `git diff --stat origin/development...HEAD` that the branch carries **only** this change before opening the PR.

## Workflow

Copy this checklist into your response and tick items as you go:

```
PR progress:
- [ ] Preflight — scoped the change, branch matches it, no existing PR
- [ ] Self-review (quickapps-code-review) — blockers resolved
- [ ] Branch cut from development (if not already on this change's branch)
- [ ] make format + make lint green
- [ ] Staged only in-scope paths, committed (Conventional Commits)
- [ ] Pushed with -u
- [ ] PR body composed from .github/pull_request_template.md
- [ ] gh pr create --base development; reported the URL
```

### 0. Self-review gate

Before committing, run the team's pre-submit self-review. **REQUIRED SUB-SKILL:** invoke `quickapps-code-review` (scope `uncommitted` if changes aren't committed yet, else `pr`). Surface any **Blocking** findings to the user and resolve or explicitly waive them before proceeding. Don't open a PR over an unaddressed blocker.

### 1. Branch

If still on the base branch, cut a feature branch. Naming follows the commit type:

```bash
git checkout -b <type>/<short-kebab-desc>
# with an issue number:
git checkout -b <type>/<issue>-<short-kebab-desc>
```

`<type>` ∈ `feat` | `fix` | `chore` | `refactor` | `docs` | `test` (see the table below). Examples from this repo: `feat/353-wrap-file-stage-content`, `fix/write-overwrite-missing-file`, `chore/core_module`.

### 2. Pre-PR gate — format + lint must be green

```bash
make format        # autoflake → black → isort → schema dump
make lint          # poetry check --lock + flake8 + black/isort/autoflake --check + mypy + schema check
```

Both must pass before committing. If a config model changed, `make format` regenerates schema artifacts (via `make dump_app_schema`) — those belong **in this PR**, so stage them. Run `make test ARGS="-k <relevant-pattern>"` (scoped to the changed modules) **only if the user asks** or the change touches core agent/orchestration logic; the full and integration suites otherwise run in CI and on the review environment, not locally.

### 3. Commit (Conventional Commits)

Stage **only the in-scope paths** from Preflight §2 — list them explicitly. **Never `git add -A` / `git add .`** when the tree also holds parallel, unrelated changes; that sweeps the other change into this PR.

```bash
git add <in-scope-path> [<more-in-scope-paths>]   # explicit paths, never -A when scopes are mixed
git status --short                                 # verify: staged (left column) = in-scope only; nothing unrelated leaked in
```

Then commit with a `<type>: <subject>` title and a body that explains **why**, not just what. Always show the user **the staged file list, the title, and the body**, and get a quick confirmation before running the commit (see the header rule). Keep the branch `<type>` and the commit `<type>` identical.

```bash
git commit -F - <<'EOF'
<type>: <imperative, lowercase subject, no trailing period>

<1–3 short paragraphs or bullets explaining the why and the key
implementation points. Reference the issue if applicable.>
EOF
```

After committing, run `git diff --stat origin/development...HEAD` and confirm it lists **only** the in-scope files before pushing.

Title rules: imperative mood, lowercase after the colon, no period, optional scope `<type>(scope):`. The PR title will reuse this exact subject.

### 4. Push

```bash
git push -u origin <branch>
```

`-u` sets upstream on the first push. Never `--force`.

### 5. Compose the PR body

**Read [`.github/pull_request_template.md`](../../../.github/pull_request_template.md)** and use it verbatim as the skeleton — it is the source of truth for the body, so don't reproduce it from memory (it changes). Then:

- Fill `### Applicable issues` with `fixes #<issue>` (or leave `fixes #` if none).
- Fill `### Description of changes` with the **why** first (problem/motivation), then the key implementation points — expand on the commit body. Add screenshots for user-visible / stage-rendering changes.
- **Keep every checklist point** from the template — do not delete rows. Tick `[x]` only the ones you've actually verified, leave the rest `[ ]`. `Title follows Conventional Commits` is safe to tick; **leave `Integration tests pass` and `Changes are tested on review environment` unticked** unless they really ran (they're CI/reviewer responsibilities, and Step 2 doesn't run them locally). If a config/schema model changed, the schema-compat row is load-bearing — address it.
- **If a checklist point doesn't apply to this PR** (e.g. "Design documented..." on a pure refactor with no design doc), don't delete the row and don't just leave it unticked — cross it out with `~~...~~` so the reviewer can tell "not applicable" apart from "not done". Leave a short parenthetical reason, e.g. `- ~~[ ] Design documented is updated/created and approved by the team (if applicable)~~ (no design doc for this change)`.
- Keep the license confirmation line at the bottom.

Write the filled body with the **Write** tool to `./tmp/quickapp_pr_body.md` — a project-local, gitignored scratch dir (`mkdir -p ./tmp` first if it doesn't exist yet) — not the global `/tmp` and not a shell heredoc.

### 6. Open the PR

With the body already written to `./tmp/quickapp_pr_body.md` (Step 5):

```bash
gh pr create \
  --base development \
  --head <branch> \
  --assignee @me \
  --title "<type>: <subject>" \
  --body-file ./tmp/quickapp_pr_body.md
```

`--base development` is non-negotiable — this repo's default base is `development`, never `main`/`master`.

### 7. Report back

Print the PR URL `gh` returns. Give the user a 3-line summary: branch, title, and the URL.

## Commit / branch types

| `<type>` | Use for |
|---|---|
| `feat` | New user-facing capability |
| `fix` | Bug fix |
| `chore` | Maintenance, deps, tooling, no behavior change |
| `refactor` | Internal restructure, no behavior change |
| `docs` | Docs / design docs only |
| `test` | Tests only |

## Red flags — stop and reconsider

| Thought | Reaction |
|---|---|
| "Everything dirty is probably part of this PR" | No — scope it (Preflight §2). Stage only this change's paths. |
| "`git add -A` is faster" | It sweeps parallel unrelated work into the PR. Stage explicit paths. |
| "I'll just reuse the branch I'm on" | Only if it's *this* change's branch. Otherwise branch off `development`. |
| "I'll commit on `development`, it's faster" | No. Branch first. |
| "lint is failing but it's unrelated" | Gate is red — fix it before the PR. |
| "I'll target `main`" | Base is always `development`. |
| "Schema dump changed, I'll commit it later" | It belongs in this PR — stage it now. |
| "I'll skip the self-review" | Run `quickapps-code-review` first; resolve blockers. |
| "Force-push to fix the branch" | Never. Open the PR clean or make a new commit. |
| "The title can be a sentence" | Conventional Commits: `<type>: lowercase imperative`. |

## Common mistakes

- **`git add -A` sweeping in parallel work** — when several unrelated changes sit dirty at once (e.g. two different skill edits), `-A` stages all of them. Stage explicit in-scope paths and verify with `git status --short` before committing, and with `git diff --stat origin/development...HEAD` after.
- **PR'd from the wrong branch** — committing this change onto whatever feature branch you happened to be on drags that branch's commits into the PR diff. Branch off `development` and carry only the in-scope files.
- **Empty `fixes #`** left when an issue exists — pass `$issue` or infer it.
- **Body that only says *what*** — reviewers want the *why*. Lead with motivation.
- **Unstaged schema/cache regen** from `make format`/`make dump_app_schema` — always commit regenerated artifacts.
- **Deleting checklist rows** — keep every point from `.github/pull_request_template.md`; tick the ones you verified, leave the rest unchecked, and cross out (`~~...~~`) the ones that don't apply with a short reason. Don't remove rows.
- **Reproducing the PR template from memory** — read `.github/pull_request_template.md` each time; it's the source of truth and it changes.
