"""Lazy access to the OAuth manager.

Importing :mod:`open_webui.utils.oauth` pulls in authlib/joserfc and registers
every configured provider. Deployments that never use OAuth should not pay that
cost at startup, so the manager is created on first use and cached on
``app.state``.
"""

from __future__ import annotations

from typing import Any


def get_oauth_manager(request_or_app: Any):
    """Return the app's OAuthManager, creating it on first use."""
    app = getattr(request_or_app, 'app', request_or_app)
    manager = getattr(app.state, 'oauth_manager', None)
    if manager is None:
        from open_webui.utils.oauth import OAuthManager

        manager = OAuthManager(app)
        app.state.oauth_manager = manager
    return manager
