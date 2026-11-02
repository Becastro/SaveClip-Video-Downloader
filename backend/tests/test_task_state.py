import pytest

from app.local_store import LocalStore
from app.task_state import TaskStatus, is_terminal, validate_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (None, TaskStatus.QUEUED.value),
        ("queued", "analyzing"),
        ("analyzing", "downloading"),
        ("downloading", "processing"),
        ("processing", "completed"),
        ("queued", "cancelled"),
        ("downloading", "cancel_requested"),
        ("cancel_requested", "cancelled"),
    ],
)
def test_valid_task_transitions(current, target):
    validate_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("completed", "downloading"),
        ("failed", "completed"),
        ("queued", "completed"),
        ("unknown", "downloading"),
    ],
)
def test_invalid_task_transitions_are_rejected(current, target):
    with pytest.raises(ValueError, match="Transição|Estado"):
        validate_transition(current, target)


def test_terminal_task_states_are_identified():
    assert is_terminal("completed")
    assert is_terminal("failed")
    assert is_terminal("cancelled")
    assert not is_terminal("cancel_requested")


def test_local_store_rejects_invalid_task_transition_atomically(tmp_path):
    store = LocalStore(tmp_path / "state.db")
    store.set_task_state("task-id", {"status": TaskStatus.QUEUED.value})

    with pytest.raises(ValueError, match="Transição"):
        store.set_task_state("task-id", {"status": TaskStatus.COMPLETED.value})

    assert store.get_task_state("task-id")["status"] == TaskStatus.QUEUED.value
