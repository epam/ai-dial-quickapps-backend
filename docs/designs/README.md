# Design Documents

This folder contains design documents for QuickApps and provides general guidelines, structure, and best practices for
writing design docs.

## When to Write a Design Doc

Write a design doc before starting implementation when:

- The change touches multiple components or modules.
- There are meaningful trade-offs or alternative approaches to evaluate.
- The change introduces a new concept, config field, or public interface.
- The change has migration or backward-compatibility implications.

For small, self-contained fixes or straightforward feature additions, a well-described PR is sufficient.

## Structure of a Design Document

Use [`template.md`](template.md) as a starting point. Every design doc should include these sections:

| Section                            | Purpose                                                                 |
|------------------------------------|-------------------------------------------------------------------------|
| **Problem Statement**              | What is broken or missing today. Focus on symptoms, not solutions.      |
| **Design Goals**                   | Concrete, verifiable outcomes the design must achieve.                  |
| **Proposed Design**                | The core proposal, broken into orthogonal concerns or components.       |
| **Secondary Fixes**                | Smaller follow-on changes that fall out of the main design.             |
| **Out of Scope**                   | What was considered but intentionally deferred, and why.                |
| **Configuration / Usage Examples** | Concrete recipes, tables, or walkthroughs showing the design in action. |
| **Migration**                      | Breaking changes and backward-compatibility strategy.                   |
| **Summary of Changes**             | Scannable reference of all additions, removals, and modifications.      |

Not every section will be relevant for every design. Omit sections that don't apply, but think twice before dropping *
*Out of Scope** or **Migration** — they catch common blind spots.

## Best Practices

- **Lead with the problem, not the solution.** A reader should understand *why* before *how*.
- **Keep concerns orthogonal.** If your design has multiple moving parts, give each its own subsection with clear
  ownership. Avoid designs where one field or flag controls multiple unrelated behaviors.
- **Be explicit about defaults and non-obvious behavior.** State what happens when a field is omitted, set to `None`, or
  left at its default value.
- **Show, don't just tell.** Tables, config snippets, and before/after comparisons are more effective than long prose.
  Use mermaid diagrams where they clarify component interactions or flow.
- **Name the trade-offs.** If you chose approach A over B, briefly explain why. Future readers (and reviewers) will ask.
- **Scope aggressively.** A focused design that ships is better than an ambitious one that stalls. Use "Out of Scope" to
  defer related work explicitly rather than letting it creep in.

## Lifecycle

Each design doc carries a **Status** field:

| Status          | Meaning                                                        |
|-----------------|----------------------------------------------------------------|
| **Draft**       | Under active writing or discussion. Open for feedback.         |
| **Approved**    | Reviewed and accepted. Ready for implementation.               |
| **Implemented** | Implementation is merged. The doc is now historical reference. |
| **Superseded**  | Replaced by a newer design. Link to the successor doc.         |

## File Naming

Use descriptive, lowercase filenames with underscores: `attachment_config_redesign.md`, `tool_system_design.md`.