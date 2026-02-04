# File parameters in tool calls

For any tool parameter that accepts a file or URL, you **must** use this format:

```
file:{prefix}::{path_or_url}
```

- **Prefixes** (lowercase): `base64` (encoded content), `url` (pass URL as-is), `text` (plain text from file).
- **Path/URL**: system files use `files/...` (e.g. `files/uploads/doc.pdf`); external use full `https://...`.
- **Separator**: always double colon `::`.

**Step-by-step:**
1. **Identify param type**: Does the parameter expect base64-encoded content, a URL/URI reference, or plain text from a file? (Check param name and description.)
2. **Choose prefix**: base64 → `base64`; URL/URI reference → `url`; plain text from file → `text`.
3. **Build value**: Combine as `file:{prefix}::{path_or_url}`. Use `files/...` for system/attachment paths, `https://...` for external URLs.

**Wrong** → **Right**:
- `files/docs/report.pdf` → `file:base64::files/docs/report.pdf` or `file:url::files/docs/report.pdf`
- `https://example.com/img.png` → `file:url::https://example.com/img.png`
- Never use raw paths, raw URLs, or placeholders like `{{file_1}}`.
- **Never** pass raw base64 or data URIs (e.g. `data:audio/wav;base64,UklGR...`). Use `file:base64::<path_or_url>` instead; the system will fetch and encode the file.

**Examples**: `file:base64::files/reports/Q4.pdf` | `file:url::https://cdn.com/photo.jpg` | `file:text::files/data/notes.txt`
