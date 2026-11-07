from uuid import uuid4

import pytest

from open_webui.utils.chat_id import (
    get_temporary_chat_session_id,
    is_saved_chat_id,
    is_temporary_chat_id,
)


def test_session_id_from_legacy_temporary_chat():
    assert get_temporary_chat_session_id('temporary:session-a') == 'session-a'
    assert get_temporary_chat_session_id('local:session-a') == 'session-a'


def test_session_id_from_conversation_scoped_temporary_chat():
    conversation_id = str(uuid4())
    assert get_temporary_chat_session_id(f'temporary:session-a:{conversation_id}') == 'session-a'
    assert get_temporary_chat_session_id(f'local:session-a:{conversation_id}') == 'session-a'


@pytest.mark.parametrize(
    'chat_id',
    [
        'temporary:',
        'temporary:session-a:not-a-uuid',
        'temporary:session-a:',
        f'temporary:session-a:{str(uuid4()).upper()}',
        f'temporary:session-a:{{{uuid4()}}}',
    ],
)
def test_invalid_temporary_chat_ids(chat_id):
    assert get_temporary_chat_session_id(chat_id) is None


def test_non_temporary_chat_id_has_no_session():
    assert get_temporary_chat_session_id('chat-id') is None
    assert get_temporary_chat_session_id('channel:session-a') is None


def test_saved_and_temporary_classification():
    assert is_temporary_chat_id('temporary:session-a')
    assert is_temporary_chat_id('local:session-a')
    assert not is_temporary_chat_id('chat-id')
    assert not is_temporary_chat_id(None)

    assert is_saved_chat_id('chat-id')
    assert not is_saved_chat_id('temporary:session-a')
    assert not is_saved_chat_id('local:session-a')
    assert not is_saved_chat_id('channel:session-a')
    assert not is_saved_chat_id(None)
