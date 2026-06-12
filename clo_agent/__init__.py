"""CLO fund-performance agent: Claude Opus 4.7 + tool use over the workbook."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
WORKBOOK_PATH = PROJECT_ROOT / "CLO_Fund_Domain_Data.xlsx"
ONTOLOGY_PATH = PROJECT_ROOT / "clo-fund-ontology.jsonld"
