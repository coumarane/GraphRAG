"""Multimodal element processors."""

from graph_rag.application.multimodal.processors.chart import ChartProcessor
from graph_rag.application.multimodal.processors.equation import EquationProcessor
from graph_rag.application.multimodal.processors.image import DiagramProcessor, ImageProcessor
from graph_rag.application.multimodal.processors.table import TableProcessor

__all__ = [
    "ChartProcessor",
    "DiagramProcessor",
    "EquationProcessor",
    "ImageProcessor",
    "TableProcessor",
]
