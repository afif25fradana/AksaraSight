"""Central constants shared across core, cli, and gui modules."""

# Application release version (single source of truth)
__version__: str = "1.1.0"

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

