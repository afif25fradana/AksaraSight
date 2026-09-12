"""Central constants shared across core, cli, and gui modules."""

# Supported document file extensions for ingestion and pre-flight validation
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",
    ".pdf",
})
