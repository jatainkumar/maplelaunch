"""Local development database. DATABASE_URL=pgserver starts an embedded Postgres 16 (pip package `pgserver`)
in apps/api/.data/pg, shared by the API and the mock-provider service. No Docker required."""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / ".data" / "pg"


def resolve(url: str) -> str:
    if url != "pgserver":
        return url
    import pgserver  # dev dependency only

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(str(DATA_DIR), cleanup_mode=None)
    return server.get_uri()
