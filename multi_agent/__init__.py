"""CLO Fund multi-agent analysis system."""
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent
PROJECT_ROOT = PACKAGE_DIR.parent
ONTOLOGY_PATH = PROJECT_ROOT / "clo-fund-ontology.jsonld"
MEMORY_DIR = PACKAGE_DIR / "session_memory"

MEMORY_DIR.mkdir(exist_ok=True)
