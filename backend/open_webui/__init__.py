import base64
import os
import random
import sys
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

app = typer.Typer()

KEY_FILE = Path.cwd() / '.webui_secret_key'
DEFAULT_SECRET_KEY_LENGTH = 24


def version_callback(value: bool) -> None:
    if value:
        from open_webui.env import VERSION

        # LICENSE covers this Open WebUI CLI identifier.
        # Do not alter, remove, obscure, or replace it except as LICENSE permits:
        # https://docs.openwebui.com/license.
        typer.echo(f'Open WebUI version: {VERSION}')
        raise typer.Exit()


@app.command()
def main(
    version: Annotated[bool | None, typer.Option('--version', callback=version_callback)] = None,
):
    pass


@app.command()
def serve(
    host: str = '0.0.0.0',
    port: int = 8080,
):
    os.environ['FROM_INIT_PY'] = 'true'
    if os.getenv('WEBUI_SECRET_KEY') is None:
        typer.echo('Loading WEBUI_SECRET_KEY from file, not provided as an environment variable.')
        if not KEY_FILE.exists():
            key_length = int(os.getenv('WEBUI_SECRET_KEY_LENGTH', DEFAULT_SECRET_KEY_LENGTH))
            if key_length < 1:
                raise ValueError('WEBUI_SECRET_KEY_LENGTH must be a positive integer')
            typer.echo(f'Generating a new secret key and saving it to {KEY_FILE}')
            KEY_FILE.write_bytes(base64.b64encode(random.randbytes(key_length)))
        typer.echo(f'Loading WEBUI_SECRET_KEY from {KEY_FILE}')
        os.environ['WEBUI_SECRET_KEY'] = KEY_FILE.read_text()

    import open_webui.main  # noqa: F401
    from open_webui.env import UVICORN_WORKERS, UVICORN_WS_PER_MESSAGE_DEFLATE

    # On Windows, uvicorn's default loop factory hardcodes ProactorEventLoop,
    # which is incompatible with psycopg v3 async.  Setting loop='none' lets
    # asyncio.run() respect the WindowsSelectorEventLoopPolicy set in db.py.
    loop = 'none' if sys.platform == 'win32' else 'auto'

    uvicorn.run(
        'open_webui.main:app',
        host=host,
        port=port,
        forwarded_allow_ips='*',
        workers=UVICORN_WORKERS,
        ws_per_message_deflate=UVICORN_WS_PER_MESSAGE_DEFLATE,
        loop=loop,
    )


@app.command()
def dev(
    host: str = '0.0.0.0',
    port: int = 8080,
    reload: bool = True,
):
    from open_webui.env import UVICORN_WS_PER_MESSAGE_DEFLATE

    uvicorn.run(
        'open_webui.main:app',
        host=host,
        port=port,
        reload=reload,
        forwarded_allow_ips='*',
        ws_per_message_deflate=UVICORN_WS_PER_MESSAGE_DEFLATE,
    )


if __name__ == '__main__':
    app()
