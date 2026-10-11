"""Studio identity and nondestructive access to earlier installations' storage."""

from pathlib import Path

APP_NAME = "ParaDigMa Studio"
DISTRIBUTION_NAME = "paradigma-studio"
USER_DATA_DIRECTORY = "ParaDigMaStudio"
LEGACY_USER_DATA_DIRECTORY = "ParaDigMaDesktop"


def user_storage_path(root, *parts):
    """Use Studio for new data; retain existing paths and saved-result references."""
    preferred = Path(root) / USER_DATA_DIRECTORY / Path(*parts)
    legacy = Path(root) / LEGACY_USER_DATA_DIRECTORY / Path(*parts)
    return legacy if not preferred.exists() and legacy.exists() else preferred
