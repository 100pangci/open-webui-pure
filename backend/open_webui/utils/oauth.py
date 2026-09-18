from __future__ import annotations

import asyncio
import base64
import fnmatch
import logging
import re
import sys
import urllib.parse
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlparse

import aiohttp
import jwt
from authlib.integrations.starlette_client import OAuth
from authlib.oauth2.rfc6749.errors import OAuth2Error
from authlib.oidc.core import UserInfo
from fastapi import HTTPException, status
from joserfc.errors import BadSignatureError
from open_webui.config import (
    DEFAULT_USER_ROLE,
    ENABLE_OAUTH,
    ENABLE_OAUTH_GROUP_CREATION,
    ENABLE_OAUTH_GROUP_MANAGEMENT,
    ENABLE_OAUTH_ROLE_MANAGEMENT,
    ENABLE_OAUTH_SIGNUP,
    JWT_EXPIRES_IN,
    OAUTH_ACCESS_TOKEN_REQUEST_INCLUDE_CLIENT_ID,
    OAUTH_ADMIN_ROLES,
    OAUTH_ALLOWED_DOMAINS,
    OAUTH_ALLOWED_ROLES,
    OAUTH_AUDIENCE,
    OAUTH_AUTHORIZE_PARAMS,
    OAUTH_BLOCKED_GROUPS,
    OAUTH_EMAIL_CLAIM,
    OAUTH_GROUP_DEFAULT_SHARE,
    OAUTH_GROUPS_CLAIM,
    OAUTH_GROUPS_SEPARATOR,
    OAUTH_MERGE_ACCOUNTS_BY_EMAIL,
    OAUTH_PICTURE_CLAIM,
    OAUTH_PROVIDERS,
    OAUTH_REFRESH_TOKEN_INCLUDE_SCOPE,
    OAUTH_ROLES_CLAIM,
    OAUTH_ROLES_SEPARATOR,
    OAUTH_SUB_CLAIM,
    OAUTH_UPDATE_EMAIL_ON_LOGIN,
    OAUTH_UPDATE_NAME_ON_LOGIN,
    OAUTH_UPDATE_PICTURE_ON_LOGIN,
    OAUTH_USERNAME_CLAIM,
)
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import (
    AIOHTTP_CLIENT_ALLOW_REDIRECTS,
    AIOHTTP_CLIENT_SESSION_SSL,
    ENABLE_OAUTH_EMAIL_FALLBACK,
    ENABLE_OAUTH_ID_TOKEN_COOKIE,
    GLOBAL_LOG_LEVEL,
    OAUTH_MAX_SESSIONS_PER_USER,
    WEBUI_AUTH_COOKIE_SAME_SITE,
    WEBUI_AUTH_COOKIE_SECURE,
)
from open_webui.events import EVENTS, publish_event
from open_webui.models.auths import Auths
from open_webui.models.config import Config
from open_webui.models.groups import GroupForm, GroupModel, Groups, GroupUpdateForm
from open_webui.models.oauth_sessions import OAuthSessions
from open_webui.models.users import Users
from open_webui.utils.auth import (
    create_token,
    get_password_hash,
    revoke_user_tokens,
)
from open_webui.utils.groups import apply_default_group_assignment
from open_webui.utils.json_codec import JSONCodec
from open_webui.utils.misc import parse_duration
from open_webui.utils.validate import validate_profile_image_url
from starlette.responses import RedirectResponse

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('Only absolute HTTP(S) URLs are allowed')


def get_ssrf_safe_session():
    return aiohttp.ClientSession()


OAUTH_RUNTIME_CONFIG = {
    'DEFAULT_USER_ROLE': ('ui.default_user_role', DEFAULT_USER_ROLE),
    'ENABLE_OAUTH': ('oauth.enable', ENABLE_OAUTH),
    'ENABLE_OAUTH_SIGNUP': ('oauth.enable_signup', ENABLE_OAUTH_SIGNUP),
    'OAUTH_REFRESH_TOKEN_INCLUDE_SCOPE': (
        'oauth.refresh_token.include_scope',
        OAUTH_REFRESH_TOKEN_INCLUDE_SCOPE,
    ),
    'OAUTH_MERGE_ACCOUNTS_BY_EMAIL': (
        'oauth.merge_accounts_by_email',
        OAUTH_MERGE_ACCOUNTS_BY_EMAIL,
    ),
    'ENABLE_OAUTH_ROLE_MANAGEMENT': (
        'oauth.enable_role_mapping',
        ENABLE_OAUTH_ROLE_MANAGEMENT,
    ),
    'ENABLE_OAUTH_GROUP_MANAGEMENT': (
        'oauth.enable_group_mapping',
        ENABLE_OAUTH_GROUP_MANAGEMENT,
    ),
    'ENABLE_OAUTH_GROUP_CREATION': (
        'oauth.enable_group_creation',
        ENABLE_OAUTH_GROUP_CREATION,
    ),
    'OAUTH_GROUP_DEFAULT_SHARE': (
        'oauth.group_default_share',
        OAUTH_GROUP_DEFAULT_SHARE,
    ),
    'OAUTH_BLOCKED_GROUPS': ('oauth.blocked_groups', OAUTH_BLOCKED_GROUPS),
    'OAUTH_ROLES_CLAIM': ('oauth.roles_claim', OAUTH_ROLES_CLAIM),
    'OAUTH_SUB_CLAIM': ('oauth.sub_claim', OAUTH_SUB_CLAIM),
    'OAUTH_GROUPS_CLAIM': ('oauth.group_claim', OAUTH_GROUPS_CLAIM),
    'OAUTH_EMAIL_CLAIM': ('oauth.email_claim', OAUTH_EMAIL_CLAIM),
    'OAUTH_PICTURE_CLAIM': ('oauth.picture_claim', OAUTH_PICTURE_CLAIM),
    'OAUTH_USERNAME_CLAIM': ('oauth.username_claim', OAUTH_USERNAME_CLAIM),
    'OAUTH_ALLOWED_ROLES': ('oauth.allowed_roles', OAUTH_ALLOWED_ROLES),
    'OAUTH_ADMIN_ROLES': ('oauth.admin_roles', OAUTH_ADMIN_ROLES),
    'OAUTH_ALLOWED_DOMAINS': ('oauth.allowed_domains', OAUTH_ALLOWED_DOMAINS),
    'JWT_EXPIRES_IN': ('auth.jwt_expiry', JWT_EXPIRES_IN),
    'OAUTH_UPDATE_PICTURE_ON_LOGIN': (
        'oauth.update_picture_on_login',
        OAUTH_UPDATE_PICTURE_ON_LOGIN,
    ),
    'OAUTH_UPDATE_NAME_ON_LOGIN': (
        'oauth.update_name_on_login',
        OAUTH_UPDATE_NAME_ON_LOGIN,
    ),
    'OAUTH_UPDATE_EMAIL_ON_LOGIN': (
        'oauth.update_email_on_login',
        OAUTH_UPDATE_EMAIL_ON_LOGIN,
    ),
    'OAUTH_AUDIENCE': ('oauth.audience', OAUTH_AUDIENCE),
}




