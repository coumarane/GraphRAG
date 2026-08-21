# 05 — Parser and OCR Specification

## Parser interface

```python
class MultimodalDocumentParser(Protocol):
    @property
    def name(self) -> str: ...

    async def inspect(self, source: ParseSource) -> ParserInspection: ...

    async def parse(
        self,
        source: ParseSource,
        options: ParseOptions,
    ) -> RawParserResult: ...
```

Parser adapters do not write directly to databases.

## Parser responsibilities

### MinerU

Preferred for:

- scientific and academic PDFs;
- multi-column layouts;
- formula-heavy documents;
- difficult tables;
- complex PDF layout.

### Docling

Preferred for:

- common enterprise PDFs;
- DOCX, PPTX and HTML;
- structured office documents;
- general layout and table extraction.

### Marker

Use as:

- PDF structured-text/Markdown fallback;
- parser comparison path;
- alternative for PDFs producing poor primary output.

### PaddleOCR

Preferred for:

- scanned PDF pages;
- document images;
- multilingual OCR;
- low extractable-text density;
- selective page OCR.

### pypdfium2

Use for:

- page rendering;
- PDF inspection;
- thumbnails;
- text-density estimation;
- bounding-box crops.

It is not the primary semantic parser.

## Automatic routing inputs

- extension and MIME type;
- page count;
- file size;
- extractable characters per page;
- scanned-page ratio;
- image coverage;
- probable table density;
- probable formula density;
- column count;
- detected language;
- profile: fast, balanced, accurate, scientific or scanned.

## Default routing

| Document characteristic | Primary | Fallbacks |
|---|---|---|
| DOCX/PPTX/HTML | Docling | format-specific safe extractor |
| General text PDF | Docling | MinerU, Marker |
| Scientific/formula PDF | MinerU | Docling, Marker |
| Complex multi-column PDF | MinerU | Docling, Marker |
| Scanned PDF | PaddleOCR | MinerU |
| Image | PaddleOCR | vision-assisted OCR |
| Mixed PDF | Docling or MinerU plus selective PaddleOCR | Marker |

## OCR modes

- `auto`: OCR only pages below text-density or quality threshold;
- `always`: OCR all supported pages;
- `never`: do not OCR and fail quality gates when required.

Store OCR engine, language, confidence and page-level result provenance.

## Parser subprocess safety

Where parsers run as subprocesses:

- use argument arrays, never shell interpolation;
- use temporary directories outside user-controlled paths;
- set CPU, memory and wall-clock limits when supported;
- validate generated paths before reading;
- capture stdout/stderr with size limits;
- clean temporary files reliably.
