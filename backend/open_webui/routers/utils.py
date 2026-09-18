from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from open_webui.config import DATA_DIR, ENABLE_ADMIN_EXPORT
from open_webui.constants import ERROR_MESSAGES
from open_webui.models.chats import ChatTitleMessagesForm
from open_webui.models.config import Config
from open_webui.utils.auth import get_admin_user, get_verified_user
from open_webui.utils.misc import get_gravatar_url
from pydantic import BaseModel
from starlette.responses import FileResponse

log = logging.getLogger(__name__)

router = APIRouter()


@router.get('/gravatar')
async def get_gravatar(email: str, user=Depends(get_verified_user)):
    return get_gravatar_url(email)


class CodeForm(BaseModel):
    code: str


@router.post('/code/format')
async def format_code(form_data: CodeForm, user=Depends(get_admin_user)):
    try:
        # black is heavy (mypyc extension, ~10 MiB); import it only when the
        # admin actually uses the formatting endpoint.
        import black

        formatted_code = black.format_str(form_data.code, mode=black.Mode())
        return {'code': formatted_code}
    except ImportError as e:
        raise HTTPException(status_code=501, detail=f'Code formatting is not available: {e}')
    except black.NothingChanged:
        return {'code': form_data.code}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post('/pdf')
async def download_chat_as_pdf(form_data: ChatTitleMessagesForm, user=Depends(get_verified_user)):
    try:
        # Imported lazily so fpdf/fontTools are not kept in memory at idle.
        from open_webui.utils.pdf_generator import PDFGenerator

        pdf_bytes = PDFGenerator(form_data).generate_chat_pdf()

        return Response(
            content=pdf_bytes,
            media_type='application/pdf',
            headers={'Content-Disposition': 'attachment;filename=chat.pdf'},
        )
    except ImportError as e:
        raise HTTPException(status_code=501, detail=f'PDF export is not available: {e}')
    except Exception as e:
        log.exception(f'Error generating PDF: {e}')
        raise HTTPException(status_code=400, detail=str(e))


@router.get('/db/download')
async def download_db(user=Depends(get_admin_user)):
    """Download the raw SQLite database file (admin-only, SQLite deployments only)."""
    if not ENABLE_ADMIN_EXPORT:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)

    # Lazy import avoids circular dependency at module load time
    from open_webui.internal.db import engine

    if engine.name != 'sqlite':
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=ERROR_MESSAGES.DB_NOT_SQLITE)

    return FileResponse(
        str(engine.url.database),
        media_type='application/octet-stream',
        filename='webui.db',
    )
