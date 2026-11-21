"""Run the MCP server over stdio: `python -m app.mcp` (from backend/, with DATABASE_URL set or infra/.env present).

stdout carries the MCP protocol, so all logging goes to stderr.
"""

import sys

from app.core.logging import configure_logging
from app.mcp.server import build_server


def main() -> None:
    configure_logging(stream=sys.stderr)
    build_server().run("stdio")


if __name__ == "__main__":
    main()