def _default_value(value):
    return getattr(value, 'value', value)


async def get_oauth_runtime_config() -> SimpleNamespace:
    keys = [key for key, _default in OAUTH_RUNTIME_CONFIG.values()]
    stored = await Config.get_many(*keys)
    values = {name: stored.get(key, _default_value(default)) for name, (key, default) in OAUTH_RUNTIME_CONFIG.items()}
    return SimpleNamespace(**values)


# Conservative default when the provider omits both expires_in and expires_at.
# Matches the value recommended by Authlib's compliance_fix documentation.
DEFAULT_TOKEN_EXPIRY_SECONDS = 3600
NON_EXPIRING_TOKEN_EXPIRES_AT = 253402300799  # 9999-12-31 23:59:59 UTC


def _normalize_token_expiry(token: dict) -> dict:
    """Ensure a token dict always has a numeric ``expires_at``.

    Resolution order:
    1. If *expires_at* is already present and non-None, trust it.
    2. Else if *expires_in* is present and non-None, compute *expires_at*.
    3. Else if a *refresh_token* is present, fall back to
       ``DEFAULT_TOKEN_EXPIRY_SECONDS`` and log a warning so operators can
       identify providers that omit expiration.
    4. Otherwise treat the token as non-expiring; there is no refresh path to
       recover from a fabricated short expiry.

    Also stamps *issued_at* for auditing.
    """
    token['issued_at'] = datetime.now().timestamp()

    if token.get('expires_at') is not None:
        expires_at = int(token['expires_at'])
    elif token.get('expires_in') is not None:
        expires_at = int(datetime.now().timestamp() + token['expires_in'])
    elif token.get('refresh_token'):
        log.warning(
            "OAuth token response missing both 'expires_in' and 'expires_at'; "
            f'defaulting to {DEFAULT_TOKEN_EXPIRY_SECONDS}s from now'
        )
        expires_at = int(datetime.now().timestamp() + DEFAULT_TOKEN_EXPIRY_SECONDS)
    else:
        log.info(
            "OAuth token response missing 'expires_in', 'expires_at' and 'refresh_token'; treating token as non-expiring"
        )
        expires_at = NON_EXPIRING_TOKEN_EXPIRES_AT

    id_token = token.get('id_token')
    if id_token:
        # Cap at the id_token expiry so pipes and tools never receive an expired JWT
        try:
            exp = jwt.decode(id_token, options={'verify_signature': False}).get('exp')
            if exp is not None:
                expires_at = min(expires_at, int(exp))
        except Exception as e:
            log.debug('Could not read exp from id_token: %s', e)

    token['expires_at'] = expires_at
    return token


def _build_oauth_callback_error_message(e: Exception) -> str:
    """
    Produce a user-facing callback error string with actionable context.
    Keeps the message short and strips newlines for safe redirect usage.
    """
    if isinstance(e, OAuth2Error):
        parts = [p for p in [e.error, e.description] if p]
        detail = ' - '.join(parts)
    elif isinstance(e, HTTPException):
        detail = e.detail if isinstance(e.detail, str) else str(e.detail)
    elif isinstance(e, aiohttp.ClientResponseError):
        detail = f'Upstream provider returned {e.status}: {e.message}'
    elif isinstance(e, aiohttp.ClientError):
        detail = str(e)
    elif isinstance(e, KeyError):
        missing = str(e).strip("'")
        if missing.lower() == 'state':
            detail = 'Missing state parameter in callback (session may have expired)'
        else:
            detail = f"Missing expected key '{missing}' in OAuth response"
    else:
        detail = str(e)

    detail = detail.replace('\n', ' ').strip()
    if not detail:
        detail = e.__class__.__name__

    message = f'OAuth callback failed: {detail}'
    return message[:197] + '...' if len(message) > 200 else message


def is_in_blocked_groups(group_name: str, groups: list) -> bool:
    """
    Check if a group name matches any blocked pattern.
    Supports exact matches, shell-style wildcards (*, ?), and regex patterns.

    Args:
        group_name: The group name to check
        groups: List of patterns to match against

    Returns:
        True if the group is blocked, False otherwise
    """
    if not groups:
        return False

    for group_pattern in groups:
        if not group_pattern:  # Skip empty patterns
            continue

        # Exact match
        if group_name == group_pattern:
            return True

        # Try as regex pattern first if it contains regex-specific characters
        if any(char in group_pattern for char in ['^', '$', '[', ']', '(', ')', '{', '}', '+', '\\', '|']):
            try:
                # Use the original pattern as-is for regex matching
                if re.search(group_pattern, group_name):
                    return True
            except re.error:
                # If regex is invalid, fall through to wildcard check
                pass

        # Shell-style wildcard match (supports * and ?)
        if '*' in group_pattern or '?' in group_pattern:
            if fnmatch.fnmatch(group_name, group_pattern):
                return True

    return False



