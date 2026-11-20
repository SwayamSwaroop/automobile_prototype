import logging


def setup_logger(
    name: str,
) -> logging.Logger:
    """
    Temporary backward-compatible logger factory.

    Logging configuration is now handled centrally
    by apps.app_logging.

    Existing modules can continue using:

        logger = setup_logger(__name__)

    until they are migrated to:

        logger = logging.getLogger(__name__)
    """

    return logging.getLogger(name)
