# 12 — CLI Specification

Use Typer. Provide package command `graph-rag` and compatibility scripts under `scripts/`.

## Ingest

```bash
graph-rag ingest SOURCE \
  --tenant-id demo \
  --parser auto \
  --parser-profile balanced \
  --llm-implementation langchain \
  --text-model "$OPENAI_TEXT_MODEL" \
  --vision-model "$OPENAI_VISION_MODEL" \
  --embedding-model "$OPENAI_EMBEDDING_MODEL" \
  --ocr auto \
  --multimodal enabled \
  --graph enabled \
  --wait
```

Arguments:

- source;
- tenant ID;
- document ID/title/type;
- parser and profile;
- fallback parsers and failure mode;
- LLM implementation/provider/models;
- OCR mode/language/confidence;
- modality toggles;
- graph/entity-resolution/community toggles;
- chunking sizes;
- metadata/tags/security labels;
- force/resume/dry-run/wait;
- output format;
- log level and correlation ID.

## Query

```bash
graph-rag query "Compare the particle-size charts" \
  --tenant-id demo \
  --mode mix \
  --include-images \
  --include-graph-paths \
  --top-k 12 \
  --output json
```

## Additional commands

- `inspect-document`;
- `reindex`;
- `rebuild-vectors`;
- `rebuild-graph`;
- `delete-document`;
- `show-run`;
- `resume-run`.

## Exit codes

- 0 success;
- 1 unexpected failure;
- 2 invalid arguments;
- 3 unsupported document;
- 4 parsing failure;
- 5 storage failure;
- 6 model or embedding failure;
- 7 graph failure;
- 8 partial completion;
- 9 authorization or tenant failure.

## Output

JSON output must be stable and machine readable. Human table output may be concise but must include run ID, parser used, counts, duration and warnings.
