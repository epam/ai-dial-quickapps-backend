# Design: [Title]

- **Status:** Draft | Approved | Implemented | Superseded
- **Dependencies:**
  - None | [Link to dependent design doc(s)]

## Problem Statement

What is broken, missing, or inadequate today? Describe the current behavior and why it's a problem.
Focus on observable symptoms (bugs, duplication, semantic mismatches) rather than jumping to solutions.

## Design Goals

Bulleted list of concrete outcomes this design must achieve. Each goal should be independently verifiable.

- Goal 1
- Goal 2

---

## Use Cases

Concrete scenarios that illustrate how the feature is used from the user's or agent's perspective.
Each use case should describe the trigger, the expected behavior, and the observable outcome.

### UC-1: [Title]

**Trigger:** What initiates this scenario.
**Behavior:** What happens as a result.
**Outcome:** What the user or agent observes.

---

## Proposed Design

The core of the document. Break this into subsections that map to the distinct concerns or components being changed.

### Concern / Component 1

For each concern, cover:

- **What** is being introduced or changed (field, class, method).
- **Owner** — which component is responsible for this behavior.
- **Semantics** — how it works at runtime.
- **Change** — what specifically changes relative to the current codebase.

### Concern / Component 2

...

---

## Secondary Fixes

Smaller changes that naturally follow from the core design but are not the main focus.
Each should be a self-contained subsection with a brief description and the fix.

---

## Out of Scope

Items that were considered but intentionally deferred. For each, briefly explain **why** it's deferred
and what would be needed to address it in a future design pass.

---

## Configuration / Usage Examples

Concrete examples showing how the new design is used in practice.
Use tables, config snippets, or step-by-step walkthroughs — whatever makes the patterns clearest.

---

## Migration

### Breaking changes

Describe any breaking changes and the backward-compatibility strategy (warnings, coercion, migration scripts).

### Non-breaking changes

Note changes that are safe by default and require no action from existing users.

## Summary of Changes

A concise reference of all fields, classes, or interfaces added, removed, or modified.
Group by component. This section should be scannable without reading the full doc.
