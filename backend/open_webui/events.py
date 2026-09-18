from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from open_webui.env import VERSION
from pydantic import BaseModel, ConfigDict, Field, model_validator


log = logging.getLogger(__name__)

MAX_STRING_LENGTH = 1000


class EventDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    message: str | None = None

    @model_validator(mode='after')
    def defaults(self) -> 'EventDefinition':
        title = self.name.replace('.', ' ').replace('_', ' ').title()
        if self.description is None:
            object.__setattr__(self, 'description', f'{title}.')
        if self.message is None:
            object.__setattr__(self, 'message', title)
        return self


class EventDefinitions(BaseModel):
    model_config = ConfigDict(frozen=True)

    SYSTEM_STARTUP_STARTED: EventDefinition = EventDefinition(
        name='system.startup.started', description='Application startup began.', message='Startup started'
    )
    SYSTEM_STARTUP_COMPLETED: EventDefinition = EventDefinition(
        name='system.startup.completed', description='Application startup completed.', message='Startup completed'
    )
    SYSTEM_SHUTDOWN_STARTED: EventDefinition = EventDefinition(
        name='system.shutdown.started', description='Application shutdown began.', message='Shutdown started'
    )
    SYSTEM_SHUTDOWN_COMPLETED: EventDefinition = EventDefinition(
        name='system.shutdown.completed', description='Application shutdown completed.', message='Shutdown completed'
    )
    CONFIG_IMPORTED: EventDefinition = EventDefinition(
        name='config.imported', description='Configuration was imported.', message='Config imported'
    )
    CONFIG_UPDATED: EventDefinition = EventDefinition(
        name='config.updated', description='Configuration was updated.', message='Config updated'
    )
    CONFIG_CONNECTIONS_UPDATED: EventDefinition = EventDefinition(
        name='config.connections.updated',
        description='Connection configuration was updated.',
        message='Config Connections updated',
    )
    CONFIG_MODELS_UPDATED: EventDefinition = EventDefinition(
        name='config.models.updated', description='Model configuration was updated.', message='Config Models updated'
    )
    CONFIG_BANNERS_UPDATED: EventDefinition = EventDefinition(
        name='config.banners.updated', description='Banner configuration was updated.', message='Config Banners updated'
    )
    CONFIG_SUGGESTIONS_UPDATED: EventDefinition = EventDefinition(
        name='config.suggestions.updated',
        description='Suggestion configuration was updated.',
        message='Config Suggestions updated',
    )
    AUTH_SIGNUP: EventDefinition = EventDefinition(
        name='auth.signup', description='A user account was created through signup.', message='User signed up'
    )
    AUTH_LOGIN: EventDefinition = EventDefinition(
        name='auth.login', description='A user successfully logged in.', message='User logged in'
    )
    AUTH_LOGOUT: EventDefinition = EventDefinition(
        name='auth.logout', description='A user logged out.', message='User logged out'
    )
    AUTH_PASSWORD_CHANGED: EventDefinition = EventDefinition(
        name='auth.password_changed', description='A user password was changed.', message='Password changed'
    )
    AUTH_API_KEY_CREATED: EventDefinition = EventDefinition(
        name='auth.api_key.created', description='A user API key was created.', message='API key created'
    )
    AUTH_API_KEY_DELETED: EventDefinition = EventDefinition(
        name='auth.api_key.deleted', description='A user API key was deleted.', message='API key deleted'
    )
    AUTH_OAUTH_SESSION_DELETED: EventDefinition = EventDefinition(
        name='auth.oauth_session.deleted', description='An OAuth session was deleted.', message='OAuth session deleted'
    )
    USER_CREATED: EventDefinition = EventDefinition(
        name='user.created', description='A user account was created.', message='User created'
    )
    USER_UPDATED: EventDefinition = EventDefinition(
        name='user.updated', description='A user account was updated.', message='User updated'
    )
    USER_DELETED: EventDefinition = EventDefinition(
        name='user.deleted', description='A user account was deleted.', message='User deleted'
    )
    USER_ROLE_UPDATED: EventDefinition = EventDefinition(
        name='user.role_updated', description='A user role was updated.', message='User role updated'
    )
    USER_STATUS_UPDATED: EventDefinition = EventDefinition(
        name='user.status_updated', description='A user status was updated.', message='User status updated'
    )
    USER_SETTINGS_UPDATED: EventDefinition = EventDefinition(
        name='user.settings_updated', description='A user settings object was updated.', message='User settings updated'
    )
    USER_PROFILE_UPDATED: EventDefinition = EventDefinition(
        name='user.profile_updated', description='A user profile was updated.', message='User profile updated'
    )
    USER_PERMISSIONS_UPDATED: EventDefinition = EventDefinition(
        name='user.permissions_updated',
        description='A user permissions object was updated.',
        message='User permissions updated',
    )
    GROUP_CREATED: EventDefinition = EventDefinition(
        name='group.created', description='A group was created.', message='Group created'
    )
    GROUP_UPDATED: EventDefinition = EventDefinition(
        name='group.updated', description='A group was updated.', message='Group updated'
    )
    GROUP_DELETED: EventDefinition = EventDefinition(
        name='group.deleted', description='A group was deleted.', message='Group deleted'
    )
    GROUP_MEMBER_ADDED: EventDefinition = EventDefinition(
        name='group.member_added', description='A user was added to a group.', message='Group member added'
    )
    GROUP_MEMBER_REMOVED: EventDefinition = EventDefinition(
        name='group.member_removed', description='A user was removed from a group.', message='Group member removed'
    )
    CHAT_CREATED: EventDefinition = EventDefinition(
        name='chat.created', description='A chat was created.', message='Chat created'
    )
    CHAT_FINISHED: EventDefinition = EventDefinition(
        name='chat.finished', description='A chat response finished.', message='Chat finished'
    )
    CHAT_FAILED: EventDefinition = EventDefinition(
        name='chat.failed', description='A chat response failed.', message='Chat failed'
    )
    CHAT_IMPORTED: EventDefinition = EventDefinition(
        name='chat.imported', description='A chat was imported.', message='Chat imported'
    )
    CHAT_UPDATED: EventDefinition = EventDefinition(
        name='chat.updated', description='A chat was updated.', message='Chat updated'
    )
    CHAT_DELETED: EventDefinition = EventDefinition(
        name='chat.deleted', description='A chat was deleted.', message='Chat deleted'
    )
    CHAT_DELETED_ALL: EventDefinition = EventDefinition(
        name='chat.deleted_all', description='All chats for a scope were deleted.', message='Chat deleted all'
    )
    CHAT_COMPACTED: EventDefinition = EventDefinition(
        name='chat.compacted', description='A chat was compacted.', message='Chat compacted'
    )
    CHAT_PINNED: EventDefinition = EventDefinition(
        name='chat.pinned', description='A chat was pinned.', message='Chat pinned'
    )
    CHAT_UNPINNED: EventDefinition = EventDefinition(
        name='chat.unpinned', description='A chat was unpinned.', message='Chat unpinned'
    )
    CHAT_CLONED: EventDefinition = EventDefinition(
        name='chat.cloned', description='A chat was cloned.', message='Chat cloned'
    )
    CHAT_ARCHIVED: EventDefinition = EventDefinition(
        name='chat.archived', description='A chat was archived.', message='Chat archived'
    )
    CHAT_UNARCHIVED: EventDefinition = EventDefinition(
        name='chat.unarchived', description='A chat was unarchived.', message='Chat unarchived'
    )
    CHAT_SHARED: EventDefinition = EventDefinition(
        name='chat.shared', description='A chat was shared.', message='Chat shared'
    )
    CHAT_UNSHARED: EventDefinition = EventDefinition(
        name='chat.unshared', description='A chat was unshared.', message='Chat unshared'
    )
    CHAT_FOLDER_UPDATED: EventDefinition = EventDefinition(
        name='chat.folder_updated', description='A chat folder assignment was updated.', message='Chat folder updated'
    )
    CHAT_TAG_ADDED: EventDefinition = EventDefinition(
        name='chat.tag_added', description='A tag was added to a chat.', message='Chat tag added'
    )
    CHAT_TAG_REMOVED: EventDefinition = EventDefinition(
        name='chat.tag_removed', description='A tag was removed from a chat.', message='Chat tag removed'
    )
    MESSAGE_CREATED: EventDefinition = EventDefinition(
        name='message.created', description='A message was created.', message='Message created'
    )
    MESSAGE_UPDATED: EventDefinition = EventDefinition(
        name='message.updated', description='A message was updated.', message='Message updated'
    )
    MESSAGE_DELETED: EventDefinition = EventDefinition(
        name='message.deleted', description='A message was deleted.', message='Message deleted'
    )
    MESSAGE_EVENT_RECEIVED: EventDefinition = EventDefinition(
        name='message.event_received',
        description='A message-level event was received.',
        message='Message event received',
    )
    FILE_UPLOADED: EventDefinition = EventDefinition(
        name='file.uploaded', description='A file was uploaded.', message='File uploaded'
    )
    FILE_CONTENT_UPDATED: EventDefinition = EventDefinition(
        name='file.content_updated', description='File content was updated.', message='File content updated'
    )
    FILE_RENAMED: EventDefinition = EventDefinition(
        name='file.renamed', description='A file was renamed.', message='File renamed'
    )
    FILE_DELETED: EventDefinition = EventDefinition(
        name='file.deleted', description='A file was deleted.', message='File deleted'
    )
    FILE_DELETED_ALL: EventDefinition = EventDefinition(
        name='file.deleted_all', description='All files for a scope were deleted.', message='File deleted all'
    )
    FOLDER_CREATED: EventDefinition = EventDefinition(
        name='folder.created', description='A folder was created.', message='Folder created'
    )
    FOLDER_UPDATED: EventDefinition = EventDefinition(
        name='folder.updated', description='A folder was updated.', message='Folder updated'
    )
    FOLDER_PARENT_UPDATED: EventDefinition = EventDefinition(
        name='folder.parent_updated', description='A folder parent was updated.', message='Folder parent updated'
    )
    FOLDER_ACCESS_UPDATED: EventDefinition = EventDefinition(
        name='folder.access_updated', description='Folder access was updated.', message='Folder access updated'
    )
    FOLDER_DELETED: EventDefinition = EventDefinition(
        name='folder.deleted', description='A folder was deleted.', message='Folder deleted'
    )
    MODEL_CREATED: EventDefinition = EventDefinition(
        name='model.created', description='A model was created.', message='Model created'
    )
    MODEL_IMPORTED: EventDefinition = EventDefinition(
        name='model.imported', description='A model was imported.', message='Model imported'
    )
    MODEL_SYNCED: EventDefinition = EventDefinition(
        name='model.synced', description='A model was synced.', message='Model synced'
    )
    MODEL_UPDATED: EventDefinition = EventDefinition(
        name='model.updated', description='A model was updated.', message='Model updated'
    )
    MODEL_DELETED: EventDefinition = EventDefinition(
        name='model.deleted', description='A model was deleted.', message='Model deleted'
    )
    MODEL_ENABLED: EventDefinition = EventDefinition(
        name='model.enabled', description='A model was enabled.', message='Model enabled'
    )
    MODEL_DISABLED: EventDefinition = EventDefinition(
        name='model.disabled', description='A model was disabled.', message='Model disabled'
    )
    MODEL_ACCESS_UPDATED: EventDefinition = EventDefinition(
        name='model.access_updated', description='Model access was updated.', message='Model access updated'
    )
    MODEL_PROVIDER_CONFIG_UPDATED: EventDefinition = EventDefinition(
        name='model.provider_config.updated',
        description='Model provider configuration was updated.',
        message='Model Provider Config updated',
    )
    MODEL_PROVIDER_REQUEST_FAILED: EventDefinition = EventDefinition(
        name='model.provider_request.failed',
        description='A model provider request failed.',
        message='Model provider request failed',
    )
    MODEL_PROVIDER_MODEL_CREATED: EventDefinition = EventDefinition(
        name='model.provider_model.created',
        description='A provider model was created.',
        message='Provider model created',
    )
    MODEL_PROVIDER_MODEL_DELETED: EventDefinition = EventDefinition(
        name='model.provider_model.deleted',
        description='A provider model was deleted.',
        message='Provider model deleted',
    )
    PROMPT_CREATED: EventDefinition = EventDefinition(
        name='prompt.created', description='A prompt was created.', message='Prompt created'
    )
    PROMPT_UPDATED: EventDefinition = EventDefinition(
        name='prompt.updated', description='A prompt was updated.', message='Prompt updated'
    )
    PROMPT_DELETED: EventDefinition = EventDefinition(
        name='prompt.deleted', description='A prompt was deleted.', message='Prompt deleted'
    )
    PROMPT_ENABLED: EventDefinition = EventDefinition(
        name='prompt.enabled', description='A prompt was enabled.', message='Prompt enabled'
    )
    PROMPT_DISABLED: EventDefinition = EventDefinition(
        name='prompt.disabled', description='A prompt was disabled.', message='Prompt disabled'
    )
    PROMPT_VERSION_UPDATED: EventDefinition = EventDefinition(
        name='prompt.version_updated', description='A prompt version was updated.', message='Prompt version updated'
    )
    PROMPT_ACCESS_UPDATED: EventDefinition = EventDefinition(
        name='prompt.access_updated', description='Prompt access was updated.', message='Prompt access updated'
    )
    IMAGE_GENERATED: EventDefinition = EventDefinition(
        name='image.generated', description='An image was generated.', message='Image generated'
    )
    IMAGE_EDITED: EventDefinition = EventDefinition(
        name='image.edited', description='An image was edited.', message='Image edited'
    )


