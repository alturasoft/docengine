"""DocEngine — Main Entry Point.

Supports two modes:
1. FastAPI server:  python main.py serve  (or via uvicorn main:app)
2. CLI:             python main.py extract <source>

The `app` module-level variable is exposed for uvicorn/gunicorn.
"""

from __future__ import annotations

import sys

import click
import uvicorn

from app.api.main import create_app
from app.cli.commands import cli, skill

# FastAPI application instance (used by uvicorn/gunicorn)
# uvicorn main:app --host 0.0.0.0 --port 8000
app = create_app()


@click.group()
def main() -> None:
    """DocEngine — Motor de Extracción Documental."""


@main.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind host.")
@click.option("--port", default=8000, show_default=True, help="Bind port.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload (dev).")
@click.option(
    "--workers", default=1, show_default=True, help="Number of worker processes."
)
def serve(host: str, port: int, reload: bool, workers: int) -> None:
    """Start the DocEngine REST API server."""
    click.echo(f"🚀 Starting DocEngine API on {host}:{port}")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
        log_level="info",
    )


# Register CLI commands under the main group
main.add_command(cli, name="extract")
main.add_command(skill, name="skill")


if __name__ == "__main__":
    # Allow both:
    #   python main.py serve
    #   python main.py extract document.pdf
    #   python main.py process-rag document.pdf
    #   python main.py skill analyze CRI
    if len(sys.argv) > 1 and sys.argv[1] in ("extract", "process-rag", "version"):
        cli(standalone_mode=True)
    elif len(sys.argv) > 1 and sys.argv[1] == "skill":
        skill(standalone_mode=True)
    else:
        main(standalone_mode=True)

