"""Open WebUI package.

This module is intentionally import-light: ``open_webui.main`` is imported by
uvicorn on every start, while the CLI (typer → rich → pygments, ~15 MiB
resident) is only needed when the ``open-webui`` command is actually invoked.
The typer application is therefore resolved lazily via module ``__getattr__``
and the CLI dependency is an opt-in extra.
"""

from __future__ import annotations


def __getattr__(name: str):
    if name == 'app':
        try:
            from open_webui.cli import app
        except ImportError as e:
            if getattr(e, 'name', None) != 'typer':
                raise
            raise ImportError(
                "The `open-webui` CLI requires the optional 'typer' dependency. "
                'Install it with `pip install "open-webui[cli]"` (or '
                '`pip install -r backend/requirements-cli.txt`), or run the server '
                'directly with `python -m uvicorn open_webui.main:app`.'
            ) from e

        return app
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
