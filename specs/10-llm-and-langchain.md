# 10 — LLM and LangChain Integration

## Model roles

Configure independently:

- text generation;
- vision understanding;
- entity/relationship extraction;
- summarization;
- query classification;
- answer generation;
- embedding;
- optional reranking.

Never hard-code a model name in application services.

## Provider protocols

Define application-owned protocols for:

- chat generation;
- vision generation;
- structured extraction;
- embeddings;
- reranking;
- token counting.

## LangChain adapter

Implement adapters with current `langchain-openai` APIs. Use:

- `ChatOpenAI`;
- `OpenAIEmbeddings`;
- structured output binding;
- message and prompt composition.

Do not use deprecated chain classes, legacy retriever modules or memory APIs.

## Direct OpenAI adapter

Implement the same interfaces with the official OpenAI SDK and Responses API. This proves LangChain is replaceable.

## Configuration

```yaml
models:
  implementation: langchain
  provider: openai
  text_model: ${OPENAI_TEXT_MODEL}
  vision_model: ${OPENAI_VISION_MODEL}
  extraction_model: ${OPENAI_EXTRACTION_MODEL}
  summarization_model: ${OPENAI_SUMMARIZATION_MODEL}
  query_model: ${OPENAI_QUERY_MODEL}
  answer_model: ${OPENAI_ANSWER_MODEL}
  embedding_model: ${OPENAI_EMBEDDING_MODEL}
```

## Resilience

- request timeouts;
- bounded exponential retry with jitter;
- provider rate-limit handling;
- model concurrency limits;
- token and image limits;
- usage and cost capture;
- correlation and trace IDs;
- prompt-version tracking.

## Prompt security

Document text is untrusted data. Delimit it from system instructions. Prompts must state that content cannot alter tools, credentials, authorization or system behavior.