EVENTS = EventDefinitions()
EVENT_DEFINITIONS = tuple(getattr(EVENTS, field_name) for field_name in EventDefinitions.model_fields)
EVENT_DEFINITIONS_BY_NAME = {definition.name: definition for definition in EVENT_DEFINITIONS}
EVENT_CATALOG = tuple(definition.name for definition in EVENT_DEFINITIONS)
EVENT_CATALOG_SET = set(EVENT_CATALOG)


def get_event_catalog() -> list[dict[str, str]]:
    return [
        {
            'event': definition.name,
            'description': definition.description,
            'message': definition.message,
        }
        for definition in EVENT_DEFINITIONS
    ]


SENSITIVE_KEYS = {
    'password',
    'hashed_password',
    'token',
    'access_token',
    'refresh_token',
    'id_token',
    'api_key',
    'secret',
    'key',
    'authorization',
    'cookie',
    'webhook_token',
}

SAFE_ACTOR_FIELDS = ('id', 'name', 'email', 'role', 'created_at', 'updated_at')


class Event(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(alias='schema')
    id: str
    event: str
    resource: str
    operation: str
    created_at: int
    instance_id: str | None
    version: str
    source: str
    actor: dict[str, Any] | None = None
    subject: dict[str, Any] | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None

    def model_dump(self, *args, **kwargs) -> dict[str, Any]:
        kwargs.setdefault('by_alias', True)
        return super().model_dump(*args, **kwargs)


def _sensitive(key: Any) -> bool:
    normalized = str(key).lower().replace('-', '_')
    return (
        normalized in SENSITIVE_KEYS
        or normalized.endswith('_token')
        or normalized.endswith('_secret')
        or normalized.endswith('_api_key')
        or normalized.endswith('_key')
    )


def _sanitize(value: Any) -> Any:
    if hasattr(value, 'model_dump'):
        value = value.model_dump()

    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items() if not _sensitive(key)}

    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item) for item in value]

    if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        return f'{value[:MAX_STRING_LENGTH]}...'

    return value


