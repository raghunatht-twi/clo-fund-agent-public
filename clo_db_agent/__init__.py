"""CLO fund-performance agent — PostgreSQL backend."""

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
ONTOLOGY_PATH = PROJECT_ROOT / "clo-fund-ontology.jsonld"

# F-03: externalised — set DATABASE_URL in the environment for non-local deployments
DB_DSN = os.environ.get("DATABASE_URL", "host=/tmp port=5432 dbname=postgres")