class OAuthManager:
    def __init__(self, app):
        self.oauth = OAuth()
        self.app = app

        self._clients = {}

        for name, provider_config in OAUTH_PROVIDERS.items():
            if 'register' not in provider_config:
                log.error(f'OAuth provider {name} missing register function')
                continue

            client = provider_config['register'](self.oauth)
            self._clients[name] = client

    def get_client(self, provider_name):
        if provider_name not in self._clients:
            self._clients[provider_name] = self.oauth.create_client(provider_name)
        return self._clients[provider_name]

    def get_server_metadata_url(self, provider_name):
        if provider_name in self._clients:
            client = self._clients[provider_name]
            return client._server_metadata_url if hasattr(client, '_server_metadata_url') else None
        return None

    async def get_oauth_token(self, user_id: str, session_id: str, force_refresh: bool = False):
        """
        Get a valid OAuth token for the user, automatically refreshing if needed.

        Args:
            user_id: The user ID
            provider: Optional provider name. If None, gets the most recent session.
            force_refresh: Force token refresh even if current token appears valid

        Returns:
            dict: OAuth token data with access_token, or None if no valid token available
        """
        try:
            # Get the OAuth session
            session = await OAuthSessions.get_session_by_id_and_user_id(session_id, user_id)
            if not session:
                log.warning(f'No OAuth session found for user {user_id}, session {session_id}')
                return None

            # Guard: MCP-provider sessions must be refreshed by
            # oauth_client_manager, not the SSO OAuthManager.  If one
            # reaches here (e.g. via a stale cookie), bail out early
            # instead of attempting a refresh that will fail and delete
            # the session (#24618).
            if (session.provider or '').startswith('mcp:'):
                log.debug(
                    'Skipping MCP session %s (provider=%s) in SSO OAuthManager — handled by oauth_client_manager',
                    session.id,
                    session.provider,
                )
                return None

            if (
                force_refresh
                or session.expires_at is None
                or datetime.now() + timedelta(minutes=5) >= datetime.fromtimestamp(session.expires_at)
            ):
                log.debug('Token refresh needed for user %s, provider %s', user_id, session.provider)
                refreshed_token = await self._refresh_token(session)
                if refreshed_token:
                    return refreshed_token
                else:
                    log.warning(
                        f'Token refresh failed for user {user_id}, provider {session.provider}, deleting session {session.id}'
                    )
                    await OAuthSessions.delete_session_by_id(session.id)

                    return None
            return session.token

        except Exception as e:
            log.error(f'Error getting OAuth token for user {user_id}: {e}')
            return None

    async def _refresh_token(self, session) -> dict:
        """
        Refresh an OAuth token if needed, with concurrency protection.

        Args:
            session: The OAuth session object

        Returns:
            dict: Refreshed token data, or None if refresh failed
        """
        try:
            # Perform the actual refresh
            refreshed_token = await self._perform_token_refresh(session)

            if refreshed_token:
                # Update the session with new token data
                session = await OAuthSessions.update_session_by_id(session.id, refreshed_token)
                log.info('Successfully refreshed token for session %s', session.id)
                return session.token
            else:
                log.error(f'Failed to refresh token for session {session.id}')
                return None

        except Exception as e:
            log.error(f'Error refreshing token for session {session.id}: {e}')
            return None

    async def _perform_token_refresh(self, session) -> dict:
        """
        Perform the actual OAuth token refresh.

        Args:
            session: The OAuth session object

        Returns:
            dict: New token data, or None if refresh failed
        """
        provider = session.provider
        token_data = session.token
        auth_config = await get_oauth_runtime_config()

        if not token_data.get('refresh_token'):
            log.warning(f'No refresh token available for session {session.id}')
            return None

        try:
            client = self.get_client(provider)
            if not client:
                log.error(f'No OAuth client found for provider {provider}')
                return None

            server_metadata_url = self.get_server_metadata_url(provider)
            token_endpoint = None
            async with aiohttp.ClientSession(trust_env=True) as session_http:
                async with session_http.get(server_metadata_url) as r:
                    if r.status == 200:
                        openid_data = await r.json()
                        token_endpoint = openid_data.get('token_endpoint')
                    else:
                        log.error(f'Failed to fetch OpenID configuration for provider {provider}')
            if not token_endpoint:
                log.error(f'No token endpoint found for provider {provider}')
                return None

            # Prepare refresh request
            refresh_data = {
                'grant_type': 'refresh_token',
                'refresh_token': token_data['refresh_token'],
                'client_id': client.client_id,
            }
            # Add client_secret if available (some providers require it)
            if hasattr(client, 'client_secret') and client.client_secret:
                refresh_data['client_secret'] = client.client_secret

            # Add scope if available in client kwargs (some providers require it on refresh)
            if (
                hasattr(client, 'client_kwargs')
                and client.client_kwargs.get('scope')
                and auth_config.OAUTH_REFRESH_TOKEN_INCLUDE_SCOPE
            ):
                refresh_data['scope'] = client.client_kwargs['scope']

            # Make refresh request
            async with aiohttp.ClientSession(trust_env=True) as session_http:
                async with session_http.post(
                    token_endpoint,
                    data=refresh_data,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'},
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as r:
                    if r.status == 200:
                        new_token_data = await r.json()

                        # Merge with existing token data (preserve refresh_token if not provided)
                        if 'refresh_token' not in new_token_data:
                            new_token_data['refresh_token'] = token_data['refresh_token']

                        _normalize_token_expiry(new_token_data)

                        log.debug('Token refresh successful for provider %s', provider)
                        return new_token_data
                    else:
                        error_text = await r.text()
                        log.error(f'Token refresh failed for provider {provider}: {r.status} - {error_text}')
                        return None

        except Exception as e:
            log.error(f'Exception during token refresh for provider {provider}: {e}')
            return None

    async def get_user_role(self, user, user_data):
        auth_config = await get_oauth_runtime_config()
        user_count = await Users.get_num_users()
        if user and user_count == 1:
            # If the user is the only user, assign the role "admin" - actually repairs role for single user on login
            log.debug('Assigning the only user the admin role')
            return 'admin'
        if not user and user_count == 0:
            # First-user bootstrap: skip role management gating so the
            # instance can be initialized.  We intentionally return the
            # default role here (not 'admin') — admin promotion happens
            # race-safely *after* insert via get_num_users() == 1.
            log.debug('First user bootstrap: using default role (admin promotion deferred to post-insert)')
            return auth_config.DEFAULT_USER_ROLE

        if auth_config.ENABLE_OAUTH_ROLE_MANAGEMENT:
            log.debug('Running OAUTH Role management')
            oauth_claim = auth_config.OAUTH_ROLES_CLAIM
            oauth_allowed_roles = auth_config.OAUTH_ALLOWED_ROLES
            oauth_admin_roles = auth_config.OAUTH_ADMIN_ROLES
            oauth_roles = []
            # Keep existing users at their current role unless the provider sent roles.
            role = user.role if user else auth_config.DEFAULT_USER_ROLE

            # Next block extracts the roles from the user data, accepting nested claims of any depth
            if oauth_claim and oauth_allowed_roles and oauth_admin_roles:
                claim_data = user_data
                nested_claims = oauth_claim.split('.')
                for nested_claim in nested_claims:
                    claim_data = claim_data.get(nested_claim, {})

                # Try flat claim structure as alternative
                if not claim_data:
                    claim_data = user_data.get(oauth_claim, {})

                oauth_roles = []

                if isinstance(claim_data, list):
                    oauth_roles = claim_data
                elif isinstance(claim_data, str):
                    # Split by the configured separator if present
                    if OAUTH_ROLES_SEPARATOR and OAUTH_ROLES_SEPARATOR in claim_data:
                        oauth_roles = claim_data.split(OAUTH_ROLES_SEPARATOR)
                    else:
                        oauth_roles = [claim_data]
                elif isinstance(claim_data, int):
                    oauth_roles = [str(claim_data)]

            log.debug('Oauth Roles claim: %s', oauth_claim)
            log.debug('User roles from oauth: %s', oauth_roles)
            log.debug('Accepted user roles: %s', oauth_allowed_roles)
            log.debug('Accepted admin roles: %s', oauth_admin_roles)

            # If roles are present in the token, they must match; otherwise deny access
            if oauth_roles:
                matched = False
                for allowed_role in oauth_allowed_roles:
                    if allowed_role == '*' or allowed_role in oauth_roles:
                        log.debug('Assigned user the user role')
                        role = 'user'
                        matched = True
                        break
                for admin_role in oauth_admin_roles:
                    if admin_role in oauth_roles:
                        log.debug('Assigned user the admin role')
                        role = 'admin'
                        matched = True
                        break
                if not matched:
                    log.warning(
                        f'OAuth role management enabled but user roles do not match any allowed/admin roles. '
                        f'User roles: {oauth_roles}, allowed: {oauth_allowed_roles}, admin: {oauth_admin_roles}'
                    )
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN,
                        detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
                    )
        else:
            if not user:
                # If role management is disabled, use the default role for new users
                role = auth_config.DEFAULT_USER_ROLE
            else:
                # If role management is disabled, use the existing role for existing users
                role = user.role

        return role

    async def update_user_role_from_oauth(
        self,
        request,
        user,
        user_data,
        provider,
        *,
        db=None,
    ):
        determined_role = await self.get_user_role(user, user_data)
        if user.role == determined_role:
            return user

        updated_user = await Users.update_user_role_by_id(user.id, determined_role, db=db)
        user = updated_user or user
        user.role = determined_role
        await publish_event(
            request,
            EVENTS.USER_ROLE_UPDATED,
            actor=user,
            subject_id=user.id,
            source='oauth',
            data={'role': determined_role, 'provider': provider},
        )

        return user

    async def update_user_groups(self, request, user, user_data, default_permissions, db=None):
        auth_config = await get_oauth_runtime_config()
        log.debug('Running OAUTH Group management')
        oauth_claim = auth_config.OAUTH_GROUPS_CLAIM

        try:
            blocked_groups = JSONCodec.loads(auth_config.OAUTH_BLOCKED_GROUPS)
        except Exception as e:
            log.exception(f'Error loading OAUTH_BLOCKED_GROUPS: {e}')
            blocked_groups = []

        user_oauth_groups = []
        # Nested claim search for groups claim
        if oauth_claim:
            claim_data = user_data
            nested_claims = oauth_claim.split('.')
            for nested_claim in nested_claims:
                claim_data = claim_data.get(nested_claim, {})

            if isinstance(claim_data, list):
                user_oauth_groups = claim_data
            elif isinstance(claim_data, str):
                # Split by the configured separator if present
                if OAUTH_GROUPS_SEPARATOR in claim_data:
                    user_oauth_groups = claim_data.split(OAUTH_GROUPS_SEPARATOR)
                else:
                    user_oauth_groups = [claim_data]
            else:
                user_oauth_groups = []

        user_current_groups: list[GroupModel] = await Groups.get_groups_by_member_id(user.id, db=db)
        all_available_groups: list[GroupModel] = await Groups.get_all_groups(db=db)

        # Create groups if they don't exist and creation is enabled
        if auth_config.ENABLE_OAUTH_GROUP_CREATION:
            log.debug('Checking for missing groups to create...')
            all_group_names = {g.name for g in all_available_groups}
            groups_created = False
            # Determine creator ID: Prefer admin, fallback to current user if no admin exists
            admin_user = await Users.get_super_admin_user()
            creator_id = admin_user.id if admin_user else user.id
            log.debug('Using creator ID %s for potential group creation.', creator_id)

            for group_name in user_oauth_groups:
                if group_name not in all_group_names:
                    log.info("Group '%s' not found via OAuth claim. Creating group...", group_name)
                    try:
                        new_group_form = GroupForm(
                            name=group_name,
                            description=f"Group '{group_name}' created automatically via OAuth.",
                            permissions=default_permissions,  # Use default permissions from function args
                            data={'config': {'share': auth_config.OAUTH_GROUP_DEFAULT_SHARE}},
                        )
                        # Use determined creator ID (admin or fallback to current user)
                        created_group = await Groups.insert_new_group(creator_id, new_group_form, db=db)
                        if created_group:
                            log.info(
                                "Successfully created group '%s' with ID %s using creator ID %s",
                                group_name,
                                created_group.id,
                                creator_id,
                            )
                            groups_created = True
                            # Add to local set to prevent duplicate creation attempts in this run
                            all_group_names.add(group_name)
                            await publish_event(
                                request,
                                EVENTS.GROUP_CREATED,
                                subject_id=created_group.id,
                                source='oauth',
                                data={'name': created_group.name},
                            )
                        else:
                            log.error(f"Failed to create group '{group_name}' via OAuth.")
                    except Exception as e:
                        log.error(f"Error creating group '{group_name}' via OAuth: {e}")

            # Refresh the list of all available groups if any were created
            if groups_created:
                all_available_groups = await Groups.get_all_groups(db=db)
                log.debug('Refreshed list of all available groups after creation.')

        log.debug('Oauth Groups claim: %s', oauth_claim)
        log.debug('User oauth groups: %s', user_oauth_groups)
        log.debug("User's current groups: %s", [g.name for g in user_current_groups])
        log.debug('All groups available in OpenWebUI: %s', [g.name for g in all_available_groups])

        # Remove groups that user is no longer a part of
        for group_model in user_current_groups:
            if (
                user_oauth_groups
                and group_model.name not in user_oauth_groups
                and not is_in_blocked_groups(group_model.name, blocked_groups)
            ):
                # Remove group from user
                log.debug('Removing user from group %s as it is no longer in their oauth groups', group_model.name)
                if await Groups.remove_users_from_group(group_model.id, [user.id], db=db):
                    await publish_event(
                        request,
                        EVENTS.GROUP_MEMBER_REMOVED,
                        actor=user,
                        subject_id=group_model.id,
                        source='oauth',
                        data={'user_ids': [user.id]},
                    )

                # In case a group is created, but perms are never assigned to the group by hitting "save"
                group_permissions = group_model.permissions
                if not group_permissions:
                    group_permissions = default_permissions

                await Groups.update_group_by_id(
                    id=group_model.id,
                    form_data=GroupUpdateForm(
                        name=group_model.name,
                        description=group_model.description,
                        permissions=group_permissions,
                    ),
                    overwrite=False,
                    db=db,
                )

        # Add user to new groups
        for group_model in all_available_groups:
            if (
                user_oauth_groups
                and group_model.name in user_oauth_groups
                and not any(gm.name == group_model.name for gm in user_current_groups)
                and not is_in_blocked_groups(group_model.name, blocked_groups)
            ):
                # Add user to group
                log.debug('Adding user to group %s as it was found in their oauth groups', group_model.name)

                if await Groups.add_users_to_group(group_model.id, [user.id], db=db):
                    await publish_event(
                        request,
                        EVENTS.GROUP_MEMBER_ADDED,
                        actor=user,
                        subject_id=group_model.id,
                        source='oauth',
                        data={'user_ids': [user.id]},
                    )

                # In case a group is created, but perms are never assigned to the group by hitting "save"
                group_permissions = group_model.permissions
                if not group_permissions:
                    group_permissions = default_permissions

                await Groups.update_group_by_id(
                    id=group_model.id,
                    form_data=GroupUpdateForm(
                        name=group_model.name,
                        description=group_model.description,
                        permissions=group_permissions,
                    ),
                    overwrite=False,
                    db=db,
                )

    async def _process_picture_url(self, picture_url: str, access_token: str = None) -> str:
        """Process a picture URL and return a base64 encoded data URL.

        Args:
            picture_url: The URL of the picture to process
            access_token: Optional OAuth access token for authenticated requests

        Returns:
            A data URL containing the base64 encoded picture, or "/user.png" if processing fails
        """
        if not picture_url:
            return '/user.png'

        try:
            await asyncio.to_thread(validate_url, picture_url)

            get_kwargs = {}
            if access_token:
                get_kwargs['headers'] = {
                    'Authorization': f'Bearer {access_token}',
                }
            # get_ssrf_safe_session pins the connect-time IP (defeats DNS rebinding); allow_redirects=False keeps validate_url's vet authoritative.
            async with get_ssrf_safe_session() as session:
                async with session.get(
                    picture_url,
                    **get_kwargs,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                    allow_redirects=AIOHTTP_CLIENT_ALLOW_REDIRECTS,
                ) as resp:
                    if resp.ok:
                        upstream_mime = (resp.headers.get('Content-Type', '') or '').split(';', 1)[0].strip().lower()
                        picture = await resp.read()
                        base64_encoded_picture = base64.b64encode(picture).decode('utf-8')
                        try:
                            return validate_profile_image_url(f'data:{upstream_mime};base64,{base64_encoded_picture}')
                        except ValueError:
                            log.warning(
                                f'Rejected OAuth profile picture from {picture_url}: '
                                f'MIME {upstream_mime!r} is not allowed'
                            )
                            return '/user.png'
                    else:
                        log.warning(f'Failed to fetch profile picture from {picture_url}')
                        return '/user.png'
        except Exception as e:
            log.error(f"Error processing profile picture '{picture_url}': {e}")
            return '/user.png'

    async def handle_login(self, request, provider):
        auth_config = await get_oauth_runtime_config()
        if not auth_config.ENABLE_OAUTH:
            raise HTTPException(404)
        if provider not in OAUTH_PROVIDERS:
            raise HTTPException(404)
        # If the provider has a custom redirect URL, use that, otherwise automatically generate one
        client = self.get_client(provider)
        if client is None:
            raise HTTPException(404)
        redirect_uri = (client.server_metadata or {}).get('redirect_uri') or request.url_for(
            'oauth_login_callback', provider=provider
        )

        kwargs = {}
        if auth_config.OAUTH_AUDIENCE:
            kwargs['audience'] = auth_config.OAUTH_AUDIENCE
        if OAUTH_AUTHORIZE_PARAMS:
            kwargs.update(OAUTH_AUTHORIZE_PARAMS)

        return await client.authorize_redirect(request, redirect_uri, **kwargs)

    async def handle_callback(self, request, provider, response, db=None):
        auth_config = await get_oauth_runtime_config()
        if not auth_config.ENABLE_OAUTH:
            raise HTTPException(404)
        if provider not in OAUTH_PROVIDERS:
            raise HTTPException(404)

        error_message = None
        try:
            client = self.get_client(provider)

            auth_params = {}

            if client:
                if hasattr(client, 'client_id') and OAUTH_ACCESS_TOKEN_REQUEST_INCLUDE_CLIENT_ID:
                    auth_params['client_id'] = client.client_id

            try:
                token = await client.authorize_access_token(request, **auth_params)
            except BadSignatureError:
                # The IdP likely rotated its signing keys and the cached JWKS
                # is stale.  Evict the cached key set so the next attempt
                # fetches fresh keys from the jwks_uri.
                log.warning(
                    'OIDC bad_signature for provider %s — evicting cached JWKS and retrying',
                    provider,
                )
                if hasattr(client, 'server_metadata') and isinstance(client.server_metadata, dict):
                    client.server_metadata.pop('jwks', None)
                try:
                    token = await client.authorize_access_token(request, **auth_params)
                except Exception as retry_exc:
                    detailed_error = _build_oauth_callback_error_message(retry_exc)
                    log.warning(
                        'OAuth callback error during authorize_access_token retry for provider %s: %s',
                        provider,
                        detailed_error,
                        exc_info=True,
                    )
                    raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)
            except Exception as e:
                detailed_error = _build_oauth_callback_error_message(e)
                log.warning(
                    'OAuth callback error during authorize_access_token for provider %s: %s',
                    provider,
                    detailed_error,
                    exc_info=True,
                )
                raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)

            # Try to get userinfo from the token first, some providers include it there
            user_data: UserInfo = token.get('userinfo')
            # Preserve extra claims from the ID token (e.g. roles, groups for
            # Microsoft Entra ID) before the userinfo endpoint possibly overwrites them.
            id_token_claims = dict(user_data) if user_data else {}
            if (
                (not user_data)
                or (auth_config.OAUTH_EMAIL_CLAIM not in user_data)
                or (auth_config.OAUTH_USERNAME_CLAIM not in user_data)
            ):
                user_data: UserInfo = await client.userinfo(token=token)
                # Merge back ID token claims that the userinfo endpoint doesn't
                # return.  Only backfill missing keys so userinfo always wins.
                if user_data and id_token_claims:
                    for key, value in id_token_claims.items():
                        if key not in user_data:
                            user_data[key] = value
            if provider == 'feishu' and isinstance(user_data, dict) and 'data' in user_data:
                user_data = user_data['data']
            if not user_data:
                log.warning(f'OAuth callback failed, user data is missing: {token}')
                raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)

            # Extract the "sub" claim, using custom claim if configured
            if auth_config.OAUTH_SUB_CLAIM:
                sub = user_data.get(auth_config.OAUTH_SUB_CLAIM)
            else:
                # Fallback to the default sub claim if not configured
                sub = user_data.get(OAUTH_PROVIDERS[provider].get('sub_claim', 'sub'))
            if not sub:
                log.warning(f'OAuth callback failed, sub is missing: {user_data}')
                raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)
            sub = str(sub)

            oauth_data = {}
            oauth_data[provider] = {
                'sub': sub,
            }

            # Email extraction
            email_claim = auth_config.OAUTH_EMAIL_CLAIM
            email = user_data.get(email_claim, '')
            # We currently mandate that email addresses are provided
            if not email:
                # If the provider is GitHub,and public email is not provided, we can use the access token to fetch the user's email
                if provider == 'github':
                    try:
                        access_token = token.get('access_token')
                        headers = {'Authorization': f'Bearer {access_token}'}
                        async with aiohttp.ClientSession(trust_env=True) as session:
                            async with session.get(
                                'https://api.github.com/user/emails',
                                headers=headers,
                                ssl=AIOHTTP_CLIENT_SESSION_SSL,
                            ) as resp:
                                if resp.ok:
                                    emails = await resp.json()
                                    # use the primary email as the user's email
                                    primary_email = next(
                                        (e['email'] for e in emails if e.get('primary')),
                                        None,
                                    )
                                    if primary_email:
                                        email = primary_email
                                    else:
                                        log.warning('No primary email found in GitHub response')
                                        raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)
                                else:
                                    log.warning('Failed to fetch GitHub email')
                                    raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)
                    except Exception as e:
                        log.warning(f'Error fetching GitHub email: {e}')
                        raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)
                elif ENABLE_OAUTH_EMAIL_FALLBACK:
                    email = f'{provider}@{sub}.local'
                else:
                    log.warning(f'OAuth callback failed, email is missing: {user_data}')
                    raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)

            email = email.lower()
            # If allowed domains are configured, check if the email domain is in the list
            if (
                '*' not in auth_config.OAUTH_ALLOWED_DOMAINS
                and email.split('@')[-1] not in auth_config.OAUTH_ALLOWED_DOMAINS
            ):
                log.warning(f'OAuth callback failed, e-mail domain is not in the list of allowed domains: {user_data}')
                raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)

            # Check if the user exists
            user = await Users.get_user_by_oauth_sub(provider, sub, db=db)
            if not user:
                # If the user does not exist, check if merging is enabled
                if auth_config.OAUTH_MERGE_ACCOUNTS_BY_EMAIL:
                    # Check if the user exists by email
                    user = await Users.get_user_by_email(email, db=db)
                    if user:
                        # Update the user with the new oauth sub
                        user = await Users.update_user_oauth_by_id(user.id, provider, sub, db=db) or user

            if user:
                provider_oauth = (user.oauth or {}).get(provider) if isinstance(user.oauth, dict) else None
                # Lazy repair for legacy rows that stored numeric provider ids as JSON numbers.
                if isinstance(provider_oauth, dict) and provider_oauth.get('sub') != sub:
                    user = await Users.update_user_oauth_by_id(user.id, provider, sub, db=db) or user

            if user:
                user = await self.update_user_role_from_oauth(
                    request=request,
                    user=user,
                    user_data=user_data,
                    provider=provider,
                    db=db,
                )

                updated_fields = []

                if auth_config.OAUTH_UPDATE_NAME_ON_LOGIN:
                    username_claim = auth_config.OAUTH_USERNAME_CLAIM
                    if username_claim:
                        new_name = user_data.get(username_claim)
                        if new_name and new_name != user.name:
                            updated_user = await Users.update_user_by_id(user.id, {'name': new_name}, db=db)
                            if updated_user:
                                user = updated_user
                                updated_fields.append('name')
                                log.debug('Updated name for user %s', user.email)

                if auth_config.OAUTH_UPDATE_EMAIL_ON_LOGIN:
                    email_claim = auth_config.OAUTH_EMAIL_CLAIM
                    if email_claim:
                        new_email = user_data.get(email_claim)
                        if new_email and new_email.lower() != user.email.lower():
                            existing_user = await Users.get_user_by_email(new_email, db=db)
                            if existing_user:
                                log.error(
                                    f'Cannot update email to {new_email} for user {user.id} because it is already taken.'
                                )
                            elif await Auths.update_email_by_id(user.id, new_email.lower(), db=db):
                                user = await Users.get_user_by_id(user.id, db=db) or user
                                updated_fields.append('email')
                                log.debug('Updated email for user %s', user.id)

                # Update profile picture if enabled and different from current
                if auth_config.OAUTH_UPDATE_PICTURE_ON_LOGIN:
                    picture_claim = auth_config.OAUTH_PICTURE_CLAIM
                    if picture_claim:
                        new_picture_url = user_data.get(
                            picture_claim,
                            OAUTH_PROVIDERS[provider].get('picture_url', ''),
                        )
                        processed_picture_url = await self._process_picture_url(
                            new_picture_url, token.get('access_token')
                        )
                        if processed_picture_url != user.profile_image_url:
                            updated_user = await Users.update_user_profile_image_url_by_id(
                                user.id, processed_picture_url, db=db
                            )
                            if updated_user:
                                user = updated_user
                                updated_fields.append('profile_image_url')
                                log.debug('Updated profile picture for user %s', user.email)

                if updated_fields:
                    await publish_event(
                        request,
                        EVENTS.USER_UPDATED,
                        actor=user,
                        subject_id=user.id,
                        source='oauth',
                        data={'updated_fields': updated_fields, 'provider': provider},
                    )
            else:
                # If the user does not exist, check if signups are enabled
                if auth_config.ENABLE_OAUTH_SIGNUP:
                    # Check if an existing user with the same email already exists
                    existing_user = await Users.get_user_by_email(email, db=db)
                    if existing_user:
                        raise HTTPException(400, detail=ERROR_MESSAGES.EMAIL_TAKEN)

                    picture_claim = auth_config.OAUTH_PICTURE_CLAIM
                    if picture_claim:
                        picture_url = user_data.get(
                            picture_claim,
                            OAUTH_PROVIDERS[provider].get('picture_url', ''),
                        )
                        picture_url = await self._process_picture_url(picture_url, token.get('access_token'))
                    else:
                        picture_url = '/user.png'
                    username_claim = auth_config.OAUTH_USERNAME_CLAIM

                    name = user_data.get(username_claim)
                    if not name:
                        log.warning('Username claim is missing, using email as name')
                        name = email

                    user = await Auths.insert_new_auth(
                        email=email,
                        password=await get_password_hash(str(uuid.uuid4())),  # Random password, not used
                        name=name,
                        profile_image_url=picture_url,
                        role=await self.get_user_role(None, user_data),
                        oauth=oauth_data,
                        db=db,
                    )

                    if not user:
                        raise HTTPException(500, detail=ERROR_MESSAGES.CREATE_USER_ERROR)

                    # Atomically check if this is the only user *after* the
                    # insert to avoid TOCTOU race on first-user registration.
                    # Matches signup_handler pattern.
                    if await Users.get_num_users(db=db) == 1:
                        await Users.update_user_role_by_id(user.id, 'admin', db=db)
                        user = await Users.get_user_by_id(user.id, db=db)

                    default_group_id = await Config.get('ui.default_group_id')
                    await apply_default_group_assignment(default_group_id, user.id, db=db)
                    await publish_event(
                        request,
                        EVENTS.USER_CREATED,
                        actor=user,
                        subject_id=user.id,
                        source='oauth',
                        data={'role': user.role, 'provider': provider},
                    )

                else:
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN,
                        detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
                    )

            jwt_token = create_token(
                data={'id': user.id},
                expires_delta=parse_duration(auth_config.JWT_EXPIRES_IN),
            )
            if auth_config.ENABLE_OAUTH_GROUP_MANAGEMENT:
                await self.update_user_groups(
                    request=request,
                    user=user,
                    user_data=user_data,
                    default_permissions=await Config.get('user.permissions'),
                    db=db,
                )

        except Exception as e:
            log.error(f'Error during OAuth process: {e}')
            error_message = (
                e.detail
                if isinstance(e, HTTPException) and e.detail
                else ERROR_MESSAGES.DEFAULT('Error during OAuth process')
            )

        webui_url = await Config.get('webui.url')
        redirect_base_url = (str(webui_url or request.base_url)).rstrip('/')
        redirect_url = f'{redirect_base_url}/auth'

        if error_message:
            redirect_url = f'{redirect_url}?error={urllib.parse.quote_plus(error_message)}'
            return RedirectResponse(url=redirect_url, headers=response.headers)

        response = RedirectResponse(url=redirect_url, headers=response.headers)

        # Compute cookie expiry from JWT lifetime
        expires_delta = parse_duration(auth_config.JWT_EXPIRES_IN)
        cookie_max_age = int(expires_delta.total_seconds()) if expires_delta else None

        # Set the cookie token
        # Redirect back to the frontend with the JWT token
        response.set_cookie(
            key='token',
            value=jwt_token,
            httponly=False,  # Required for frontend access
            samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
            secure=WEBUI_AUTH_COOKIE_SECURE,
            **({'max_age': cookie_max_age} if cookie_max_age is not None else {}),
        )

        await publish_event(
            request,
            EVENTS.AUTH_LOGIN,
            actor=user,
            subject_id=user.id,
            subject_type='user',
            source='oauth',
            data={'auth_method': 'oauth', 'provider': provider},
        )

        # Legacy cookies for compatibility with older frontend versions
        if ENABLE_OAUTH_ID_TOKEN_COOKIE:
            response.set_cookie(
                key='oauth_id_token',
                value=token.get('id_token'),
                httponly=True,
                samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
                secure=WEBUI_AUTH_COOKIE_SECURE,
                **({'max_age': cookie_max_age} if cookie_max_age is not None else {}),
            )

        try:
            _normalize_token_expiry(token)

            # Enforce max concurrent sessions per user/provider to prevent
            # unbounded growth while allowing multi-device usage
            sessions = await OAuthSessions.get_sessions_by_user_id(user.id, db=db)
            provider_sessions = sorted(
                [session for session in sessions if session.provider == provider],
                key=lambda session: session.created_at,
                reverse=True,
            )
            # Keep the newest sessions up to the limit, prune the rest
            if len(provider_sessions) >= OAUTH_MAX_SESSIONS_PER_USER:
                for old_session in provider_sessions[OAUTH_MAX_SESSIONS_PER_USER - 1 :]:
                    await OAuthSessions.delete_session_by_id(old_session.id, db=db)

            session = await OAuthSessions.create_session(
                user_id=user.id,
                provider=provider,
                token=token,
                db=db,
            )

            if session:
                response.set_cookie(
                    key='oauth_session_id',
                    value=session.id,
                    httponly=True,
                    samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
                    secure=WEBUI_AUTH_COOKIE_SECURE,
                    **({'max_age': cookie_max_age} if cookie_max_age is not None else {}),
                )

                log.info('Stored OAuth session server-side for user %s, provider %s', user.id, provider)
            else:
                log.warning(f'Failed to create OAuth session for user {user.id}, provider {provider}')
        except Exception as e:
            log.error(f'Failed to store OAuth session server-side: {e}')

        return response

    async def handle_backchannel_logout(self, request, db=None):
        """
        Handle an OIDC Back-Channel Logout request.
        Validates the logout_token, identifies the user, revokes their
        sessions via Redis, and deletes their OAuth sessions.
        Returns a JSONResponse per the OIDC Back-Channel Logout 1.0 spec.
        """
        from fastapi.responses import JSONResponse

        # 1. Extract logout_token from form body
        try:
            form = await request.form()
            logout_token = form.get('logout_token')
        except Exception:
            logout_token = None

        if not logout_token:
            return JSONResponse(
                status_code=400,
                content={'error': 'invalid_request', 'error_description': 'Missing logout_token parameter'},
            )

        # 2. Peek at unverified issuer to match against configured providers
        try:
            unverified_claims = jwt.decode(logout_token, options={'verify_signature': False})
            token_issuer = unverified_claims.get('iss')
        except Exception as e:
            log.warning(f'Back-channel logout: cannot decode logout_token: {e}')
            return JSONResponse(
                status_code=400,
                content={'error': 'invalid_request', 'error_description': 'Malformed logout_token'},
            )

        if not token_issuer:
            return JSONResponse(
                status_code=400,
                content={'error': 'invalid_request', 'error_description': 'logout_token missing iss claim'},
            )

        # 3. Find the configured provider whose issuer matches the token
        matched_provider = None
        matched_client = None
        matched_jwks_uri = None

        for provider_name in OAUTH_PROVIDERS:
            client = self.get_client(provider_name)
            if not client:
                continue

            try:
                oidc_config = await client.load_server_metadata()
            except Exception as e:
                log.debug('Back-channel logout: error checking provider %s: %s', provider_name, e)
                continue

            if oidc_config.get('issuer') == token_issuer:
                matched_provider = provider_name
                matched_client = client
                matched_jwks_uri = oidc_config.get('jwks_uri')
                break

        if not matched_provider or not matched_client or not matched_client.client_id or not matched_jwks_uri:
            log.warning(f'Back-channel logout: no configured provider matches issuer {token_issuer}')
            return JSONResponse(
                status_code=400,
                content={
                    'error': 'invalid_request',
                    'error_description': 'No configured provider matches token issuer',
                },
            )

        # 4. Validate the logout_token signature and claims
        try:
            token_kid = jwt.get_unverified_header(logout_token).get('kid')
            if not token_kid:
                raise jwt.InvalidTokenError('logout_token missing kid header')

            try:
                jwk_set = jwt.PyJWKSet.from_dict(await matched_client.fetch_jwk_set())
            except jwt.PyJWTError as e:
                raise jwt.InvalidTokenError(str(e))

            signing_key = next(
                (key for key in jwk_set.keys if key.key_id == token_kid and key.public_key_use in ['sig', None]),
                None,
            )
            if not signing_key:
                raise jwt.InvalidTokenError('no signing key matches the token kid')

            claims = jwt.decode(
                logout_token,
                signing_key.key,
                algorithms=['RS256', 'RS384', 'RS512', 'ES256', 'ES384', 'ES512'],
                audience=matched_client.client_id,
                issuer=token_issuer,
                options={
                    'require': ['iss', 'aud', 'iat', 'events'],
                },
            )
        except jwt.InvalidTokenError as e:
            log.warning(f'Back-channel logout: invalid logout_token: {e}')
            return JSONResponse(
                status_code=400,
                content={'error': 'invalid_request', 'error_description': f'Invalid logout_token: {e}'},
            )
        except Exception as e:
            log.error(f'Back-channel logout: error validating logout_token: {e}')
            return JSONResponse(
                status_code=400,
                content={'error': 'invalid_request', 'error_description': 'Failed to validate logout_token'},
            )

        # 5. Validate events claim per spec
        events = claims.get('events', {})
        if 'http://schemas.openid.net/event/backchannel-logout' not in events:
            log.warning('Back-channel logout: missing required backchannel-logout event claim')
            return JSONResponse(
                status_code=400,
                content={'error': 'invalid_request', 'error_description': 'Missing backchannel-logout event claim'},
            )

        # 6. Per spec, back-channel logout tokens MUST NOT contain a nonce
        if 'nonce' in claims:
            log.warning('Back-channel logout: logout_token contains nonce (rejected per spec)')
            return JSONResponse(
                status_code=400,
                content={'error': 'invalid_request', 'error_description': 'logout_token must not contain nonce'},
            )

        # 7. Extract sub and/or sid — at least one must be present
        sub = claims.get('sub')
        sid = claims.get('sid')

        if not sub and not sid:
            log.warning('Back-channel logout: logout_token contains neither sub nor sid')
            return JSONResponse(
                status_code=400,
                content={'error': 'invalid_request', 'error_description': 'logout_token must contain sub or sid'},
            )

        # 8. Identify users to log out
        users_to_logout = []
        if sub:
            user = await Users.get_user_by_oauth_sub(matched_provider, str(sub), db=db)
            if user:
                users_to_logout.append(user)

        if not users_to_logout and sid:
            log.debug('Back-channel logout: no user found by sub, sid-based lookup not yet supported (sid=%s)', sid)

        if not users_to_logout:
            log.debug(
                'Back-channel logout: no matching user for provider=%s, sub=%s, sid=%s', matched_provider, sub, sid
            )
            return JSONResponse(status_code=200, content={})

        # 9. Revoke tokens and delete sessions
        redis = request.app.state.redis
        if not redis:
            log.warning(
                'Back-channel logout: Redis not configured, cannot revoke JWT tokens. '
                'OAuth sessions will be deleted but existing JWTs will remain valid until expiry.'
            )

        revoked_count = 0
        for user in users_to_logout:
            sessions = await OAuthSessions.get_sessions_by_user_id(user.id, db=db)
            for oauth_session in sessions:
                await OAuthSessions.delete_session_by_id(oauth_session.id, db=db)

            if redis:
                await revoke_user_tokens(request, user.id)
                revoked_count += 1

            log.info(
                'Back-channel logout: revoked sessions for user %s (email=%s, provider=%s, sessions_deleted=%s)',
                user.id,
                user.email,
                matched_provider,
                len(sessions),
            )

        log.info(
            'Back-channel logout: completed for %s user(s), %s revocation(s) set', len(users_to_logout), revoked_count
        )
        return JSONResponse(status_code=200, content={})
