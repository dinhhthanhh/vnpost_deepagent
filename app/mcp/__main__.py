"""Entry point for python -m app.mcp."""
from app.mcp.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
