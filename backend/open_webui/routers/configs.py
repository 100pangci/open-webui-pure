from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from open_webui.config import BannerModel
from open_webui.events import EVENTS, publish_event
from open_webui.models.config import Config
from open_webui.utils.auth import get_admin_user, get_verified_user
from pydantic import BaseModel

router = APIRouter()

CONNECTIONS_CONFIG_KEYS = {
    'ENABLE_DIRECT_CONNECTIONS': 'direct.enable',
    'ENABLE_BASE_MODELS_CACHE': 'models.base_models_cache',
}
MODELS_CONFIG_KEYS = {
    'DEFAULT_MODELS': 'ui.default_models',
    'DEFAULT_PINNED_MODELS': 'ui.default_pinned_models',
    'MODEL_ORDER_LIST': 'ui.model_order_list',
    'DEFAULT_MODEL_METADATA': 'models.default_metadata',
    'DEFAULT_MODEL_PARAMS': 'models.default_params',
}


async def get_config_values(key_map: dict[str, str]) -> dict:
    values = await Config.get_many(*key_map.values())
    return {field: values[storage_key] for field, storage_key in key_map.items() if storage_key in values}


def config_updates(data: dict, key_map: dict[str, str]) -> dict:
    return {key_map[field]: value for field, value in data.items() if field in key_map}


############################
# ImportConfig
# Thy configuration come, thy settings be done,
# in production as it is in development.
############################


class ImportConfigForm(BaseModel):
    config: dict


@router.post('/import', response_model=dict)
async def import_config(request: Request, form_data: ImportConfigForm, user=Depends(get_admin_user)):
    await Config.upsert(form_data.config)
    await publish_event(
        request,
        EVENTS.CONFIG_IMPORTED,
        actor=user,
        subject_id='import',
        data={'keys': list(form_data.config.keys())},
    )
    return await Config.get_all()


############################
# ExportConfig
############################


@router.get('/export', response_model=dict)
async def export_config(user=Depends(get_admin_user)):
    return await Config.get_all()


@router.get('/namespace/{namespace}', response_model=dict)
async def get_config_namespace(namespace: str, user=Depends(get_admin_user)):
    return await Config.get_namespace(namespace)


############################
# Connections Config
############################


class ConnectionsConfigForm(BaseModel):
    ENABLE_DIRECT_CONNECTIONS: bool
    ENABLE_BASE_MODELS_CACHE: bool


@router.get('/connections', response_model=ConnectionsConfigForm)
async def get_connections_config(request: Request, user=Depends(get_admin_user)):
    return await get_config_values(CONNECTIONS_CONFIG_KEYS)


@router.post('/connections', response_model=ConnectionsConfigForm)
async def set_connections_config(
    request: Request,
    form_data: ConnectionsConfigForm,
    user=Depends(get_admin_user),
):
    await Config.upsert(config_updates(form_data.model_dump(), CONNECTIONS_CONFIG_KEYS))
    values = await get_config_values(CONNECTIONS_CONFIG_KEYS)
    await publish_event(
        request,
        EVENTS.CONFIG_UPDATED,
        actor=user,
        subject_id='connections',
        subject_type='config',
        data=values,
    )
    return values


############################
# SetDefaultModels
############################
class ModelsConfigForm(BaseModel):
    DEFAULT_MODELS: str | None
    DEFAULT_PINNED_MODELS: str | None
    MODEL_ORDER_LIST: list[str] | None
    DEFAULT_MODEL_METADATA: dict | None = None
    DEFAULT_MODEL_PARAMS: dict | None = None


@router.get('/models/defaults')
async def get_models_defaults(request: Request, user=Depends(get_verified_user)):
    return {
        'DEFAULT_MODEL_METADATA': await Config.get('models.default_metadata'),
    }


@router.get('/models', response_model=ModelsConfigForm)
async def get_models_config(request: Request, user=Depends(get_admin_user)):
    return await get_config_values(MODELS_CONFIG_KEYS)


@router.post('/models', response_model=ModelsConfigForm)
async def set_models_config(request: Request, form_data: ModelsConfigForm, user=Depends(get_admin_user)):
    await Config.upsert(config_updates(form_data.model_dump(), MODELS_CONFIG_KEYS))
    values = await get_config_values(MODELS_CONFIG_KEYS)
    await publish_event(
        request,
        EVENTS.CONFIG_UPDATED,
        actor=user,
        subject_id='models',
        subject_type='config',
        data={
            'default_models': values.get('DEFAULT_MODELS'),
            'default_pinned_models': values.get('DEFAULT_PINNED_MODELS'),
            'model_order_count': len(values.get('MODEL_ORDER_LIST') or []),
        },
    )
    return values


class PromptSuggestion(BaseModel):
    title: list[str]
    content: str


class SetDefaultSuggestionsForm(BaseModel):
    suggestions: list[PromptSuggestion]


@router.post('/suggestions', response_model=list[PromptSuggestion])
async def set_default_suggestions(
    request: Request,
    form_data: SetDefaultSuggestionsForm,
    user=Depends(get_admin_user),
):
    data = form_data.model_dump()
    await Config.upsert({'ui.prompt_suggestions': data['suggestions']})
    suggestions = await Config.get('ui.prompt_suggestions')
    await publish_event(
        request,
        EVENTS.CONFIG_UPDATED,
        actor=user,
        subject_id='ui.prompt_suggestions',
        subject_type='config',
        data={'count': len(suggestions or [])},
    )
    return suggestions


############################
# SetBanners
############################


class SetBannersForm(BaseModel):
    banners: list[BannerModel]


@router.post('/banners', response_model=list[BannerModel])
async def set_banners(
    request: Request,
    form_data: SetBannersForm,
    user=Depends(get_admin_user),
):
    data = form_data.model_dump()
    await Config.upsert({'ui.banners': data['banners']})
    banners = await Config.get('ui.banners')
    await publish_event(
        request,
        EVENTS.CONFIG_UPDATED,
        actor=user,
        subject_id='ui.banners',
        subject_type='config',
        data={'count': len(banners or [])},
    )
    return banners


@router.get('/banners', response_model=list[BannerModel])
async def get_banners(
    request: Request,
    user=Depends(get_verified_user),
):
    return await Config.get('ui.banners')
