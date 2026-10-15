"""Central constants shared across core, cli, and web modules."""

# Application release version (single source of truth)
__version__: str = "1.3.0"

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