def _actor(actor: Any | None) -> dict[str, Any] | None:
    actor = _sanitize(actor)
    if not actor:
        return None

    get = actor.get if isinstance(actor, dict) else lambda key: getattr(actor, key, None)
    data = {field: get(field) for field in SAFE_ACTOR_FIELDS if get(field) is not None}
    if not data:
        return None

    data['type'] = get('type') or 'user'
    return data


def event_name(event: EventDefinition | str) -> str:
    name = event.name if isinstance(event, EventDefinition) else str(event)
    if name not in EVENT_CATALOG_SET:
        raise ValueError(f'Unknown event: {name}')
    return name


def build_event(
    request_or_app: Any,
    event: EventDefinition | str,
    *,
    actor: Any | None = None,
    subject_id: Any | None = None,
    subject_type: str | None = None,
    source: str = 'api',
    data: dict | None = None,
    message: str | None = None,
) -> Event:
    event_name_value = event_name(event)
    app = getattr(request_or_app, 'app', request_or_app)
    parts = event_name_value.split('.')
    resource = '.'.join(parts[:-1])
    instance_id = getattr(getattr(app, 'state', None), 'instance_id', None)
    subject = (
        {'type': subject_type or resource, 'id': subject_id}
        if subject_id is not None or subject_type is not None
        else None
    )

    return Event(
        schema=VERSION,
        id=str(uuid.uuid4()),
        event=event_name_value,
        resource=resource,
        operation=parts[-1],
        created_at=int(time.time()),
        instance_id=instance_id,
        version=VERSION,
        source=source,
        actor=_actor(actor),
        subject=_sanitize(subject) if subject else None,
        data=_sanitize(data or {}),
        message=message,
    )


