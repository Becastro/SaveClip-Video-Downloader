from app.local_store import LocalStore


def test_local_store_updates_and_reads_task_state(tmp_path):
    store = LocalStore(tmp_path / "saveclip.db")
    store.set_task_state("task-1", {"status": "queued", "percent": 0})
    store.set_task_state("task-1", {"status": "downloading", "percent": 42.5})
    assert store.get_task_state("task-1") == {
        "status": "downloading",
        "percent": "42.5",
    }


def test_local_store_rate_limits_within_window(tmp_path):
    store = LocalStore(tmp_path / "saveclip.db")
    assert store.increment_rate_window("ip:window", 60) == 1
    assert store.increment_rate_window("ip:window", 60) == 2
