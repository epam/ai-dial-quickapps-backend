# File parameters in tool calls

For any tool parameter that accepts a file or URL, you **must** use this format:

```
file:{prefix}::{path_or_url}
```

- **Prefixes** (lowercase): `base64` (encoded content), `url` (pass URL as-is), `text` (plain text from file).
- **Path/URL**: system files use `files/...` (e.g. `files/uploads/doc.pdf`); external use full `https://...`.
- **Separator**: always double colon `::`.

**Wrong** → **Right**:
- `files/docs/report.pdf` → `file:base64::files/docs/report.pdf` or `file:url::files/docs/report.pdf`
- `https://example.com/img.png` → `file:url::https://example.com/img.png`
- Never use raw paths, raw URLs, or placeholders like `{{file_1}}`.

**Examples**: `file:base64::files/reports/Q4.pdf` | `file:url::https://cdn.com/photo.jpg` | `file:text::files/data/notes.txt`
