"""Write a four-page citation fixture. Invoked with fpdf2, not an inlined PDF body."""

from __future__ import annotations

import sys

from fpdf import FPDF

PAGES = (
    "Page one introduces the citrine serum base.",
    "Page two cites ceramide at two percent for the barrier claim.",
    "Page three records the stability claim for twelve weeks.",
    "Page four states the usage is twice daily.",
)


def main() -> None:
    destination = sys.argv[1]
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    for text in PAGES:
        pdf.add_page()
        pdf.set_font("Helvetica", size=16)
        pdf.multi_cell(0, 10, text)
    pdf.output(destination)


if __name__ == "__main__":
    main()
