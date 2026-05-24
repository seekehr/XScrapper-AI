from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logger(name: str = "xscrapper", level: int = logging.INFO) -> logging.Logger:
    # Only attach handlers to the root "xscrapper" logger; children inherit them via propagation
    root = logging.getLogger("xscrapper")
    if not root.handlers:
        root.setLevel(level)

        formatter = logging.Formatter(
            "%(asctime)s | %(name)-18s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(formatter)
        root.addHandler(console)

        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(logs_dir / "xscrapper.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    return logging.getLogger(name)
