from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from open_webui.models.users import User, UserUpdateForm
from open_webui.routers.users import update_user_by_id
from open_webui.utils.misc import validate_email_format


class _FakeSession:
    """Stands in for the request-scoped AsyncSession the update endpoint receives."""


def test_validate_email_format_accepts_internationalized_addresses():
    assert validate_email_format('user@example.com')
    assert validate_email_format('用户@example.com')
    assert validate_email_format('admin@localhost')
    assert not validate_email_format('abc')


@pytest.mark.asyncio
@pytest.mark.parametrize('email', ['abc', 'user@@example.com', 'user@example'])
async def test_update_user_by_id_rejects_invalid_email(monkeypatch, email):
    stored = SimpleNamespace(id='user-1', email='old@example.com', role='user')

    async def fake_first_user(db=None):
        return SimpleNamespace(id='admin-1')

    async def fake_get_user(user_id, db=None):
        return stored

    async def fail_lookup(candidate, db=None):
        pytest.fail('an invalid email must be rejected before the duplicate lookup')

    monkeypatch.setattr('open_webui.routers.users.Users.get_first_user', fake_first_user)
    monkeypatch.setattr('open_webui.routers.users.Users.get_user_by_id', fake_get_user)
    monkeypatch.setattr('open_webui.routers.users.Users.get_user_by_email', fail_lookup)

    with pytest.raises(HTTPException) as excinfo:
        await update_user_by_id(
            request=SimpleNamespace(),
            user_id='user-1',
            form_data=UserUpdateForm(email=email),
            session_user=SimpleNamespace(id='admin-1'),
            db=_FakeSession(),
        )

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_update_user_by_id_still_allows_the_same_email(monkeypatch):
    stored = SimpleNamespace(id='user-1', email='old@example.com', role='user')
    updated = SimpleNamespace(id='user-1', email='old@example.com', role='user')
    calls = []

    async def fake_first_user(db=None):
        return SimpleNamespace(id='admin-1')

    async def fake_get_user(user_id, db=None):
        return stored

    async def fake_get_user_by_email(candidate, db=None):
        calls.append(candidate)
        return stored

    async def fake_update_user(user_id, data, db=None):
        return updated

    monkeypatch.setattr('open_webui.routers.users.Users.get_first_user', fake_first_user)
    monkeypatch.setattr('open_webui.routers.users.Users.get_user_by_id', fake_get_user)
    monkeypatch.setattr('open_webui.routers.users.Users.get_user_by_email', fake_get_user_by_email)
    monkeypatch.setattr('open_webui.routers.users.Users.update_user_by_id', fake_update_user)

    result = await update_user_by_id(
        request=SimpleNamespace(),
        user_id='user-1',
        form_data=UserUpdateForm(email='Old@Example.com'),
        session_user=SimpleNamespace(id='admin-1'),
        db=_FakeSession(),
    )

    assert result is updated
    assert calls == []


def test_user_table_still_accepts_the_same_email_column():
    # Guard the route patch against a schema rename that would silently drop the check.
    assert User.email is not None
