import argparse
from pathlib import Path

from app.core.config import Settings
from app.rag import KnowledgeBases

parser = argparse.ArgumentParser(description="Ingest example documents into KnowledgeBase")
parser.add_argument("--tenant", default="vnpost", help="Tenant ID (default: vnpost)")
args = parser.parse_args()

settings = Settings()
kb = KnowledgeBases(settings).for_tenant(args.tenant)
for path in (Path(__file__).resolve().parents[1] / "examples").glob("*.txt"):
    result = kb.ingest(path.name, path.read_bytes())
    print(result["filename"], "duplicate" if result["duplicate"] else "indexed")
