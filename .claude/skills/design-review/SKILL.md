---
name: design-review
description: Use when the user asks to review, critique, validate, or approve a design doc under docs/designs/. Appends a Review Notes block; on explicit approval, strips notes and flips Status to Approved.
context: fork
agent: general-purpose
model: opus
effort: xhigh
---

# Design document review

You are running in a forked, isolated context. Read and research freely — only the final summary you return reaches the main conversation. All file edits (appending review notes, flipping Status on approval) happen here.

## 1. Resolve the target

- The target doc lives under `docs/designs/`. If the user gave an explicit path, use it. If they named the doc loosely ("the toolset design"), match it against filenames in `docs/designs/`. If multiple plausible matches exist, stop and ask which one.
- Never review anything outside `docs/designs/`.
- Read the full target doc before doing anything else.

## 2. Decide the operating mode

Pick exactly one, based on the user's phrasing and the current state of the doc:

| Mode | Trigger | Action |
|------|---------|--------|
| **Initial review** | User asks to review/critique/validate. Doc has **no** `## Review Notes — Round N` section. | Review, append a `## Review Notes — Round 1` block at the bottom. |
| **Revision review** | Doc already has one or more `## Review Notes — Round N` sections; user wants another pass. | Review, append `## Review Notes — Round N+1` below the previous rounds. Preserve prior rounds (they are the history). |
| **Approval** | User **explicitly** says "approve", "mark approved", "looks good, approve it", or similar unambiguous approval. | Strip all review-notes sections, flip `Status` to `Approved`, add an `Approved:` date line. Do **not** perform another review. |

Edge cases:

- If Status is already `Approved`, `Implemented`, or `Superseded` and the user asks for a fresh review, stop and ask them to confirm — the doc is past the review stage.
- If the user says something ambiguous like "ship it", "lgtm", or asks to review a doc with only-just-resolved comments, ask before acting. **Approval is one-way; never auto-approve.**

## 3. Ground yourself before writing a single finding

Read — in this order:

1. The target design doc (full contents).
2. `docs/designs/README.md` — required structure, lifecycle, best practices.
3. `docs/designs/template.md` — the canonical section list.
4. `CLAUDE.md` and `CLAUDE.local.md` — project conventions.
5. `CODESTYLE.md` if referenced by the doc or relevant to a claim.
6. Any doc the target links to (e.g. `docs/agent.md`, `docs/skills.md`), **only** where relevant.
7. The specific code the design references. Spot-check every non-trivial code claim against the actual file/symbol. Prefer LSP (`goToDefinition`, `findReferences`, `hover`) for navigation; fall back to Grep/Read only when LSP can't answer.

Do not skip this. A review that hasn't verified the doc's claims against the codebase is low-signal noise.

## 4. Evaluate against the rubric

For each dimension, produce a finding only when something is actually off — do not invent filler. Every finding must cite a specific section or quoted snippet from the doc.

- **Structural completeness.** Are all sections from `docs/designs/README.md` present? If one is missing, is the omission defensible for this doc?
- **Problem grounding.** Are symptoms in *Problem Statement* verifiable by reading the cited code? Flag any claim the code contradicts.
- **Goal verifiability.** Is each Design Goal concrete and independently verifiable, or is it a slogan?
- **Use-case coverage.** Trigger / Behavior / Outcome covered? Error and edge scenarios included?
- **Orthogonality of concerns.** Are sections in *Proposed Design* separable, or does one field/flag secretly gate multiple behaviors?
- **Per-concern completeness.** For each concern: **What**, **Owner**, **Semantics**, **Change** — covered?
- **Defaults & non-obvious behavior.** Are defaults, `None` handling, and omitted-field semantics explicit?
- **Edge cases.** Error paths, concurrency, partial failures, schema evolution, config upgrades.
- **Migration.** Breaking changes called out with a compatibility strategy? Non-breaking changes distinguished?
- **Alignment with project conventions.** DI pattern (`*_module.py` + `configure(binder)`), module boundaries, preview-feature gating (`ENABLE_PREVIEW_FEATURES`), config schema auto-gen (`make dump_app_schema`), `aidial_sdk` vs `aidial_client` type boundaries.
- **Trade-offs & alternatives.** Does the doc name alternatives considered and why this one wins?
- **Clarity.** Prose over code snippets? Mermaid diagrams where they clarify? Referenced components named (e.g. `StagedBaseTool._run_in_stage_report_success`) rather than inlined?
- **Out of Scope justification.** Is each deferral explained, or is the section a dumping ground?

Prefer a small number of sharp findings over exhaustive nitpicking.

## 5. Write the Review Notes block

Append to the **end** of the target doc, separated from the existing content by a `---` rule, using exactly this structure:

```markdown
---

## Review Notes — Round N

- **Reviewer:** Claude (design-review skill)
- **Date:** YYYY-MM-DD

### Verdict

One of: `Blocking issues must be addressed` | `Ready for approval pending minor suggestions` | `Approval-ready`.

Follow with one short paragraph: what is strong, what blocks approval, what the author should revise.

### Blocking issues

Findings the author must resolve before approval. Omit this subsection if there are none.

1. **[Section name]** — issue description with evidence (quoted doc line, or reference to a codebase file `path/to/file.py:NN`).
   **Suggestion:** concrete action the author can take.

### Suggestions

Non-blocking improvements worth considering. Omit if none.

1. **[Section name]** — ...

### Nits

Minor wording, formatting, or consistency tweaks. Omit if none.

1. **[Section name]** — ...

### Changes since previous round

*Revision reviews only.* For each finding from the previous round, mark it **resolved**, **partially addressed**, or **still open**, with a one-line justification. Omit this subsection in Round 1.
```

Rules:

- Use today's date. Fall back to the date in the environment header (`currentDate`).
- Every finding must cite a specific section/paragraph of the doc.
- Do **not** touch any part of the design body above the Review Notes block. The Status line is yours only during approval (step 6).
- On revision reviews, **append** a new Round N+1 block below previous rounds. Do not rewrite or collapse older rounds.

## 6. Approval procedure (approval mode only)

Only when the user has **explicitly** approved in their message:

1. Delete every `## Review Notes — Round N` section and the preceding `---` rule, from the first review-notes divider to EOF.
2. In the header metadata:
   - Change `- **Status:** Draft` (or current non-Approved status) to `- **Status:** Approved`.
   - Insert `- **Approved:** YYYY-MM-DD` on the line directly below Status.
3. Leave everything else untouched.

## 7. Return to the main conversation

Return a **short** summary — five lines or fewer. Include:

- Which doc was reviewed (path).
- Which mode ran (initial / revision Round N+1 / approval).
- The verdict, and a count of blocking / suggestion / nit findings (or, for approval, the new status and date).

Do not reproduce the review text — it is already in the doc.

Example:

> Reviewed `docs/designs/dial_app_toolset.md` (Round 2). Verdict: Ready for approval pending minor suggestions. 0 blocking, 3 suggestions, 1 nit. 2 of 3 Round-1 blocking issues resolved; migration strategy for existing `DialDeploymentSimpleTool` callers is still open.

## Safety rails

- **Never auto-approve.** The Status flip requires an explicit, unambiguous approval from the user's message.
- **Never rename, move, or delete** the design file.
- **Never rewrite the design body.** You review; you do not ghost-write.
- **Never embed raw exploration output** in the review block. Structured, cited, concise only.
- If the target doc is missing, malformed (no Status header, no sections), or not under `docs/designs/`, stop and report what is wrong instead of guessing.
