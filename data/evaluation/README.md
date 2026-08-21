# Evaluation fixtures

- `corpus/` — synthetic multimodal PDFs for offline evaluation
- `questions.json` — annotated questions covering TEMP.md §28 scenarios

Regenerate corpus PDFs with:

```bash
uv run python scripts/generate_evaluation_corpus.py
```
