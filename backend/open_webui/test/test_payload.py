import pytest

from open_webui.utils.payload import apply_model_params_to_body_openai


@pytest.mark.parametrize(
    'stop, expected',
    [
        ('終', '終'),
        ('café', 'café'),
        ('\U0001f600', '\U0001f600'),
        ('before 終 after', 'before 終 after'),
        (r'\n', '\n'),
        (r'\\n', r'\n'),
        ('終\n', '終\n'),
    ],
)
def test_stop_sequences_are_preserved(stop, expected):
    form_data = apply_model_params_to_body_openai({'stop': [stop]}, {})

    assert form_data['stop'] == [expected]
