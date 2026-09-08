# Research: Citation Handling Across LLM Providers

- **Status:** Research — complete
- **Type:** Research / prior art. **Not** a design doc. No implementation decision,
  no target component chosen.
- **Dependencies:** None
- **Researched:** 2026-08-05. All findings reflect provider documentation as of that
  date. Every provider on this list has changed its citation surface at least once in
  the last 18 months; re-verify before building on any specific field name.

> **Scope (agreed before research):**
> 1. Covers both API-guaranteed citations (native web search, file search, document
>    grounding) **and** prompt-driven citations (model emits `[1]` markers or Markdown
>    links because the prompt told it to).
> 2. Includes verbatim request/response JSON, including streaming deltas.
> 3. Sourced from official provider documentation; links in §7.

---

## Key Findings

**KF-1 — The real split is not "inline vs. separate block." It is *what a citation
points at*.** Anthropic is **source-anchored**: the citation carries a pointer into the
source document (char range / page / block index) and the output span is delimited by
the text block itself, so no output offsets exist. OpenAI and Gemini are
**output-anchored**: `(start_index, end_index)` into the generated text, with no pointer
back into the source. Qwen and GLM anchor nothing at all — correlation is a string match
on a marker number. → §2 terminology, §4.2

**KF-2 — Source-anchored and output-anchored do not convert without loss.**
Anthropic → OpenAI is mechanical in the output direction but discards every source
pointer. OpenAI → Anthropic requires splitting text at annotation boundaries, which is
only well-defined if annotation spans never overlap — and nothing in OpenAI's spec says
they can't. → §4.3 point 1

**KF-3 — Only Anthropic returns what the source actually said, and only Anthropic
cannot be wrong.** `cited_text` is extracted by the API from the supplied document, not
written by the model. Gemini's `segment.text` is the *model's own words*; GLM's
`content` is the pre-answer search snippet; OpenAI, Qwen and DeepSeek return nothing.
A "hover to see the supporting quote" UI is fully implementable on exactly one provider.
→ §3.2.4, §4.3 point 5

**KF-4 — Every provider except Anthropic collapses to bare prompt-driven markers the
moment the grounding material comes from *our* tools rather than theirs.** OpenAI
concedes this explicitly: instead of an API it publishes a *prompt convention* built on
private-use Unicode markers (U+E200/E202/E201). Anthropic's `search_result` content
blocks are the only mechanism that runs your own RAG results through the same guaranteed
pipeline as native search. Given that our tools produce the groundable content, this is
the most decision-relevant fact in the document. → §3.1.4, §3.2.4, §4.2 Pattern D

**KF-5 — Consuming citations through an OpenAI-shaped endpoint destroys four of six.**
Anthropic and Gemini have nowhere to put their structures; GLM's fields are non-standard
extensions a strict client drops. Qwen is the sharpest case — its docs state flatly that
*"the OpenAI-compatible protocol does not support returning search sources in the
response,"* while its native DashScope endpoint will insert `[ref_1]` markers in a format
you choose. On Qwen, picking an endpoint **is** picking a citation capability. This
single fact constrains the design space more than any schema difference. → §3.4.3, §4.1 D8

**KF-6 — Offset units differ silently, and one of them is bytes.** OpenAI: characters.
Gemini legacy `groundingSupports`: **UTF-8 bytes**. Gemini's newer format: undocumented.
Code that slices a Python `str` with Gemini offsets is correct for ASCII and wrong for
everything else — this is a confirmed bug in Google's own `gemini-cli` (#5955), not a
hypothetical. → §3.3.1, §4.3 point 2

**KF-7 — Non-citation payloads ride in the citation envelope, and dropping them breaks
things.** Anthropic's `encrypted_index` / `encrypted_content` must be echoed back
verbatim or the next turn fails with a 400. Gemini's `searchEntryPoint.renderedContent`
is a Google-Search-Suggestions widget carrying a Terms of Service display obligation. A
normalizer that discards unrecognized fields breaks multi-turn correctness in the first
case and compliance in the second. → §3.2.5, §3.3.1, §4.3 point 7

**KF-8 — "A citation" spans a four-level trust gradient.** Anthropic's cannot be wrong
(API-derived). OpenAI's and Gemini's can point at the wrong span but always name a real
source. Qwen's and GLM's can reference a source index that does not exist. DeepSeek's
can be fabricated outright — it has no citation feature at all, only a published
`search_answer` prompt template using `[citation:X]`. Presenting all four uniformly
flattens a real difference, and the UI consequences differ. → §3.5, §5

**KF-9 — Two hard constraints worth knowing before any design.** Anthropic citations and
structured outputs are **mutually exclusive** (400 error) — you cannot have grounded
citations and a strict JSON schema in the same call. And Gemini carries a second field
named `citationMetadata` that is training-data recitation attribution, *not* grounding;
reading the wrong one is an easy mistake with no visible symptom. → §3.2.7, §3.3.3

**KF-10 — Streaming is documented for two providers out of six.** Anthropic
(`citations_delta`, no offsets, trivially incremental) and OpenAI
(`response.output_text.annotation.added`, ordered after the text it references). Gemini,
Qwen and GLM document nothing — and for the offset-carrying formats that is the
difference between incremental rendering and buffering the whole response. → §4.1 D5,
§6 items 3 & 5

---

## 1. Purpose & Scope

Agent responses increasingly carry grounded content — web search results, file search
hits, RAG-style tool results. Every provider surfaces the provenance of that content
differently, and the differences are not cosmetic: they disagree on *what a citation
points at*, which is the one thing you cannot paper over with field renaming.

This document establishes what each provider actually puts on the wire. It does not
propose a normalized model, does not choose an owning component, and does not
recommend a course of action.

**A note on terminology.** Throughout this document:

- **Output-anchored** — the citation carries offsets into the *generated text*.
  "Characters 2606–2758 of my answer are supported by this URL."
