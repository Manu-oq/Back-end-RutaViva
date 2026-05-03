from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401,E402
from app.db.session import BASE_CATEGORIES, init_db


async def main() -> None:
    await init_db()
    category_list = ", ".join(
        f"{category['name']} ({category['id']})"
        for category in BASE_CATEGORIES
    )
    print(f"Categorías base aseguradas correctamente: {category_list}")


if __name__ == "__main__":
    asyncio.run(main())
