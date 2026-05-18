import asyncio
from pathlib import Path

from packages.aura_core.observability.run_store import RunStore
from packages.aura_core.scheduler.queues.durable_queue import DurableTaskQueue
from packages.aura_core.scheduler.queues.task_queue import Tasklet


def test_run_store_v6_migrations_and_queue_tables(tmp_path: Path):
    store = RunStore(tmp_path / "aura.sqlite3")

    status = store.migration_status()

    assert status["status"] == "success"
    assert "v6_recoverable_queue" in {row["name"] for row in status["applied"]}
    assert store.apply_migrations()["status"] == "success"


def test_durable_queue_claim_ack_and_recover(tmp_path: Path):
    async def _run():
        store = RunStore(tmp_path / "aura.sqlite3")
        queue = DurableTaskQueue(run_store=store, lease_ttl_sec=0.01)
        tasklet = Tasklet(
            task_name="demo/tasks:hello.yaml",
            cid="cid-1",
            payload={"plan_name": "demo", "task_name": "tasks:hello.yaml"},
            initial_context={"name": "Aura"},
        )

        await queue.put(tasklet)
        assert queue.qsize() == 1
        claimed = await queue.get()
        assert claimed.cid == "cid-1"
        assert queue.qsize() == 0
        assert await queue.ack("cid-1", getattr(claimed, "_queue_lease_token", None))
        assert store.queue_list(state="completed")[0]["cid"] == "cid-1"

        await queue.put(Tasklet(task_name="demo/tasks:again.yaml", cid="cid-2", payload={"plan_name": "demo"}))
        stale = await queue.get()
        assert stale.cid == "cid-2"
        result = store.queue_recover_expired_leases(now_ms=10**15)
        assert result["recovered"] == ["cid-2"]
        assert store.queue_recovery_status()["recoverable_count"] == 1

    asyncio.run(_run())


def test_run_store_queue_claim_is_single_winner_and_ack_requires_token(tmp_path: Path):
    store1 = RunStore(tmp_path / "aura.sqlite3")
    store2 = RunStore(tmp_path / "aura.sqlite3")
    store1.queue_enqueue(
        {
            "cid": "cid-atomic",
            "queue_name": "main",
            "state": "ready",
            "plan_name": "demo",
            "task_name": "tasks:hello.yaml",
            "tasklet": {"task_name": "demo/tasks:hello.yaml", "cid": "cid-atomic"},
        }
    )

    first = store1.queue_claim_ready(worker_id="worker-1")
    second = store2.queue_claim_ready(worker_id="worker-2")

    assert first is not None
    assert second is None
    assert not store2.queue_ack("cid-atomic")
    assert store1.queue_ack("cid-atomic", first["lease_token"])
    assert store1.queue_list(state="completed")[0]["cid"] == "cid-atomic"