- **Source-anchored** — the citation carries a pointer into the *source document*.
  "This text block of my answer quotes characters 0–20 of document 3."

These are not the same operation, and the distinction drives most of §4.3.

## 2. Comparison Dimensions

| ID | Dimension | Question it answers |
|----|-----------|---------------------|
| D1 | Transport | Inline in the text, a separate structured field, or both? |
| D2 | Trigger | Which feature produces them? |
| D3 | Anchoring | What does a citation point at? |
| D4 | Metadata | Which of url / title / snippet / page / doc id / confidence is available? |
| D5 | Streaming shape | How does it arrive? Are offsets stable mid-stream? |
| D6 | Opt-in | What request-side flags are required? |
| D7 | Fidelity | Model-emitted (hallucinable) vs. API-guaranteed? |
| D8 | OpenAI-compat | What survives an `/v1/chat/completions`-shaped endpoint? |

---

## 3. Provider Findings

### 3.1 OpenAI

OpenAI has **four** separate citation surfaces. They do not share a schema, and two of
them are mutually exclusive in practice.

| Dim | Finding |
|-----|---------|
| D1 | **Both.** Inline citations appear in the text *and* a parallel `annotations[]` array carries structure. |
| D2 | Web search tool, file search tool, code-interpreter container files, and a documented prompt-engineering convention. |
| D3 | **Output-anchored** character offsets (`start_index`/`end_index`) into the generated text. File search is weaker — a single `index` point marker, no span. |
| D4 | `url` + `title` (web); `file_id` + `filename` (file search). No snippet of the source, no page number, no confidence score. |
| D5 | `response.output_text.annotation.added` events, carrying `content_index` + `annotation_index`. |
| D6 | Responses API: `tools: [{"type": "web_search"}]`. Chat Completions: `web_search_options`. Sources list needs `include: ["web_search_call.action.sources"]`. |
| D7 | API-guaranteed for the native tools; purely model-emitted for the prompt convention (§3.1.4). |
| D8 | Chat Completions is the *native* shape here, so it survives fully — see §3.1.3. |

#### 3.1.1 Responses API — web search