class SocketSessionEventSink:
    async def handle_event(self, app: Any, event: Event, request: Any | None = None) -> None:
        if event.event not in {EVENTS.USER_DELETED.name, EVENTS.USER_ROLE_UPDATED.name}:
            return

        subject = event.subject or {}
        if subject.get('type') != 'user' or not subject.get('id'):
            return

        from open_webui.socket.main import disconnect_user_sessions

        await disconnect_user_sessions(str(subject['id']))


EVENT_SINKS = [SocketSessionEventSink()]


async def publish_event(
    request_or_app: Any,
    event: EventDefinition | str,
    *,
    actor: Any | None = None,
    subject_id: Any | None = None,
    subject_type: str | None = None,
    source: str = 'api',
    data: dict | None = None,
    message: str | None = None,
) -> None:
    app = getattr(request_or_app, 'app', request_or_app)
    request = request_or_app if hasattr(request_or_app, 'app') else None
    event_payload = build_event(
        request_or_app,
        event,
        actor=actor,
        subject_id=subject_id,
        subject_type=subject_type,
        source=source,
        data=data,
        message=message,
    )

    for sink in EVENT_SINKS:
        try:
            await sink.handle_event(app, event_payload, request=request)
        except Exception:
            log.exception('Event sink failed for %s', event_payload.event)


