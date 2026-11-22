"""Hjælpeværktøj: vis alle synlige elementer i Hinge lige nu (ændrer ingenting)."""
import asyncio

from wda import phone, visible


async def main() -> None:
    async with phone() as c:
        print(await c.get_window_size(session_id=c.session_id))
        for e in await visible(c):
            print(f'{e["type"]:12} {str(e["name"])[:44]!r:48} ({e["x"]},{e["y"]},{e["w"]},{e["h"]})')


if __name__ == "__main__":
    asyncio.run(main())