Response output (verbatim from OpenAI's web search guide):

```json
[
  {
    "type": "web_search_call",
    "id": "ws_67c9fa0502748190b7dd390736892e100be649c1a5ff9609",
    "status": "completed",
    "action": {
      "type": "search",
      "query": "latest news about AI"
    }
  },
  {
    "id": "msg_67c9fa077e288190af08fdffda2e34f20be649c1a5ff9609",
    "type": "message",
    "status": "completed",
    "role": "assistant",
    "content": [
      {
        "type": "output_text",
        "text": "On March 6, 2025, several news...",
        "annotations": [
          {
            "type": "url_citation",
            "start_index": 2606,
            "end_index": 2758,
            "url": "https://...",
            "title": "Title..."
          }
        ]
      }
    ]
  }
]
```

Two things worth flagging:

- The docs say "the model's response will include inline citations for URLs found in
  the web search results" **and** the annotations array is populated. So the text is
  already user-presentable, and the annotations are a parallel structured view of the
  same thing. This is a redundant-by-design format.
- `sources` (the full list of URLs consulted, typically much larger than the cited
  set) is only returned if you opt in with
  `include: ["web_search_call.action.sources"]`. OpenAI notes it "often exceeds the
  number displayed as inline citations." Real-time feeds are labelled `oai-sports`,
  `oai-weather`, `oai-finance`.

> **Unresolved:** OpenAI's own docs define `start_index`/`end_index` only as "the
> character positions within the response text where citations apply" — which does not
> disambiguate between *the span of the supported claim* and *the span of the inline
> citation marker itself*. Secondary sources assert the latter. I could not confirm
> either reading from official documentation. This matters: it is the difference
> between "highlight this sentence" and "replace this substring with a link", and it
> would need an empirical check before anyone builds on it.

#### 3.1.2 File search & container files

File search citations are structurally weaker — a point, not a span:

```json
{
  "type": "file_citation",
  "index": 992,
  "file_id": "file-2dtbBZdjtDKS8eqWxqbgDi",
  "filename": "deep_research_blog.pdf"
}
```

There is no `start_index`/`end_index`, and no quoted text from the source. You know
*which file* supported the answer and roughly *where in the output* the reference sits,
but you cannot show the user what passage was relied on.

Container file citations (code interpreter output) do carry a span:

```json
{
  "type": "container_file_citation",
  "container_id": "cntr_68a58729ebf88190b4451603...",
  "file_id": "cfile_68a5873005008190...",
  "filename": "chart.png",
  "start_index": 197,
  "end_index": 249
}
```

#### 3.1.3 Chat Completions

The same `url_citation` shape, relocated to `message.annotations[]`, and gated on
`web_search_options` rather than a `tools` entry. Fields are identical: `url`, `title`,
`start_index`, `end_index`. This is the only provider in this comparison whose
structured citations are *native* to the `/v1/chat/completions` schema rather than
bolted onto it.

#### 3.1.4 Prompt-driven — OpenAI's own convention

OpenAI publishes a **Citation Formatting** guide for the case where you supply the
retrieved context yourself and want the model to cite it. It is prompt engineering, not
an API feature, and it is unusually specific — it recommends Unicode Private Use Area
markers, because those are what the models are trained on:

```
CITATION_START     = U+E200   (\ue200)
CITATION_DELIMITER = U+E202   (\ue202)
CITATION_STOP      = U+E201   (\ue201)
```

Grammar:

```
{CITATION_START}<family>{CITATION_DELIMITER}<source_id>{CITATION_DELIMITER}<locator>{CITATION_STOP}
```

Example of what the model emits inside `output_text`:

```
The agreement requires thirty days' notice. \ue200cite\ue202turn0file0\ue202L8-L13\ue201

(shown with the markers escaped; on the wire they are the literal, non-printing
U+E200 / U+E202 / U+E201 code points)
```

Source IDs follow patterns like `turn0file0`, `turn0block1`, `block5`. The guide states
these markers are "highly recommended because they closely match the markers our models
are trained on," and that if you pick different markers you should keep the overall
shape as close as possible.

Documented placement rules for the prompt: citations go after punctuation, at paragraph
end (or inline for long paragraphs), never inside markdown formatting or code blocks,
and never grouped into a citation-only line at the end.

**This is the single most important finding in §3.1 for our purposes.** It is an
explicit acknowledgement by OpenAI that when the grounding material comes from *your*
tools rather than *their* tools, there is no structured channel at all — you get
in-band markers that you must parse and strip yourself. Every provider in this document
degrades to this mode for custom tool results, except Anthropic (§3.2.4).

#### 3.1.5 Streaming

```json
{
  "type": "response.output_text.annotation.added",
  "sequence_number": 229,
  "item_id": "msg_68a5872f058881a08...",
  "output_index": 1,
  "content_index": 0,
  "annotation_index": 1,
  "annotation": {
    "type": "container_file_citation",
    "container_id": "cntr_68a58729ebf88190b4451603...",
    "end_index": 249,
    "file_id": "cfile_68a5873005008190...",
    "filename": "chart.png",
    "start_index": 197
  }
}
```

The annotation arrives as its own event, addressed by `output_index` / `content_index` /
`annotation_index`. Because offsets are into the accumulated text of that content part,
and the annotation arrives after the text it describes has been emitted, offsets are
resolvable at arrival time without buffering the whole response.

---

### 3.2 Anthropic Claude

Claude is the outlier, and the reason this research exists. Its citations are
**source-anchored, not output-anchored**, and they are structurally incapable of
landing in the wrong place in the output text.

| Dim | Finding |
|-----|---------|
| D1 | **Separate structure only.** Nothing is embedded in the text. The response text is split into multiple `text` blocks; cited blocks carry a `citations[]` array. |
| D2 | Document blocks with `citations.enabled`, `search_result` blocks (RAG), and the web search tool. |
| D3 | **Source-anchored.** The cited *output* span is the text block itself. The citation payload points into the *source*: char range, page range, block range, or an opaque encrypted index. |
| D4 | `cited_text` (the actual quoted passage!), `document_index`, `document_title`, plus type-specific locators. Web search adds `url` + `title`. No confidence score. |
| D5 | `citations_delta` inside `content_block_delta`, appended to the current text block. |
| D6 | `"citations": {"enabled": true}` per document. Always-on for the web search tool. |
| D7 | **API-guaranteed.** The model emits an internal format that the API parses and validates; `cited_text` is extracted by the API, not written by the model. |
| D8 | Nothing survives. The block-splitting *is* the anchoring, and `/v1/chat/completions` has no block-splitting. |

#### 3.2.1 Request

```json
{
  "model": "claude-opus-5",
  "max_tokens": 1024,
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "document",
          "source": {
            "type": "text",
            "media_type": "text/plain",
            "data": "The grass is green. The sky is blue."
          },
          "title": "My Document",
          "context": "This is a trustworthy document.",
          "citations": {"enabled": true}
        },
        {
          "type": "text",
          "text": "What color is the grass and sky?"
        }
      ]
    }
  ]
}
```

Citations must be enabled on all documents in a request or none.

#### 3.2.2 Response — the block-splitting model

```json
{
  "content": [
    {"type": "text", "text": "According to the document, "},
    {
      "type": "text",
      "text": "the grass is green",
      "citations": [
        {
          "type": "char_location",
          "cited_text": "The grass is green.",
          "document_index": 0,
          "document_title": "Example Document",
          "start_char_index": 0,
          "end_char_index": 20
        }
      ]
    },
    {"type": "text", "text": " and "},
    {
      "type": "text",
      "text": "the sky is blue",
      "citations": [
        {
          "type": "char_location",
          "cited_text": "The sky is blue.",
          "document_index": 0,
          "document_title": "Example Document",
          "start_char_index": 20,
          "end_char_index": 36
        }
      ]
    },
    {"type": "text", "text": ". Information from page 5 states that "},
    {
      "type": "text",
      "text": "water is essential",
      "citations": [
        {
          "type": "page_location",
          "cited_text": "Water is essential for life.",
          "document_index": 1,
          "document_title": "PDF Document",
          "start_page_number": 5,
          "end_page_number": 6
        }
      ]
    }
  ]
}
```

Note what this buys: **there are no offsets into the output at all.** The span of text
a citation applies to is delimited by the block boundary. Concatenating `text` fields
yields the plain answer; nothing has to be stripped, and nothing can drift.

#### 3.2.3 The five location types

| Type | Produced by | Locator fields | Indexing |
|------|-------------|----------------|----------|
| `char_location` | plain-text document | `start_char_index`, `end_char_index` | 0-indexed, end exclusive |
| `page_location` | PDF document | `start_page_number`, `end_page_number` | **1-indexed**, end exclusive |
| `content_block_location` | custom-content document | `start_block_index`, `end_block_index` | 0-indexed, end exclusive |
| `search_result_location` | `search_result` blocks | `search_result_index`, `start_block_index`, `end_block_index` | 0-indexed, end exclusive |
| `web_search_result_location` | web search tool | `url`, `title`, `encrypted_index` | opaque |

`document_index` is 0-indexed across *all* document blocks in the request, spanning all
messages — not per-message.

Chunking granularity is determined by document type: plain text and PDF are
auto-chunked into sentences; custom-content documents are not chunked further, so the
blocks you supply are exactly the citable units.

#### 3.2.4 `search_result` blocks — the RAG path

This is the mechanism with no analogue at any other provider. You return search results
from *your own* tool, in a first-class content-block type, and Claude cites them through
the same guaranteed pipeline as its native tools:

```json
{
  "type": "search_result",
  "source": "https://example.com/article",
  "title": "Article Title",
  "content": [
    {"type": "text", "text": "The actual content of the search result..."}
  ],
  "citations": {"enabled": true}
}
```

Resulting citation:

```json
{
  "type": "search_result_location",
  "cited_text": "All API requests must include an API key in the Authorization header. Keys can be generated from the dashboard. Rate limits: 1000 requests per hour for standard tier, 10000 for premium.",
  "source": "https://docs.company.com/api-reference",
  "title": "API Reference - Authentication",
  "search_result_index": 0,
  "start_block_index": 0,
  "end_block_index": 1
}
```

Per the docs, `cited_text` "equals the contents of `content[start_block_index:end_block_index]`
joined together." It is a derived field, not a model output — which is why it cannot be
wrong. `search_result_index` is 0-based across all `search_result` blocks in the
request, including those nested in tool results.

Search results can be supplied either as tool-call results or directly as top-level
user-message content.

#### 3.2.5 Web search tool

Citations are **always enabled** for the web search tool — not optional:

```json
{
  "text": "Claude Shannon was born on April 30, 1916, in Petoskey, Michigan",
  "type": "text",
  "citations": [
    {
      "type": "web_search_result_location",
      "url": "https://en.wikipedia.org/wiki/Claude_Shannon",
      "title": "Claude Shannon - Wikipedia",
      "encrypted_index": "Eo8BCioIAhgBIiQyYjQ0OWJmZi1lNm..",
      "cited_text": "Claude Elwood Shannon (April 30, 1916 – February 24, 2001) was an American mathematician, electrical engineer, computer scientist, cryptographer and i..."
    }
  ]
}
```

`cited_text` is capped at 150 characters here. `encrypted_index` and the results'
`encrypted_content` must be echoed back verbatim on subsequent turns or the request
fails with a 400 — so a normalization layer that drops unknown fields would break
multi-turn web search.

Anthropic also attaches a display obligation: "When displaying API outputs directly to
end users, citations must be included to the original source."

#### 3.2.6 Streaming

```sse
event: content_block_delta
data: {"type": "content_block_delta", "index": 0,
       "delta": {"type": "text_delta", "text": "According to..."}}

event: content_block_delta
data: {"type": "content_block_delta", "index": 0,
       "delta": {"type": "citations_delta",
                 "citation": {
                     "type": "char_location",
                     "cited_text": "...",
                     "document_index": 0
                 }}}
```

Each `citations_delta` appends one citation to the current text block. Because there
are no output offsets, nothing needs recomputing as the stream progresses — this is the
most stream-friendly of the six formats by a wide margin.

#### 3.2.7 Constraints

- **Citations and structured outputs are mutually exclusive.** Enabling citations
  alongside `output_config.format` returns a 400. The docs explain why: citations
  require interleaving citation blocks with text, which is incompatible with a strict
  JSON schema constraint. Any design that wants both grounded citations *and*
  structured output from Claude has to pick one.
- Text-only. Image citations are not supported; scanned PDFs without extractable text
  are not citable.
- `cited_text` does not count toward output tokens, and does not count toward input
  tokens when passed back on later turns.

---

### 3.3 Google Gemini

Gemini has **two** grounding response formats — a legacy one and a current one — plus a
third field named `citationMetadata` that is not a citation feature in the sense used
here. Getting these confused is easy and the naming actively invites it.

| Dim | Finding |
|-----|---------|
| D1 | **Separate structure only** (legacy) / annotations attached to text (current). The model's text contains no markers in either format; you insert them yourself. |
| D2 | Google Search grounding, Maps grounding, Vertex AI Search grounding. |
| D3 | **Output-anchored** — but see the byte-offset trap below. |
| D4 | `uri` + `title` per chunk; `confidenceScores` **deprecated** (empty for Gemini 2.5+); `segment.text` gives the grounded output substring. |
| D5 | Not clearly documented. See D5 note below. |
| D6 | `tools: [{"google_search": {}}]`. |
| D7 | API-guaranteed. |
| D8 | Nothing survives; `groundingMetadata` has no home in the OpenAI schema. |

#### 3.3.1 Legacy format — `groundingMetadata`

```json
{
  "candidates": [
    {
      "content": {
        "parts": [
          {
            "text": "Spain won Euro 2024, defeating England 2-1 in the final. This victory marks Spain's record fourth European Championship title."
          }
        ],
        "role": "model"
      },
      "groundingMetadata": {
        "webSearchQueries": [
          "UEFA Euro 2024 winner",
          "who won euro 2024"
        ],
        "searchEntryPoint": {
          "renderedContent": "<!-- HTML and CSS for the search widget -->"
        },
        "groundingChunks": [
          {"web": {"uri": "https://vertexaisearch.cloud.google.com.....", "title": "aljazeera.com"}},
          {"web": {"uri": "https://vertexaisearch.cloud.google.com.....", "title": "uefa.com"}}
        ],
        "groundingSupports": [
          {
            "segment": {"startIndex": 0, "endIndex": 85, "text": "Spain won Euro 2024, defeatin..."},
            "groundingChunkIndices": [0]
          },
          {
            "segment": {"startIndex": 86, "endIndex": 210, "text": "This victory marks Spain's..."},
            "groundingChunkIndices": [0, 1]
          }
        ]
      }
    }
  ]
}
```

This is a **normalized relational shape**: chunks are the source table, supports are the
join table, `groundingChunkIndices` is the foreign key. One support can reference many
chunks (`[0, 1]` above). No other provider models many-to-many this explicitly.

Four traps in this format:

1. **`startIndex`/`endIndex` are byte offsets, not character offsets.** The Vertex API
   reference defines them as "measured in bytes, offset from the start of the Part."
   The encoding is not stated in the spec but is UTF-8 in practice. Any implementation
   that slices Python `str` by these indices produces correct output for ASCII and
   silently wrong output for anything else. This is not theoretical — it is a filed
   and confirmed bug in Google's own `gemini-cli` (issue #5955), where citation markers
   land in the wrong place for Japanese text.
2. **`uri` is a Google redirect, not the publisher's URL.** The values point at
   `vertexaisearch.cloud.google.com/...`. Displaying the real domain requires either
   using the `title` (which holds `aljazeera.com`, i.e. a domain, not an article title)
   or resolving the redirect.
3. **`confidenceScores` is dead.** Documented as parallel to `groundingChunkIndices`
   with values 0.0–1.0, but "for Gemini 2.5 and later, the confidence scores list is
   empty and should be ignored." A schema that models it as required will break.
4. **`searchEntryPoint.renderedContent` carries a Terms of Service obligation.** It is
   a blob of HTML+CSS for a Google Search Suggestions widget, and Google's terms
   require displaying it when using Search grounding. It is a compliance artifact, not
   a citation, but it arrives in the same envelope.

Google's own recommended rendering algorithm is worth noting: sort supports by
`endIndex` **descending** and insert markers back-to-front, so that each insertion
doesn't invalidate the offsets of the ones not yet processed.

#### 3.3.2 Current format — `steps` + `annotations`

The current Gemini API docs show a different envelope, in which grounding is expressed
as a step sequence and citations become OpenAI-shaped annotations:

```json
{
  "steps": [
    {
      "type": "thought",
      "summary": [
        {
          "type": "text",
          "text": "The user is asking for the winner of Euro 2024. I need to search for the result of the Euro 2024 final."
        }
      ],
      "signature": "CoMDAXLI2nynRYojJIy6B1Jh9os2crpWLfB0..."
    },
    {
      "type": "google_search_call",
      "arguments": {
        "queries": ["UEFA Euro 2024 winner"]
      }
    },
    {
      "type": "google_search_result",
      "call_id": "search_001",
      "result": [
        {
          "search_suggestions": "<!-- HTML and CSS for the search widget -->"
        }
      ]
    },
    {
      "type": "model_output",
      "content": [
        {
          "type": "text",
          "text": "Spain won Euro 2024, defeating England 2-1 in the final. This victory marks Spain's record fourth European Championship title.",
          "annotations": [
            {
              "type": "url_citation",
              "url": "https://www.aljazeera.com/sports/euro-2024-final",
              "title": "aljazeera.com",
              "start_index": 0,
              "end_index": 56
            },
            {
              "type": "url_citation",
              "url": "https://www.uefa.com/euro2024/news/spain-wins-euro-2024",
              "title": "uefa.com",
              "start_index": 57,
              "end_index": 124
            }
          ]
        }
      ]
    }
  ]
}
```

Google has converged on OpenAI's `url_citation` vocabulary — same type name, same field
names. Two consequences: the many-to-many capability of `groundingSupports` is gone
(flattened to one URL per annotation), and the URLs here are *real publisher URLs*, not
redirects.

> **Unresolved:** whether `start_index`/`end_index` in this newer format are byte
> offsets (inherited from `Segment`) or character offsets (matching the OpenAI
> convention they are imitating). The docs do not say. Given the field names were
> borrowed from OpenAI but the backend is the same one that produced byte offsets, this
> is genuinely ambiguous and must be verified empirically before use.

#### 3.3.3 `citationMetadata` is a different thing

`GenerateContentResponse` also carries a `citationMetadata` field with a
`citationSources[]` array. This is **recitation metadata** — attribution for content the
model reproduced from training data, driven by copyright compliance — not grounding
attribution. It has its own quirks (the backend can return sources with a missing
`endIndex`, and `startIndex` is optional, which has caused decode failures in Google's
own Firebase SDK). Anything reading "citations" out of a Gemini response needs to know
which field it is reading.

#### 3.3.4 Streaming

> **Unresolved.** Neither the Gemini API docs nor the Vertex reference documents when
> `groundingMetadata` arrives during `streamGenerateContent`, nor whether `segment`
> offsets are relative to the accumulated text or to the individual chunk. This is a
> significant gap: for a byte-offset-into-accumulated-text format, the answer determines
> whether citations can be rendered incrementally at all. Requires empirical testing.

---

### 3.4 Qwen (Alibaba Cloud Model Studio / DashScope)

Qwen is the only provider here that will insert citation markers into the text **for**
you, in a format **you** choose — and the only one whose behaviour differs across three
of its own endpoints.

| Dim | Finding |
|-----|---------|
| D1 | **Both, and configurable.** Markers inline (opt-in, format selectable) + `search_info` side-channel (opt-in). Either can be disabled independently. |
| D2 | Built-in web search (`enable_search`). |
| D3 | **Neither.** No offsets in either direction. Correlation is by matching the marker's number to `search_results[].index`. |
| D4 | `index`, `title`, `url`, `site_name`, `icon`. No snippet, no confidence. |
| D5 | Not documented; note that streaming is *required* when web search is enabled for multimodal models. |
| D6 | `enable_search: true` plus `search_options: {enable_source, enable_citation, citation_format}`. |
| D7 | Marker insertion is API-driven, but placement is model-driven — see D7 note. |
| D8 | **Parameters survive, results do not.** See §3.4.3. |

#### 3.4.1 DashScope-native request

```python
response = dashscope.Generation.call(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    model="qwen-plus",
    messages=[{"role": "user", "content": "杭州明天天气是什么？"}],
    enable_search=True,
    search_options={
        "enable_source": True,          # return the source list
        "enable_citation": True,        # insert markers into the text
        "citation_format": "[ref_<number>]",
        "search_strategy": "agent",
    },
    result_format="message",
)
```

`citation_format` accepts `[<number>]` and `[ref_<number>]`. `enable_source` must be
true for `enable_citation` to be usable — markers without a source list would be
meaningless.

#### 3.4.2 Response

Sources arrive at `response.output.search_info["search_results"]`:

```json
{
  "index": 1,
  "title": "Result title",
  "url": "https://example.com",
  "siteName": null,
  "icon": null
}
```

and the text at `response.output.choices[0].message.content` carries markers matching
the requested format:

```
杭州明天多云转晴，气温 18-26℃[ref_1]，空气质量良好[ref_2][ref_3]。
```

Correlation is purely lexical: parse `ref_N` out of the text, look up `index == N`.
There is no structured link between the two — a fact that matters if markers are ever
malformed or reference a nonexistent index.

#### 3.4.3 Three endpoints, three behaviours

This is the most fragmented surface in the comparison:

| Endpoint | `enable_search` | Markers in text | Sources returned |
|----------|-----------------|-----------------|------------------|
| DashScope native | yes | yes, format selectable | yes, via `search_info` |
| OpenAI-compatible | yes, via `extra_body` | — | **no** |
| Responses API | yes | **no** — explicitly not inserted | yes, `web_search_call.action.sources` |

The OpenAI-compatible row is documented flatly: *"The OpenAI-compatible protocol does
not support returning search sources in the response."* The search still runs and still
grounds the answer; you simply get no provenance. The Responses API is documented as not
supporting `enable_source`, `enable_citation`, or `citation_format`, and as not
inserting `[1]` markers — the docs direct you to the DashScope API if you want markers.

So: on Qwen, choosing an endpoint *is* choosing a citation capability, and the
OpenAI-compatible endpoint — the one an integration would reach for by default — is the
one that loses everything.

> **D7 caveat:** `enable_citation` makes marker insertion a documented product feature
> rather than a prompt convention, but the placement is still the model deciding where a
> claim came from. Unlike Anthropic's `cited_text`, nothing is derived or validated by
> the API. Treat placement as model-quality-dependent.

---

### 3.5 DeepSeek

DeepSeek has **no citation feature of any kind** in its API. This is a real finding, not
a gap in the research.

| Dim | Finding |
|-----|---------|
| D1 | Inline only, by prompt convention. |
| D2 | Nothing native. The published prompt template, applied to search results you retrieve yourself. |
| D3 | None. |
| D4 | Whatever you put in the prompt. |
| D5 | Markers stream as ordinary text. |
| D6 | None — there is no flag to set. |
| D7 | **Fully model-emitted.** Hallucinable in every respect: wrong index, nonexistent index, missing marker, malformed marker. |
| D8 | N/A — the "OpenAI-compatible" shape is the only shape. |

The documented API surface is: thinking mode, multi-round conversation, chat prefix
completion (beta), FIM completion (beta), JSON output, tool calls, context caching, a
Responses API, and Anthropic API compatibility. No web search, no grounding, no
annotations, no citations.

What exists instead is an official **prompt template**, published in the DeepSeek-R1
repository as `search_answer` (Chinese and English variants), which is what
chat.deepseek.com itself uses. It takes `{search_results}`, `{cur_date}` and
`{question}`, and defines a two-part convention:

Search results are fed in delimited by markers:

```
[webpage 1 begin]
...content of result 1...
[webpage 1 end]
[webpage 2 begin]
...content of result 2...
[webpage 2 end]
```

And the model is instructed to cite as `[citation:X]`, with multiple sources written
`[citation:3][citation:5]`. The template further instructs the model to place citations
at the end of the relevant sentence rather than clustering them at the end of the
answer, to filter results by relevance, to cap list answers around 10 points, and to
match the user's language.

**Implication.** For DeepSeek, citation processing is entirely an application concern:
you own the retrieval, you own the prompt, you own the parsing, and you own the
validation — because the model can and will emit `[citation:7]` when only five results
were supplied. It is the clearest illustration of the floor that every other provider is
building above.

---

### 3.6 GLM (Zhipu AI / Z.ai)

GLM's web search returns a clean structured source list and — notably — **does not
automatically cite**. Marker emission depends on your `search_prompt`.

| Dim | Finding |
|-----|---------|
| D1 | Structured `web_search[]` array always; markers in text only if prompted. |
| D2 | `web_search` tool in the `tools` array; also a standalone `/paas/v4/web_search` endpoint. |
| D3 | **Neither.** No offsets. Correlation by the `refer` string (`"ref_1"`). |
| D4 | `title`, `link`, `content` (a real snippet!), `icon`, `media` (publication name), `refer`, `publish_date`. Richest metadata set of the six. |
| D5 | Not documented. |
| D6 | Tool declaration with `"enable": "True"`; `"search_result": "True"` to get the source array back. |
| D7 | Sources are API-guaranteed; markers are fully model-emitted and prompt-dependent. |
| D8 | The tool declaration is a non-standard extension of the `tools` array, and `web_search` is a non-standard top-level response field — so a strict OpenAI client drops both. |

#### 3.6.1 Request

```json
{
  "model": "glm-4-air",
  "messages": [
    {
      "role": "user",
      "content": "Key financial events, policy changes, and market data in April 2025"
    }
  ],
  "tools": [
    {
      "type": "web_search",
      "web_search": {
        "enable": "True",
        "search_engine": "search-prime",
        "search_result": "True",
        "search_prompt": "You are a financial analyst. Please use concise language to summarize the key information in {{search_result}} from the web search, ranked by importance and citing the source date. Today's date is April 11, 2025.",
        "count": "5",
        "search_domain_filter": "www.sohu.com",
        "search_recency_filter": "noLimit",
        "content_size": "high"
      }
    }
  ]
}
```

Note the booleans are **strings** (`"True"`, not `true`) in Z.ai's own documented
example, and `count` likewise (`"5"`). Note also `search_prompt` with its
`{{search_result}}` placeholder — GLM exposes the internal grounding prompt as a
first-class request parameter, which no other provider here does.

#### 3.6.2 Response

The source array is a **top-level** field of the chat completion response, sibling to
`choices` — not nested inside the message:

```json
{
  "web_search": [
    {
      "title": "Article headline",
      "link": "https://source-url.com/article",
      "content": "Summary text",
      "icon": "https://favicon-url.jpg",
      "media": "Publication name",
      "refer": "ref_1",
      "publish_date": "2025-04-10"
    }
  ]
}
```

Markers in the assistant text take the form `[Source: ref_1]` in Z.ai's example — but
they appear *because the `search_prompt` asked for them*. Absent such an instruction,
you get the source array and an uncited answer.

The standalone search endpoint (`POST /paas/v4/web_search`) returns the same records
under `search_result[]` with no model involvement at all — useful as a pure retrieval
API.

---

## 4. Cross-Provider Comparison

### 4.1 Matrix

| | OpenAI | Anthropic | Gemini | Qwen | DeepSeek | GLM |
|---|---|---|---|---|---|---|
| **D1 Transport** | inline + structured | structured only | structured only | inline + structured (both optional) | inline only | structured + optional inline |
| **D2 Trigger** | web search, file search, containers | documents, `search_result`, web search | Search / Maps / Vertex grounding | `enable_search` | none (prompt only) | `web_search` tool |
| **D3 Anchoring** | output offsets (chars) | **source pointers**; output span = block | output offsets (**bytes**, legacy) | none — lexical marker match | none | none — lexical `refer` match |
| **D4 Metadata** | url, title / file_id, filename | **`cited_text`**, doc index, title, char/page/block range | uri (redirect), title, `segment.text` | index, title, url, site_name, icon | none | title, link, **content**, media, icon, refer, publish_date |
| **D5 Streaming** | `annotation.added` event | `citations_delta` (no offsets — trivial) | **undocumented** | undocumented | plain text | undocumented |
| **D6 Opt-in** | tool / `web_search_options` | `citations.enabled` per doc; forced for web search | `google_search` tool | `enable_search` + `search_options` | n/a | tool + `search_result: "True"` |
| **D7 Fidelity** | guaranteed (native tools) | **guaranteed + API-derived quote** | guaranteed | markers model-placed, sources guaranteed | **fully hallucinable** | sources guaranteed, markers prompt-dependent |
| **D8 OpenAI-compat** | native | nothing survives | nothing survives | **params yes, sources no** | n/a | non-standard fields, dropped by strict clients |

### 4.2 Taxonomy

The six collapse into four patterns:

**Pattern A — Source-anchored blocks.** *Anthropic only.*
The output is split into blocks; a cited block carries pointers into the source plus the
API-extracted quote. No output offsets exist, so nothing can drift, nothing needs
stripping, and streaming is trivial. It is also the only pattern that extends to
*your own* tool results at full fidelity, via `search_result` blocks.

**Pattern B — Output-anchored annotations.** *OpenAI, Gemini.*
A parallel array carries `(start, end, url, title)` into the generated text. Rendering
is a text-splicing problem. Correctness depends on getting the offset units right
(chars vs. bytes) and on offsets remaining valid as text accumulates. Gemini's legacy
format is the most expressive here — many-to-many support→chunk mapping — and also the
most dangerous, given byte offsets.

**Pattern C — Markers plus a flat source list.** *Qwen, GLM.*
The text contains `[ref_1]`-style markers; a separate array holds the sources; the join
is a string match on a number. No offsets to get wrong, but no guarantee the marker set
and the source set agree. Qwen inserts markers as a product feature; GLM leaves it to
your prompt.

**Pattern D — Pure prompt convention.** *DeepSeek; OpenAI's own documented fallback for
custom context; any provider reached through an OpenAI-compatible gateway.*
Nothing structured. You define the marker syntax, the model emits it or doesn't, and you
parse, validate, and strip it yourself.

The important observation: **Pattern D is not just DeepSeek's situation. It is every
provider's situation the moment the grounding material comes from your own tools rather
than the provider's built-in search** — with exactly one exception, Anthropic's
`search_result` blocks. OpenAI documents this explicitly by publishing a prompt-marker
convention (§3.1.4) instead of an API.

### 4.3 Points of Genuine Disagreement

**1. Source-anchored vs. output-anchored is not reconcilable without loss.**
Converting Anthropic → OpenAI shape means computing output offsets by walking the block
list and accumulating lengths — mechanical, and lossless in the output direction, but
the source pointers (`start_char_index`, `document_index`, `page_number`) have nowhere
to go. Converting OpenAI → Anthropic shape means *splitting the text* at annotation
boundaries, which is only well-defined if annotation spans don't overlap — and nothing
in OpenAI's spec says they can't. Overlapping spans have no representation in a
block-split model at all.

**2. Offset units differ, silently.**
OpenAI: characters. Gemini legacy: **UTF-8 bytes**. Gemini current: undocumented. A
single normalization path that assumes one unit produces output that is correct in
testing (ASCII) and wrong in production (any non-Latin script). Google's own CLI shipped
this bug. Anything crossing these two formats must convert units explicitly, and must
decide what "character" means — Python `str` indices are code points, JavaScript string
indices are UTF-16 code units, and neither is bytes.

**3. What the offsets *point at* is unresolved even within OpenAI.**
Whether `start_index`/`end_index` bound the supported claim or the inline marker
determines whether rendering means "wrap this text in a link" or "replace this text with
a link." The docs don't say. Gemini's `segment.text` sidesteps this by including the
substring itself; OpenAI has no equivalent.

**4. Cardinality differs.**
Gemini legacy models one span → many sources natively (`groundingChunkIndices: [0, 1]`).
Anthropic models one block → many citations. OpenAI's annotation array is one entry per
citation, so many-sources-one-span is expressible only as overlapping annotations —
which loops back to problem 1.

**5. The quoted-source-text asymmetry.**
Only Anthropic returns *what the source actually said* (`cited_text`, API-derived and
therefore trustworthy). GLM returns a search-result snippet (`content`), which is close
but is the pre-answer snippet rather than the specific passage relied on. Gemini returns
`segment.text` — which is the *model's own words*, not the source's. OpenAI, Qwen and
DeepSeek return nothing. A UI that wants "hover to see the supporting quote" is only
fully implementable on one provider.

**6. Streaming semantics are documented for two providers out of six.**
Anthropic (`citations_delta`) and OpenAI (`annotation.added`) are specified. Gemini,
Qwen and GLM are not. For the offset-carrying formats this is the difference between
incremental rendering and buffering the entire response.

**7. Non-citation payloads ride in the citation envelope.**
Gemini's `searchEntryPoint.renderedContent` is a mandatory-display HTML widget.
Anthropic's `encrypted_content` / `encrypted_index` must be echoed back verbatim or the
next turn 400s. Neither is a citation, both arrive with the citations, and a
normalization layer that drops unrecognized fields breaks correctness in the Anthropic
case and compliance in the Gemini case.

---

## 5. Consequences for a Normalized Model

Not a design — just what the collected data constrains.

**Lossy by construction.** Any common model is the intersection of six formats, and the
intersection of "source pointer" and "output offset" is empty. A model that keeps both
is a union with per-provider optional fields, not a normalization. The realistic
common denominator across all six is `(url_or_source_id, title, marker_or_span)` —
which discards `cited_text`, page numbers, document indices, many-to-many support
mapping, and confidence.

**Unreconstructable once discarded.** Three things cannot be recovered downstream:
`cited_text` (only the provider has the source), the offset *unit* (bytes vs. chars is
not inferable from the numbers), and Anthropic's `encrypted_index` / `encrypted_content`
(opaque, and required for the next turn to work).

**Marker stripping is required, not optional.** Providers in Patterns C and D put
markers in the user-visible text. If those markers are also represented structurally,
rendering them twice is a visible bug; if they're stripped, any downstream offsets
computed against the unstripped text shift. Strip-then-index and index-then-strip give
different answers, and the choice has to be made once, globally.

**Streaming ordering hazards.** Two shapes exist: citations that arrive *attached to*
the text they describe (Anthropic — safe to render immediately) and citations that
arrive *referencing* text by offset (OpenAI, Gemini — safe only if the referenced text
has already been emitted, which OpenAI's event ordering guarantees and Gemini's does
not document). A uniform streaming contract has to assume the weaker guarantee.

**Validation is provider-dependent.** Pattern A citations cannot be wrong. Pattern B
citations can point at the wrong span but always name a real source. Pattern C citations
can name a source index that doesn't exist. Pattern D citations can be fabricated
entirely. Any common model that presents all four as "a citation" is flattening a real
trust gradient — and the UI implications differ (a hallucinated `[citation:7]` shown as
a broken link is worse than not showing it).

**The OpenAI-compatible gateway question dominates.** If citations are consumed through
an OpenAI-shaped endpoint, four of six providers lose their structured citations
outright and Qwen loses its sources specifically. That single fact constrains the design
space more than any schema difference in §4.3.

---

## 6. Open Questions

Empirical checks that documentation cannot settle:

1. **OpenAI `start_index`/`end_index` semantics** — claim span or marker span? (§3.1.1)
2. **Gemini `steps`-format offset units** — bytes (inherited) or characters (borrowed
   convention)? (§3.3.2)
3. **Gemini streaming** — when does `groundingMetadata` arrive, and are `segment`
   offsets relative to the chunk or the accumulated text? (§3.3.4)
4. **Can OpenAI annotation spans overlap?** Determines whether a block-split
   representation is expressible at all. (§4.3, point 1)
5. **Qwen / GLM streaming** — do `search_info` / `web_search` arrive in the first chunk,
   the last, or a dedicated one?
6. **Qwen marker reliability** — does `enable_citation` ever emit an index with no
   corresponding `search_results` entry?
7. **DIAL Core's existing surface** — deliberately out of scope per the agreed
   framing, but any decision about where citations get processed will need to know
   what DIAL Core and `aidial-sdk` already do with attachments and `reference_url`.

---

## 7. Sources

Retrieved 2026-08-05.

**Anthropic**
- [Citations](https://platform.claude.com/docs/en/build-with-claude/citations)
- [Search results](https://platform.claude.com/docs/en/build-with-claude/search-results)
- [Web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)

**OpenAI**
- [Web search](https://developers.openai.com/api/docs/guides/tools-web-search)
- [File search](https://developers.openai.com/api/docs/guides/tools-file-search)
- [Citation formatting](https://developers.openai.com/api/docs/guides/citation-formatting)
- [Responses streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events)

**Google**
- [Grounding with Google Search (current)](https://ai.google.dev/gemini-api/docs/google-search)
- [Grounding with Google Search (legacy generateContent)](https://ai.google.dev/gemini-api/docs/generate-content/google-search)
- [GroundingMetadata reference](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1beta1/GroundingMetadata)
- [gemini-cli #5955 — citation markers misplaced for multibyte text](https://github.com/google-gemini/gemini-cli/issues/5955)
- [firebase-ios-sdk #16328 — citationMetadata without endIndex](https://github.com/firebase/firebase-ios-sdk/issues/16328)

**Alibaba / Qwen**
- [Web search with large models](https://www.alibabacloud.com/help/en/model-studio/web-search)
- [大模型如何联网搜索](https://help.aliyun.com/zh/model-studio/web-search)

**DeepSeek**
- [DeepSeek API docs](https://api-docs.deepseek.com/)
- [DeepSeek-R1 repository — `search_answer` prompt template](https://github.com/deepseek-ai/DeepSeek-R1)

**Zhipu / GLM**
- [Web search tool guide](https://docs.z.ai/guides/tools/web-search)
- [Web search API reference](https://docs.z.ai/api-reference/tools/web-search)