async def publish_model_provider_request_failed(
    request_or_app: Any,
    *,
    actor: Any | None,
    provider: str,
    base_url: str,
    status: int,
    requested_model: str | None = None,
    api_key: str | None = None,
    upstream_error: Any = None,
) -> None:
    error = upstream_error.get('error') if isinstance(upstream_error, dict) else upstream_error
    error_code = None
    if isinstance(error, dict):
        error_code = error.get('code') or error.get('type') or error.get('error_code')
        error = error.get('message') or error.get('detail') or error

    error_text = str(error or '')
    marker = f'{error_code or ""} {error_text}'.lower()
    error_type = (
        'model_not_found'
        if status == 404
        and any(value in marker for value in ('model_not_found', 'model not found', 'does not exist', 'no such model'))
        else 'authentication_failed'
        if status in (401, 403)
        else 'rate_limited'
        if status == 429
        else 'server_failed'
        if status >= 500
        else 'upstream_error'
    )

    # Server-log only; the upstream error body is otherwise invisible to admins
    # (event sinks require an event function or webhook to be configured).
    log.log(
        logging.ERROR if status >= 500 else logging.WARNING,
        'Upstream %s request failed: HTTP %d (%s) url=%s model=%s code=%s message=%s',
        provider,
        status,
        error_type,
        base_url,
        requested_model or '-',
        error_code or '-',
        error_text[:MAX_STRING_LENGTH] or '-',
    )

    data = {
        'error_type': error_type,
        'status': status,
        'provider': provider,
        'base_url': base_url,
    }
    if requested_model:
        data['requested_model'] = requested_model
    if api_key:
        data['api_key_suffix'] = f'...{api_key[-4:]}'
    if error_code:
        data['upstream_error_code'] = error_code
    if error:
        data['upstream_message'] = error

    await publish_event(
        request_or_app,
        EVENTS.MODEL_PROVIDER_REQUEST_FAILED,
        actor=actor,
        subject_id=requested_model,
        subject_type='model',
        data=data,
    )
