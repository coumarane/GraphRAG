"""Plugin API versioning policy.

The plugin contract is the set of ``typing.Protocol`` modules under
``graph_rag.domain`` (storage, parsing, models, chunks, graph, ingestion).
Domain and application code must not import provider SDKs.

Until a separate ``graph-rag-sdk`` distribution exists:

- Additive protocol changes (new optional method with a default, new field on a
  request model with a default) are a **minor** host version bump.
- Signature changes, removed methods, or tightened types are a **major** bump.
- Third-party plugins declare ``min_host`` against this scheme in their
  packaging metadata.

Core adapters are in-tree factories, not entry points. Entry-point groups are
listed in ``pyproject.toml`` under ``[project.entry-points."graph_rag.*"]``.
"""
