# Evaluation

Offline evaluation for retrieval quality, citation fidelity and answer groundedness.

## Corpus

Versioned fixtures under `evaluation/corpus/`:

| File | Intent |
|---|---|
| `text_heavy.pdf` | Dense prose + packaging / regulation mentions |
| `scanned.pdf` | Sparse/OCR-like page |
| `scientific_equations.pdf` | Equation 4 / viscosity formula |
| `charts.pdf` | Viscosity-vs-temperature chart claim |
| `complex_tables.pdf` | Supplier comparison tables |
| `shared_entities_a.pdf` / `shared_entities_b.pdf` | Shared Ingredient X with conflicting density |

Questions live in `evaluation/questions.json`.

## Metrics

Implemented in `enterprise_rag.application.evaluation`:

- retrieval hit rate
- context precision / recall
- citation precision
- answer groundedness
- unsupported-claim rate
- graph-path accuracy
- entity-resolution precision
- mean latency

Live OpenAI runs are gated by `RUN_LIVE_OPENAI_TESTS=true` and the `live_openai` pytest marker.

## Run

```bash
uv run pytest tests/evaluation -m evaluation
```

Regenerate synthetic PDFs:

```bash
uv run python -c "from pathlib import Path; from enterprise_rag.infrastructure.intake.pdf_bytes import build_simple_pdf; Path('examples/sample.pdf').write_bytes(build_simple_pdf(title='Sample', lines=['hello']))"
```
