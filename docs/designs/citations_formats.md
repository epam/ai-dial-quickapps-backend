# Citations formats

## OpenAI / Responses API + Chat completion API

**Citations in the response**

Citations live in a block "annotations" in the response.

```json
{
  ...,
  "annotations": [
    {
      "type": "url_citation",
      "url": "https://example.com/source",
      "title": "Example source",
      "start_index": 12,
      "end_index": 34
    }
  ],
  ...
}
```

* Responses API ref: [link](https://developers.openai.com/api/reference/resources/responses#(resource)%20responses%20%3E%20(model)%20response_output_text%20%3E%20(schema)%20%3E%20(property)%20annotations%20%3E%20(items)%20%3E%20(variant)%201)

start_index and end_index point to the span into the response text.

Place in the Responses API:
```
response
└── output[]
    └── content[]
        └── {
                "type": "output_text",
                "text": "...",
                "annotations": [...]
             }
```

Place in the Completion API:
```
response
└── choices[]
    └── message
        ├── content: "..."
        └── annotations: [...]
```

**Streaming**

There is a special event: `response.output_text.annotation.added`, which comes across text blocks, and is supplied with `annotaitons` block.

* [link](https://developers.openai.com/api/reference/resources/responses/streaming-events#response.output_text.annotation.added)

**Citations in generated text**

Model can generate citations in the text. OpenAI recommends a citation format with delimeters:
| Chat | Purpose | Recommended |
| --- | --- | --- |
| CITATION_START | 	Opens the citation marker. | \ue200 |
| CITATION_DELIMITER | Separates fields inside the marker. | \ue202 |
| CITATION_STOP | Closes the citation marker. | \ue201 |

Full-structure example:
```
{CITATION_START}cite{CITATION_DELIMITER}turn0file1{CITATION_DELIMITER}L8-L13{CITATION_STOP}
```

* Citation formatting: [link](https://developers.openai.com/api/docs/guides/citation-formatting)

## Anthropic / Messages API

**Citations in the response**

Citations live in a block "citations" attached to a `text` content block.

Full response for the document `"The grass is green. The sky is blue."` and the question
`"What color is the grass and sky?"`:

```json
{
  "id": "msg_<id>",
  "type": "message",
  "role": "assistant",
  "model": "claude-opus-5",
  "content": [
    {
      "type": "text",
      "text": "According to the document, "
    },
    {
      "type": "text",
      "text": "the grass is green",
      "citations": [
        {
          "type": "char_location",
          "cited_text": "This is the exact text from the document which is being cited",
          "document_index": 0,
          "document_title": "Example Document",
          "start_char_index": 0,
          "end_char_index": 20
        }
      ]
    },
    ...
  ],
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 610,
    "output_tokens": 89
  }
}
```

* Messages API ref: [link](https://platform.claude.com/docs/en/build-with-claude/citations)

Location variants (`type`), each with `cited_text`:
| type | Source | Range fields |
| --- | --- | --- |
| `char_location` | plain-text document | `start_char_index` / `end_char_index` (0-indexed, exclusive) |
| `page_location` | PDF | `start_page_number` / `end_page_number` (1-indexed, exclusive) |
| `content_block_location` | custom-content document | `start_block_index` / `end_block_index` |
| `search_result_location` | `search_result` block (RAG) | `start_block_index` / `end_block_index` + `source`, `title`, `search_result_index` |
| `web_search_result_location` | server-side web search | `url`, `title`, `encrypted_index` |

Document-based variants also carry `document_index` and `document_title`.

**Limitations**

Opt-in per source: `"citations": {"enabled": true}` on every `document` / `search_result` block (all or none).
There are no character offsets into the response text — the model instead **splits its answer into
several `text` blocks**, and only the cited ones carry a `citations` array. The span is the block's
own `text`; the offsets point into the *source*, not the answer.

## Google / Gemini

Gemini has two surfaces with **different citation formats**:

* **Interactions API**
* **`generateContent`** - legacy in the docs

**Interactions API**

**Citations in the response**

Citations live in a block "annotations" attached to a `text` item of the `model_output` step —
the same shape as OpenAI's.

```json
{
  "steps": [
    {
      "type": "google_search_call",
      "arguments": {
        "queries": ["who won euro 2024"]
      }
    },
    {
      "type": "google_search_result",
      "call_id": "search_001",
      "result": [
        {
          "search_suggestions": "<!-- HTML and CSS for the widget -->"
        }
      ]
    },
    {
      "type": "model_output",
      "content": [
        {
          "type": "text",
          "text": "Spain won Euro 2024, defeating England 2-1 in the final.",
          "annotations": [
            {
              "type": "url_citation",
              "url": "https://vertexaisearch.cloud.google.com/...",
              "title": "uefa.com",
              "start_index": 0,
              "end_index": 56
            }
          ]
        }
      ]
    }
  ]
}
```

* Ref: [link](https://ai.google.dev/gemini-api/docs/google-search)

`start_index` and `end_index` point to the span into the response text - same semantics as OpenAI.

### generateContent

**Citations in the response**

Citations live in a block "groundingMetadata" on a candidate — a *sidecar* structure, not attached
to the text.

```json
{
  "webSearchQueries": ["UEFA Euro 2024 winner", "who won euro 2024"],
  "searchEntryPoint": {
    "renderedContent": "<!-- HTML and CSS for the search widget -->"
  },
  "groundingChunks": [
    {"web": {"uri": "https://vertexaisearch.cloud.google.com/...", "title": "aljazeera.com"}},
    {"web": {"uri": "https://vertexaisearch.cloud.google.com/...", "title": "uefa.com"}}
  ],
  "groundingSupports": [
    {
      "segment": {
        "startIndex": 0,
        "endIndex": 85,
        "text": "Spain won Euro 2024, defeatin..."
      },
      "groundingChunkIndices": [0]
    }
  ]
}
```
