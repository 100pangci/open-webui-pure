import asyncio
import copy
import logging

from fastapi import Request
from open_webui.config import BYPASS_ADMIN_ACCESS_CONTROL
from open_webui.env import BYPASS_MODEL_ACCESS_CONTROL, REDIS_KEY_PREFIX
from open_webui.models.access_grants import AccessGrants
from open_webui.models.config import Config
from open_webui.models.groups import Groups
from open_webui.models.models import Models
from open_webui.utils.chat_variables import get_chat_variables_schema
from open_webui.models.users import UserModel
from open_webui.routers import openai
from open_webui.socket.utils import RedisDict
from open_webui.utils.access_control import has_base_model_access
from open_webui.utils.json_codec import JSONCodec

log = logging.getLogger(__name__)

BASE_MODELS_CACHE_KEY = f'{REDIS_KEY_PREFIX}:models:base'


async def fetch_openai_models(request: Request, user: UserModel = None):
    openai_response = await openai.get_all_models(request, user=user)
    return openai_response['data']


async def get_all_base_models(request: Request, user: UserModel = None):
    config = await Config.get_many('openai.enable')
    openai_task = fetch_openai_models(request, user) if config.get('openai.enable') else asyncio.sleep(0, result=[])

    return await openai_task


async def get_all_models(request, refresh: bool = False, user: UserModel = None):
    config = await Config.get_many(
        'models.base_models_cache',
        'models.default_metadata',
    )
    if refresh:
        await openai.get_all_models.cache.clear()
        redis = getattr(request.app.state, 'redis', None)
        if redis is not None:
            await redis.delete(BASE_MODELS_CACHE_KEY)
        request.app.state.BASE_MODELS = []

    redis = getattr(request.app.state, 'redis', None)
    use_cache = config.get('models.base_models_cache') and not refresh
    base_models = None

    if use_cache and redis is not None:
        cached_base_models = await redis.get(BASE_MODELS_CACHE_KEY)
        if cached_base_models:
            base_models = JSONCodec.loads(cached_base_models)
            request.app.state.BASE_MODELS = base_models
        else:
            await openai.get_all_models.cache.clear()
    elif use_cache and request.app.state.MODELS and request.app.state.BASE_MODELS:
        base_models = request.app.state.BASE_MODELS

    if base_models is None:
        base_models = await get_all_base_models(request, user=user)
        if base_models:
            request.app.state.BASE_MODELS = base_models
            if config.get('models.base_models_cache') and redis is not None:
                await redis.set(BASE_MODELS_CACHE_KEY, JSONCodec.dumps(base_models))
        else:
            base_models = request.app.state.BASE_MODELS

    # deep copy the base models to avoid modifying the original list
    models = [model.copy() for model in base_models]

    # If there are no models, return an empty list
    if len(models) == 0:
        return []

    custom_models = await Models.get_all_models()

    # Single O(1) lookup: exact IDs, with base names as a fallback for
    # chained presets whose ``base_model_id`` names a base model.
    base_model_lookup = {}
    for model in models:
        base_model_lookup[model['id']] = model

    existing_ids = {m['id'] for m in models}

    for custom_model in custom_models:
        if custom_model.base_model_id is None:
            # Override applied directly to a base model (shares the same ID)
            model = base_model_lookup.get(custom_model.id)

            if model:
                if custom_model.is_active:
                    model['name'] = custom_model.name
                    model['info'] = custom_model.model_dump()
                    schema = get_chat_variables_schema(custom_model.params.model_dump().get('system'))
                    if schema:
                        model['info'].setdefault('meta', {})['chat_variables_schema'] = schema

                    if 'info' in model:
                        if 'params' in model['info']:
                            del model['info']['params']
                else:
                    models = [m for m in models if m is not model]

        elif custom_model.is_active:
            if custom_model.id in existing_ids:
                continue

            owned_by = 'openai'
            connection_type = None

            base_model = base_model_lookup.get(custom_model.base_model_id)
            if base_model:
                owned_by = base_model.get('owned_by', 'unknown')
                connection_type = base_model.get('connection_type', None)

            model = {
                'id': f'{custom_model.id}',
                'name': custom_model.name,
                'object': 'model',
                'created': custom_model.created_at,
                'owned_by': owned_by,
                'connection_type': connection_type,
                'preset': True,
                **({'provider': base_model.get('provider')} if base_model and base_model.get('provider') else {}),
                **({'loaded': base_model.get('loaded')} if base_model and base_model.get('loaded') is not None else {}),
            }

            info = custom_model.model_dump()
            schema = get_chat_variables_schema(custom_model.params.model_dump().get('system'))
            if schema:
                info.setdefault('meta', {})['chat_variables_schema'] = schema
            if 'params' in info:
                # Remove params to avoid exposing sensitive info
                del info['params']

            model['info'] = info

            models.append(model)

    # Apply global model defaults to all models
    # Per-model overrides take precedence over global defaults
    default_metadata = config.get('models.default_metadata') or {}

    if default_metadata:
        for model in models:
            info = model.get('info')

            if info is None:
                model['info'] = {'meta': copy.deepcopy(default_metadata)}
                continue

            meta = info.setdefault('meta', {})
            for key, value in default_metadata.items():
                if key == 'capabilities':
                    # Merge capabilities: defaults as base, per-model overrides win
                    existing = meta.get('capabilities') or {}
                    meta['capabilities'] = {**value, **existing}
                elif meta.get(key) is None:
                    meta[key] = copy.deepcopy(value)

    log.debug('get_all_models() returned %s models', len(models))

    models_dict = {model['id']: model for model in models}
    if isinstance(request.app.state.MODELS, RedisDict):
        try:
            request.app.state.MODELS.set(models_dict)
        except Exception as e:
            log.warning(f'Failed to update Redis model cache, using in-process cache: {e}')
            request.app.state.MODELS = models_dict
    else:
        request.app.state.MODELS = models_dict

    return models


