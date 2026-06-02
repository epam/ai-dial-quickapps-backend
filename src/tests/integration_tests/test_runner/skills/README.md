Store integration-test dial-prompt skills as Markdown files in this directory.

Each file must include YAML frontmatter with `name` and `description` (see
`quickapp/skills/_frontmatter.py`).

Example usage in tests:

`@e2e_test(skills="numbered-list-only.md", ...)`

The test runner uploads skill content to DIAL prompts storage and wires it through
`ApplicationConfig.skills` as `DialPromptSkillConfig`.
