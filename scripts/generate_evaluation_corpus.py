#!/usr/bin/env python3
"""Regenerate examples/sample.pdf and evaluation/corpus/*.pdf."""

from __future__ import annotations

from pathlib import Path

from enterprise_rag.infrastructure.intake.pdf_bytes import build_simple_pdf

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evaluation" / "corpus"
EXAMPLES = ROOT / "examples"

DOCS: dict[str, tuple[str, list[str]]] = {
    "text_heavy.pdf": (
        "Viscosity Study Report",
        [
            "Silicone oil viscosity decreases with temperature.",
            "At 20C the measured viscosity is 12 cP.",
            "At 40C the measured viscosity is 8 cP.",
            "Packaging process uses sealed HDPE containers.",
            "Ingredient X is restricted under Regulation EU-1234.",
        ],
    ),
    "scanned.pdf": (
        "Scanned Lab Notes",
        [
            "OCR candidate page with sparse extractable text.",
            "Observed haze in sample A after heating.",
        ],
    ),
    "scientific_equations.pdf": (
        "Rheology Equations",
        [
            "Equation 4 calculates dynamic viscosity eta = tau / gamma_dot.",
            "Where tau is shear stress and gamma_dot is shear rate.",
            "Equation 4 is used for Newtonian silicone oils.",
        ],
    ),
    "charts.pdf": (
        "Chart Appendix",
        [
            "Figure 1: Viscosity versus Temperature chart.",
            "The chart supports the claim that viscosity falls as temperature rises.",
            "Series Sample A: 20C->12cP, 40C->8cP.",
        ],
    ),
    "complex_tables.pdf": (
        "Supplier Comparison Tables",
        [
            "Supplier A density = 0.97 g/mL at 25C.",
            "Supplier B density = 0.94 g/mL at 25C.",
            "Table columns: Supplier | Density | Viscosity | Lot.",
        ],
    ),
    "shared_entities_a.pdf": (
        "Supplier A Datasheet",
        [
            "Ingredient X density is 0.970 g/mL.",
            "Ingredient X is linked to Regulation EU-1234.",
            "Silicone oil grade SO-100.",
        ],
    ),
    "shared_entities_b.pdf": (
        "Supplier B Datasheet",
        [
            "Ingredient X density is 0.940 g/mL.",
            "Conflicting measurement versus Supplier A.",
            "Silicone oil grade SO-100 shared across suppliers.",
        ],
    ),
}


def main() -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    for name, (title, lines) in DOCS.items():
        (CORPUS / name).write_bytes(build_simple_pdf(title=title, lines=lines))
    (EXAMPLES / "sample.pdf").write_bytes(
        build_simple_pdf(
            title="Sample Enterprise Document",
            lines=[
                "Silicone oil viscosity decreases with temperature.",
                "Figure 1 chart supports the viscosity claim.",
                "Equation 4 calculates eta = tau / gamma_dot.",
                "Ingredient X is connected to Regulation EU-1234.",
            ],
        )
    )
    print(f"wrote {len(DOCS)} corpus pdfs and examples/sample.pdf")


if __name__ == "__main__":
    main()
