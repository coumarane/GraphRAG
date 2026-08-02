# 06 — Multimodal Processing

## Principle

A non-text element is interpreted with its local document context. Context enrichment must not overwrite the original parsed element.

## Element context

Build a bounded `ElementContext` containing:

- document title and type;
- heading and section path;
- caption;
- preceding and following elements;
- nearby table/image/equation summaries;
- page number;
- relevant footnotes and references;
- tenant-safe business metadata.

Default limits:

- 3 preceding elements;
- 3 following elements;
- 1,800 input tokens;
- exclude repetitive page headers/footers.

## Image processor

Output schema:

- concise visual summary;
- visible labels and text;
- objects and relationships;
- likely purpose in the section;
- relevant facts supported by the image;
- uncertainty notes;
- source element and asset IDs.

## Chart processor

Output schema:

- chart type;
- title;
- axes and units;
- legend/series;
- readable values;
- trends and comparisons;
- anomalies;
- conclusions explicitly supported by the chart;
- unreadable or ambiguous regions.

Never invent numeric values.

## Table processor

Produce:

- normalized cell grid;
- structured JSON;
- Markdown;
- semantic summary;
- important row/column observations;
- row chunks only when useful;
- links to entities and measurements.

## Equation processor

Produce:

- LaTeX/MathML when available;
- variable list;
- definition and contextual purpose;
- relationship to nearby prose;
- searchable semantic description.

Do not solve the equation unless the user query requires it.

## Composite chunks

Create a multimodal composite chunk when text and a non-text element are semantically inseparable. The chunk must include the element description and references to the original asset.

## Model calls

- batch only compatible requests;
- apply image-size and token limits;
- record model, provider, prompt version, latency and usage;
- use retry with bounded exponential backoff;
- permit per-modality enable/disable configuration.
