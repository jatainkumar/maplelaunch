"""Entry point: `python -m app.serve`. Uses a selector event loop on Windows (required by psycopg async)."""

import asyncio
import os
import sys

import uvicorn


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    config = uvicorn.Config("app.main:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")),
                            proxy_headers=True, forwarded_allow_ips="*", log_level="info")
    asyncio.run(uvicorn.Server(config).serve())


if __name__ == "__main__":
    main()
