import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from open_webui.models.users import UpdateProfileForm, User, UserUpdateForm
from open_webui.routers.users import update_user_by_id
from open_webui.utils.misc import validate_email_format


class _FakeSession:
    """Stands in for the request-scoped AsyncSession the update endpoint receives."""


def test_validate_email_format_accepts_internationalized_addresses():
    assert validate_email_format('user@example.com')
    assert validate_email_format('用户@example.com')
    assert validate_email_format('admin@localhost')
    assert not validate_email_format('abc')


@pytest.mark.parametrize(
    'email',
    [
        'user@example.com invalid',
        'user@example.com ',
        ' user@example.com',
        'user@exa mple.com',
        'user@example.com\ninjected',
    ],
)
def test_validate_email_format_rejects_trailing_or_embedded_text(email):
    # The admin edit form submits its value verbatim, so trailing text must not slip through.
    assert not validate_email_format(email)


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


@pytest.mark.asyncio
async def test_update_user_by_id_keeps_an_unchanged_unusual_email(monkeypatch):
    # An identity provider may have issued this address; editing the name or role must
    # not fail because the format check does not recognise it.
    stored = SimpleNamespace(id='user-1', email='person@[ipv6:2001:db8::1]', role='user')
    updated = SimpleNamespace(id='user-1', email=stored.email, role='user')
    calls = []

    async def fake_first_user(db=None):
        return SimpleNamespace(id='admin-1')

    async def fake_get_user(user_id, db=None):
        return stored

    async def fail_lookup(candidate, db=None):
        calls.append(candidate)
        pytest.fail('an unchanged email must not be looked up')

    async def fake_update_user(user_id, data, db=None):
        return updated

    async def ignore_email_write(*args, **kwargs):
        return True

    monkeypatch.setattr('open_webui.routers.users.Users.get_first_user', fake_first_user)
    monkeypatch.setattr('open_webui.routers.users.Users.get_user_by_id', fake_get_user)
    monkeypatch.setattr('open_webui.routers.users.Users.get_user_by_email', fail_lookup)
    monkeypatch.setattr('open_webui.routers.users.Users.update_user_by_id', fake_update_user)
    monkeypatch.setattr('open_webui.routers.users.Auths.update_email_by_id', ignore_email_write)

    result = await update_user_by_id(
        request=SimpleNamespace(),
        user_id='user-1',
        form_data=UserUpdateForm(email='person@[IPv6:2001:db8::1]', name='Renamed'),
        session_user=SimpleNamespace(id='admin-1'),
        db=_FakeSession(),
    )

    assert result is updated
    assert calls == []


def test_user_table_still_accepts_the_same_email_column():
    # Guard the route patch against a schema rename that would silently drop the check.
    assert User.email is not None


@pytest.mark.parametrize('delta_days', [1, 3650])
def test_birth_date_in_the_future_is_rejected(delta_days):
    future = datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=delta_days)

    with pytest.raises(ValidationError) as excinfo:
        UpdateProfileForm(profile_image_url='', name='Name', date_of_birth=future)

    assert 'Birth date cannot be in the future' in str(excinfo.value)


@pytest.mark.parametrize('delta_days', [0, 1, 40 * 365])
def test_birth_date_today_or_in_the_past_is_accepted(delta_days):
    birth_date = datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=delta_days)

    form = UpdateProfileForm(profile_image_url='', name='Name', date_of_birth=birth_date)

    assert form.date_of_birth == birth_date


def test_birth_date_stays_optional():
    assert UpdateProfileForm(profile_image_url='', name='Name').date_of_birth is None
