"""Unit tests never touch a database. Importing the app reads its settings, and the default DATABASE_URL=pgserver
would boot an embedded Postgres (slow, and unavailable on some CI runners), so point it at a URL that is never
connected to. Engines are created lazily, so nothing tries to reach this host."""

import os

os.environ["DATABASE_URL"] = "postgresql://unit:tests@localhost:5432/unit_tests"
