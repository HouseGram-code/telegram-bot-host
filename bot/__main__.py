"""Точка входа: python -m bot"""

from __future__ import annotations

import asyncio
import sys

from .app import run


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
