"""Built-in Document Intelligence models.

Declarative data, not an if/elif dispatcher -- analogous to
``application/plugins/parsers.py::CORE_PARSER_DESCRIPTORS``. No extraction
logic reads these yet (that starts in a later phase); this is only the
catalog a client selects a model/field set from.
"""

from __future__ import annotations

from graph_rag.application.document_intelligence.models import (
    DocumentIntelligenceModel,
    FieldType,
    ModelFieldSpec,
    ModelType,
)


def _field(
    name: str,
    label: str,
    field_type: FieldType,
    *,
    default_selected: bool = False,
    promote_to_document_metadata: bool = False,
) -> ModelFieldSpec:
    return ModelFieldSpec(
        name=name,
        label=label,
        field_type=field_type,
        default_selected=default_selected,
        promote_to_document_metadata=promote_to_document_metadata,
    )


BUILTIN_DOCUMENT_INTELLIGENCE_MODELS: tuple[DocumentIntelligenceModel, ...] = (
    DocumentIntelligenceModel(
        model_key="layout",
        name="Layout",
        model_type=ModelType.PREBUILT,
        is_builtin=True,
        fields=[
            _field("title", "Title", FieldType.STRING, default_selected=True),
            _field("page_count", "Page count", FieldType.INTEGER, default_selected=True),
        ],
    ),
    DocumentIntelligenceModel(
        model_key="general_document",
        name="General Document",
        model_type=ModelType.PREBUILT,
        is_builtin=True,
        fields=[
            _field(
                "title",
                "Title",
                FieldType.STRING,
                default_selected=True,
                promote_to_document_metadata=True,
            ),
            _field(
                "document_type",
                "Document type",
                FieldType.STRING,
                default_selected=True,
                promote_to_document_metadata=True,
            ),
            _field("effective_date", "Effective date", FieldType.DATE),
        ],
    ),
    DocumentIntelligenceModel(
        model_key="sds",
        name="Safety Data Sheet",
        model_type=ModelType.PREBUILT,
        is_builtin=True,
        fields=[
            _field(
                "product_name",
                "Product name",
                FieldType.STRING,
                default_selected=True,
                promote_to_document_metadata=True,
            ),
            _field(
                "manufacturer",
                "Manufacturer",
                FieldType.STRING,
                default_selected=True,
                promote_to_document_metadata=True,
            ),
            _field("cas_number", "CAS number", FieldType.STRING, default_selected=True),
            _field("hazard_classification", "Hazard classification", FieldType.LIST),
            _field("signal_word", "Signal word", FieldType.STRING),
            _field("precautionary_statements", "Precautionary statements", FieldType.LIST),
            _field("revision_date", "Revision date", FieldType.DATE),
        ],
    ),
    DocumentIntelligenceModel(
        model_key="certificate_of_analysis",
        name="Certificate of Analysis",
        model_type=ModelType.PREBUILT,
        is_builtin=True,
        fields=[
            _field(
                "product_name",
                "Product name",
                FieldType.STRING,
                default_selected=True,
                promote_to_document_metadata=True,
            ),
            _field(
                "batch_number",
                "Batch number",
                FieldType.STRING,
                default_selected=True,
                promote_to_document_metadata=True,
            ),
            _field("lot_number", "Lot number", FieldType.STRING, default_selected=True),
            _field("manufacture_date", "Manufacture date", FieldType.DATE),
            _field("expiry_date", "Expiry date", FieldType.DATE),
            _field("test_results", "Test results", FieldType.TABLE, default_selected=True),
            _field("specification_reference", "Specification reference", FieldType.STRING),
        ],
    ),
    DocumentIntelligenceModel(
        model_key="product_datasheet",
        name="Product Datasheet",
        model_type=ModelType.PREBUILT,
        is_builtin=True,
        fields=[
            _field("product_name", "Product name", FieldType.STRING, default_selected=True),
            _field("model_number", "Model number", FieldType.STRING, default_selected=True),
            _field("specifications", "Specifications", FieldType.TABLE, default_selected=True),
            _field("operating_temperature_range", "Operating temperature range", FieldType.STRING),
            _field("weight", "Weight", FieldType.NUMBER),
            _field("dimensions", "Dimensions", FieldType.STRING),
        ],
    ),
    DocumentIntelligenceModel(
        model_key="raw_material_specification",
        name="Raw Material Specification",
        model_type=ModelType.PREBUILT,
        is_builtin=True,
        fields=[
            _field("material_name", "Material name", FieldType.STRING, default_selected=True),
            _field("cas_number", "CAS number", FieldType.STRING, default_selected=True),
            _field("grade", "Grade", FieldType.STRING),
            _field(
                "purity_percentage",
                "Purity",
                FieldType.PERCENTAGE,
                default_selected=True,
            ),
            _field("supplier", "Supplier", FieldType.STRING),
            _field("specification_limits", "Specification limits", FieldType.TABLE),
        ],
    ),
    DocumentIntelligenceModel(
        model_key="scientific_document",
        name="Scientific Document",
        model_type=ModelType.PREBUILT,
        is_builtin=True,
        fields=[
            _field("title", "Title", FieldType.STRING, default_selected=True),
            _field("authors", "Authors", FieldType.LIST, default_selected=True),
            _field("abstract", "Abstract", FieldType.STRING, default_selected=True),
            _field("publication_date", "Publication date", FieldType.DATE),
            _field("doi", "DOI", FieldType.STRING),
            _field("keywords", "Keywords", FieldType.LIST),
        ],
    ),
)


def builtin_model_by_key(model_key: str) -> DocumentIntelligenceModel | None:
    key = model_key.strip().lower()
    for model in BUILTIN_DOCUMENT_INTELLIGENCE_MODELS:
        if model.model_key == key:
            return model
    return None
