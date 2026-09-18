from open_webui.utils.misc import get_latest_semver_tag


def test_ignores_non_semver_tags():
    assert get_latest_semver_tag(['main', 'dev', '']) is None
    assert get_latest_semver_tag([]) is None
    assert get_latest_semver_tag(None) is None


def test_picks_highest_semver_numerically():
    assert get_latest_semver_tag(['v0.11.9', 'v0.11.10', 'v0.9.99']) == '0.11.10'


def test_strips_leading_v():
    assert get_latest_semver_tag(['v1.2.3']) == '1.2.3'
    assert get_latest_semver_tag(['1.2.3']) == '1.2.3'


def test_keeps_suffix():
    assert get_latest_semver_tag(['v0.11.4-pure']) == '0.11.4-pure'


def test_ignores_non_string_entries():
    assert get_latest_semver_tag([None, 42, 'v1.0.0']) == '1.0.0'
