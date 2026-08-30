"""MCP (Model Context Protocol) server exposing ingest/query/retrieval tools.

Gated behind ``MCP_ENABLED`` (default off). See ``docs/plugin-architecture-plan.md``
sibling doc and the MCP server implementation plan for design rationale --
notably: tenant identity is resolved once per connection from trusted
transport-layer headers (mirroring the API's ``X-Api-Service-Key`` path) and
is never accepted as a tool-call argument, since tool-call arguments are
model-generated and must not be a trust boundary.
"""

from __future__ import annotations
