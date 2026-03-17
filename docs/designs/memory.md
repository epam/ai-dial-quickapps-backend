# Design: [Title]

**Status:** Draft | Approved | Implemented | Superseded

## Problem Statement

What is broken, missing, or inadequate today? Describe the current behavior and why it's a problem.
Focus on observable symptoms (bugs, duplication, semantic mismatches) rather than jumping to solutions.

## Design Goals

Address:
- How AI agents interact with memory?
- How UI clients interact with memory?
- What is memory in terms of DIAL entities?
- How memory is stored in DIAL file storage?
- How user can view and manage memory?
- How memory is scoped?
- How user provides consent for saving information to memory?
  - user, user-app, smth else?
- How memory is structured?
  - Facts, their lifecycle
- How the system can be adjusted what is saved to memory and what is not?
- How can we later improve and evolve the system?

## Use cases

What is DIAL memory for? What are the use cases we want to support?

### Use case 1: Basic facts about the user and their preferences

We'd like the system to remember basic facts about the user, such as their:
- name
- age
- location
- time zone
- interests
- preferencies

That will be useful for the personalization if the experience in interactions with AI Agents.

Certain attributes may be available via the user profile. In that case the system should be able to pull that information
and take it into account.

However, certain attributes won't be there, but can be extracted from what user tells the system in conversations.
For example, if the user says `Provide all code examples in Python`, the system can extract that the user prefers
Python and save it as a fact in memory.

### Use case 2: Application-specific preferences and facts

The system should be able to remember facts and preferences related to particular applications. For example, if the user says
`If you generate code - generate code in Python` - the system should be able to extract that preference and apply it when the user asks to generate code.

Another use-case: some important or key facts found during the conversation, or some restrictions that should be applied
when working with particular application. In such cases agent should be able to react to that and save that information in memory for future interactions.

### Use case 3: Direct ask from user to save some information in memory

The system should be able to save information in memory based on direct ask from user. For example, if the user says
`Remember that I always prefer Python for code examples`, the system should be able to extract that preference and save
it as a fact in memory.

### Use case 4: Workflows for particular applications - OUT OF SCOPE

The system should be able to remember user's workflows in working with particular application. For example, if the user says
"Follow this process when you work on this task", the system should be able to extract the process and use it in future
interactions.

### Use case 5: Adjust what is saved in memory and what is not

System administrators and application administrators should be able to adjust what information is saved in memory and
what is not. For example, they may want to exclude certain types of information from being saved in memory for privacy reasons.

---

## Proposed Design

The core of the document. Break this into subsections that map to the distinct concerns or components being changed.

### Concern 1

For each concern, cover:

- **What** is being introduced or changed (field, class, method).
- **Owner** — which component is responsible for this behavior.
- **Semantics** — how it works at runtime.
- **Change** — what specifically changes relative to the current codebase.

### Concern 2

###

...

---

## Secondary Fixes

Smaller changes that naturally follow from the core design but are not the main focus.
Each should be a self-contained subsection with a brief description and the fix.

---

## Out of Scope

Items that were considered but intentionally deferred. For each, briefly explain **why** it's deferred
and what would be needed to address it in a future design pass.

### Search past conversations

Functionality to search past conversation for the info that was not saved in memory is out of scope for now.

The only thing that is searched - memory.

### Preferences in working with particular applications

This concern should be better addressed by introduction of extended support for agents skills: user may be able to dynamically
create and update skills, and reuse them across different agents.

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
