import asyncio
import os
import sys

import uvicorn


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    config = uvicorn.Config("mock.main:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8001")),
                            proxy_headers=True, forwarded_allow_ips="*", log_level="info")
    asyncio.run(uvicorn.Server(config).serve())


if __name__ == "__main__":
    main()
