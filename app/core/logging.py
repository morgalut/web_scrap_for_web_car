from __future__ import annotations

import logging


def get_logger() -> logging.Logger:
    logger = logging.getLogger("trademobile_scraper")

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler()

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    logger.propagate = False

    return logger