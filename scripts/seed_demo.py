import argparse
from pathlib import Path

from app.config import Settings
from app.rag import KnowledgeBases

parser = argparse.ArgumentParser(description="Ingest example documents into KnowledgeBase")
parser.add_argument("--tenant", default="vnpost", help="Tenant ID (default: vnpost)")
parser.add_argument("--force", action="store_true", help="Force ingest even if DEMO_MODE is false")
args = parser.parse_args()

settings = Settings()
if not settings.demo_mode and not args.force:
    raise SystemExit("Seed data are fictitious and only allowed in demo mode (use --force to ingest into live tenant)")

kb = KnowledgeBases(settings).for_tenant(args.tenant)
for path in (Path(__file__).resolve().parents[1] / "examples").glob("*.txt"):
    result = kb.ingest(path.name, path.read_bytes())
    print(result["filename"], "duplicate" if result["duplicate"] else "indexed")
