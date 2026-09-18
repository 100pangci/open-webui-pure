import asyncio
import logging
import sys
import uuid
from typing import Any

from fastapi import Request
from open_webui.env import BYPASS_MODEL_ACCESS_CONTROL, GLOBAL_LOG_LEVEL
from open_webui.models.users import UserModel
from open_webui.routers.openai import (
    generate_chat_completion as generate_openai_chat_completion,
)
from open_webui.socket.main import (
    get_event_call,
    get_event_emitter,
    sio,
)
from open_webui.utils.json_codec import JSONCodec
from open_webui.utils.models import check_model_access, get_all_models
from starlette.responses import StreamingResponse

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)


# When the question has been asked, let silence not be the
# answer. But if the answer must wait, let it come honest.
async def generate_direct_chat_completion(
    request: Request,
    form_data: dict,
    user: Any,
    models: dict,
):
    log.info('generate_direct_chat_completion')

    metadata = form_data.pop('metadata', {})

    user_id = metadata.get('user_id')
    session_id = metadata.get('session_id')
    request_id = str(uuid.uuid4())  # Generate a unique request ID

    event_caller = await get_event_call(metadata)
    if event_caller is None:
        raise Exception(
            'Direct connection requires an active WebSocket session; '
            'cannot generate completion in this context (e.g. background task).'
        )

    channel = f'{user_id}:{session_id}:{request_id}'
    logging.info('WebSocket channel: %s', channel)

    if form_data.get('stream'):
        q = asyncio.Queue()

        async def message_listener(sid, data):
            """
            Handle received socket messages and push them into the queue.
            """
            await q.put(data)

        # Register the listener
        sio.on(channel, message_listener)

        # Start processing chat completion in background
        res = await event_caller(
            {
                'type': 'request:chat:completion',
                'data': {
                    'form_data': form_data,
                    'model': models[form_data['model']],
                    'channel': channel,
                    'session_id': session_id,
                },
            }
        )

        log.info('res: %s', res)

        if res.get('status', False):
            # Define a generator to stream responses
            async def event_generator():
                nonlocal q
                try:
                    while True:
                        data = await q.get()  # Wait for new messages
                        if isinstance(data, dict):
                            if 'done' in data and data['done']:
                                break  # Stop streaming when 'done' is received

                            yield f'data: {JSONCodec.dumps(data)}\n\n'
                        elif isinstance(data, str):
                            if 'data:' in data:
                                yield f'{data}\n\n'
                            else:
                                yield f'data: {data}\n\n'
                except Exception as e:
                    log.debug('Error in event generator: %s', e)
                    pass

            # Define a background task to run the event generator
            async def background():
                try:
                    del sio.handlers['/'][channel]
                except Exception as e:
                    pass

            # Return the streaming response
            return StreamingResponse(event_generator(), media_type='text/event-stream', background=background)
        else:
            raise Exception(str(res))
    else:
        res = await event_caller(
            {
                'type': 'request:chat:completion',
                'data': {
                    'form_data': form_data,
                    'model': models[form_data['model']],
                    'channel': channel,
                    'session_id': session_id,
                },
            }
        )

        if 'error' in res and res['error']:
            raise Exception(res['error'])

        return res


async def generate_chat_completion(
    request: Request,
    form_data: dict,
    user: Any,
    bypass_filter: bool = False,
    bypass_system_prompt: bool = False,
):
    log.debug('generate_chat_completion: %s', form_data)
    if BYPASS_MODEL_ACCESS_CONTROL:
        bypass_filter = True

    # Propagate bypass_filter and bypass_system_prompt via request.state so that
    # downstream route handlers (openai/ollama) can read them without exposing
    # them as query parameters.
    request.state.bypass_filter = bypass_filter
    request.state.bypass_system_prompt = bypass_system_prompt

    if hasattr(request.state, 'metadata'):
        if 'metadata' not in form_data:
            form_data['metadata'] = request.state.metadata
        else:
            form_data['metadata'] = {
                **form_data['metadata'],
                **request.state.metadata,
            }

    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        # Merge the direct connection model into server models so that
        # task functions (title, tags, etc.) can resolve a server-side
        # task model while still having the direct model available.
        # dict(...items()) is one HGETALL on a Redis-backed pool; ``{**pool}``
        # would issue HKEYS plus one HGET per model.
        models = {
            **dict(request.app.state.MODELS.items()),
            request.state.model['id']: request.state.model,
        }
        log.debug('direct connection to model: %s', request.state.model['id'])
    else:
        models = request.app.state.MODELS

    model_id = form_data['model']
    # Single lookup — membership check plus getitem would be two Redis
    # round trips on a Redis-backed model pool.
    model = models.get(model_id)
    if model is None:
        raise Exception('Model not found')

    if getattr(request.state, 'direct', False) and model_id == getattr(request.state, 'model', {}).get('id'):
        return await generate_direct_chat_completion(request, form_data, user=user, models=models)
    else:
        # Check if user has access to the model
        if not bypass_filter and user.role == 'user':
            try:
                await check_model_access(user, model)
            except Exception as e:
                raise e

        return await generate_openai_chat_completion(
            request=request,
            form_data=form_data,
            user=user,
        )


chat_completion = generate_chat_completion


async def chat_completed(request: Request, form_data: dict, user: Any):
    if not request.app.state.MODELS:
        await get_all_models(request, user=user)

    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            **dict(request.app.state.MODELS.items()),
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    data = form_data

    if not data.get('id'):
        raise Exception('Missing message id')

    model_id = data['model']
    if model_id not in models:
        raise Exception('Model not found')

    model = models[model_id]

    if not data.get('id'):
        raise Exception('Missing message id')

    metadata = {
        'chat_id': data['chat_id'],
        'message_id': data['id'],
        'filter_ids': data.get('filter_ids', []),
        'session_id': data['session_id'],
        'user_id': user.id,
    }

    extra_params = {
        '__event_emitter__': await get_event_emitter(metadata),
        '__event_call__': await get_event_call(metadata),
        '__user__': user.model_dump() if isinstance(user, UserModel) else {},
        '__metadata__': metadata,
        '__request__': request,
        '__model__': model,
    }

    return data
