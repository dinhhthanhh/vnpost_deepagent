from pathlib import Path

from app.config import Settings
from app.rag import KnowledgeBases

settings = Settings()
if not settings.demo_mode:
    raise SystemExit("Seed data are fictitious and only allowed in demo mode")
kb = KnowledgeBases(settings).for_tenant("local-demo")
for path in (Path(__file__).resolve().parents[1] / "examples").glob("*.txt"):
    result = kb.ingest(path.name, path.read_bytes())
    print(result["filename"], "duplicate" if result["duplicate"] else "indexed")
