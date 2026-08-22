# 08 — Knowledge Graph

## Graph layers

### Structural graph

Nodes:

- Tenant;
- Document;
- DocumentVersion;
- Page;
- Section;
- Chunk;
- TextElement;
- Image;
- Chart;
- Diagram;
- Table;
- TableRow;
- Equation;
- Caption.

Relationships:

- HAS_VERSION;
- HAS_PAGE;
- HAS_SECTION;
- HAS_ELEMENT;
- HAS_CHUNK;
- NEXT_ELEMENT;
- PREVIOUS_ELEMENT;
- HAS_CAPTION;
- APPEARS_ON;
- DERIVED_FROM;
- REFERENCES;
- CONTINUES_ON;
- HAS_ROW.

### Semantic graph

Nodes:

- Entity;
- Person;
- Organization;
- Product;
- Ingredient;
- Chemical;
- Regulation;
- Location;
- Concept;
- Topic;
- Claim;
- Measurement;
- Community.

Controlled relationships:

- MENTIONS;
- RELATES_TO;
- SUPPORTS;
- CONTRADICTS;
- EXPLAINS;
- ILLUSTRATES;
- MEASURES;
- COMPARES;
- PRODUCED_BY;
- CONTAINS_INGREDIENT;
- REGULATED_BY;
- PART_OF;
- SIMILAR_TO;
- MEMBER_OF_COMMUNITY.

Unknown LLM predicates map to `RELATES_TO` and preserve the proposed predicate as metadata.

## Extraction

Extract from parent or composite chunks:

- entities and aliases;
- typed mentions;
- relationships;
- claims;
- measurements and units;
- topics;
- source element IDs;
- confidence.

Use Pydantic structured output and validate all values.

## Entity resolution

Resolution signals:

- exact normalized identifier;
- exact alias;
- normalized name;
- entity type compatibility;
- acronym match;
- fuzzy lexical score;
- embedding similarity;
- graph-neighborhood compatibility;
- source authority.

Do not merge by lexical similarity alone. Store merge strategy, confidence and manual-review state.

## Cypher safety

- use parameterized Cypher;
- labels and relationship types come only from enums or explicit allowlists;
- never inject raw LLM output into a query;
- every query includes tenant constraints;
- apply bounded graph depth and result limits.

## Community enrichment

Optional workflow:

- build tenant-scoped graph projection;
- run supported community detection when Neo4j GDS exists;
- fallback to application-level clustering or skip cleanly;
- generate evidence-linked summaries;
- index summaries in Qdrant.
