import pytest

from src.modules.identity.authorization import allow_roles, get_allowed_roles


def test_allow_roles_marks_handler_with_allowed_roles() -> None:
    @allow_roles("admin", "operator")
    def handler() -> None:
        pass

    assert get_allowed_roles(handler) == frozenset({"admin", "operator"})


def test_handler_without_policy_is_detected() -> None:
    def handler() -> None:
        pass

    assert get_allowed_roles(handler) is None


def test_allow_roles_rejects_empty_policy() -> None:
    with pytest.raises(ValueError, match="ít nhất một vai trò"):
        allow_roles()
