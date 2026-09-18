# Tests always run on an isolated in-memory SQLite, never on the dev/prod
# database — force (not setdefault) so a leaked DATABASE_URL cannot redirect
# the drop_all/create_all fixture at a real database.
import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["SEED_ON_EMPTY"] = "false"
