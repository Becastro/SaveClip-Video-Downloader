import json
from enum import StrEnum

from redis.exceptions import WatchError


class TaskStatus(StrEnum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    CANCEL_REQUESTED = "cancel_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {
    TaskStatus.COMPLETED.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELLED.value,
}

_ALLOWED_TRANSITIONS = {
    None: {TaskStatus.QUEUED},
    TaskStatus.QUEUED: {
        TaskStatus.ANALYZING,
        TaskStatus.DOWNLOADING,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    },
    TaskStatus.ANALYZING: {
        TaskStatus.DOWNLOADING,
        TaskStatus.PROCESSING,
        TaskStatus.CANCEL_REQUESTED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    },
    TaskStatus.DOWNLOADING: {
        TaskStatus.PROCESSING,
        TaskStatus.CANCEL_REQUESTED,
        TaskStatus.CANCELLED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    },
    TaskStatus.PROCESSING: {
        TaskStatus.DOWNLOADING,
        TaskStatus.CANCEL_REQUESTED,
        TaskStatus.CANCELLED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    },
    TaskStatus.CANCEL_REQUESTED: {
        TaskStatus.CANCELLED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
    },
}


def validate_transition(current: str | None, target: str) -> None:
    try:
        target_status = TaskStatus(target)
        current_status = TaskStatus(current) if current else None
    except ValueError as exc:
        raise ValueError(f"Estado de tarefa desconhecido: {exc}") from exc

    if current_status == target_status:
        return
    if target_status not in _ALLOWED_TRANSITIONS.get(current_status, set()):
        raise ValueError(
            f"Transição de tarefa inválida: {current or 'nova'} -> {target_status.value}"
        )


def is_terminal(status: str | None) -> bool:
    return status in TERMINAL_STATUSES


def persist_task_state(
    task_id: str,
    fields: dict[str, object],
    *,
    local_store,
    redis_factory,
    ttl_seconds: int,
) -> None:
    if local_store is not None:
        local_store.set_task_state(task_id, fields)
        return

    key = f"saveclip:task:{task_id}"
    mapping = {
        name: (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, (dict, list))
            else str(value)
        )
        for name, value in fields.items()
    }
    client = redis_factory()
    try:
        if "status" not in fields:
            client.hset(key, mapping=mapping)
            client.expire(key, ttl_seconds)
            return

        with client.pipeline() as pipeline:
            while True:
                try:
                    pipeline.watch(key)
                    current = pipeline.hget(key, "status")
                    validate_transition(current, str(fields["status"]))
                    pipeline.multi()
                    pipeline.hset(key, mapping=mapping)
                    pipeline.expire(key, ttl_seconds)
                    pipeline.execute()
                    return
                except WatchError:
                    continue
                finally:
                    pipeline.reset()
    finally:
        client.close()
