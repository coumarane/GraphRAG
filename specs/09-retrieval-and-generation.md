# 09 — Retrieval and Generation

## Retrieval modes

### `naive`

Dense vector search on child chunks followed by parent expansion.

### `local`

Resolve query entities, traverse bounded neighborhoods, retrieve claims and source chunks.

### `global`

Retrieve community summaries, document summaries and high-level topics.

### `hybrid`

Combine vector, lexical, metadata and graph signals.

### `multimodal`

Prioritize images, charts, tables and equations plus local context and assets.

### `mix`

Combine local, global, vector and multimodal evidence.

### `auto`

Classify query intent and modality needs, then select one or more strategies.

## Query pipeline

1. normalize question;
2. detect language;
3. classify intent and modality;
4. extract query entities;
5. create tenant-safe filters;
6. execute selected retrieval branches concurrently;
7. normalize scores;
8. fuse with reciprocal-rank fusion or configured explainable fusion;
9. deduplicate;
10. rerank optionally;
11. expand parents, neighbors and provenance;
12. assemble bounded context;
13. generate answer;
14. validate citations and grounding.

## Hybrid score inputs

- dense similarity;
- sparse/full-text score;
- entity overlap;
- graph distance;
- relation confidence;
- source authority;
- recency where relevant;
- metadata match;
- reranker score.

Normalize before fusion. Log score components.

## Context assembly

Prioritize evidence diversity and avoid repeated overlapping chunks. Include structured table data rather than only table summaries when needed. Include asset references for visual evidence.

## Answer contract

Return:

- answer text;
- chosen retrieval mode;
- citations;
- optional graph paths;
- warnings when evidence is weak or conflicting;
- retrieval trace identifier.

## Citation validation

After generation:

- reject unknown citation IDs;
- ensure cited evidence was in context;
- verify tenant and document identity;
- verify page and element exist;
- remove unsupported claims or regenerate once under a strict retry policy.
