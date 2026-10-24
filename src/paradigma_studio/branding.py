"""Studio identity and application storage paths."""

from pathlib import Path

APP_NAME = "ParaDigMa Studio"
DISTRIBUTION_NAME = "paradigma-studio"
USER_DATA_DIRECTORY = "ParaDigMaStudio"


def user_storage_path(root, *parts):
    """Use the Studio directory without discovering earlier installations."""
    return Path(root) / USER_DATA_DIRECTORY / Path(*parts)