async def check_model_access(user, model, model_info=None, db=None):
    # Callers that already fetched the row (chat completion entry) pass it in
    if model_info is None or model_info.id != model.get('id'):
        model_info = await Models.get_model_by_id(model.get('id'), db=db)
    if not model_info:
        raise Exception('Model not found')

    # One group-membership fetch shared by the direct check and every
    # base-model hop; skipped when no check below needs it.
    user_group_ids = None
    if user.id != model_info.user_id or model_info.base_model_id:
        user_group_ids = {group.id for group in await Groups.get_groups_by_member_id(user.id, db=db)}

    if not (
        user.id == model_info.user_id
        or await AccessGrants.has_access(
            user_id=user.id,
            resource_type='model',
            resource_id=model_info.id,
            permission='read',
            user_group_ids=user_group_ids,
            db=db,
        )
    ):
        raise Exception('Model not found')

    # Enforce access on chained base models
    if not await has_base_model_access(user.id, model_info, user_role=user.role, user_group_ids=user_group_ids, db=db):
        raise Exception('Model not found')


async def get_filtered_models(models, user, db=None):
    # Filter out models that the user does not have access to
    if (
        user.role == 'user' or (user.role == 'admin' and not BYPASS_ADMIN_ACCESS_CONTROL)
    ) and not BYPASS_MODEL_ACCESS_CONTROL:
        model_infos = {}
        for model in models:
            info = model.get('info')
            if info:
                model_infos[model['id']] = info

        user_group_ids = {group.id for group in await Groups.get_groups_by_member_id(user.id, db=db)}

        # Batch-fetch accessible resource IDs in a single query instead of N has_access calls
        accessible_model_ids = await AccessGrants.get_accessible_resource_ids(
            user_id=user.id,
            resource_type='model',
            resource_ids=list(model_infos.keys()),
            permission='read',
            user_group_ids=user_group_ids,
            db=db,
        )

        filtered_models = []
        for model in models:
            model_info = model_infos.get(model['id'])
            if model_info:
                if (
                    (user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL)
                    or user.id == model_info.get('user_id')
                    or model['id'] in accessible_model_ids
                ):
                    filtered_models.append(model)
            elif user.role == 'admin':
                # No DB entry means no access control configured yet;
                # only admins can see unconfigured models.
                filtered_models.append(model)

        return filtered_models
    else:
        return models
