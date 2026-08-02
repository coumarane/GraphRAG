# Graph schema

Structural nodes (Document, DocumentVersion, Page, Section, Chunk, …) are version-scoped. Shared semantic entities (Chemical, Ingredient, Regulation, …) are tenant-scoped and deleted only when no MENTIONS remain.

See `specs/08-knowledge-graph.md` and `contracts/` for the authoritative vocabulary.
