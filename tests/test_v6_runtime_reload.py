import asyncio
import threading

from packages.aura_core.scheduler.hot_reload_control import HotReloadControlService


class _HotReload:
    def is_enabled(self):
        return False


class _FakeScheduler:
    def __init__(self):
        self.fallback_lock = threading.RLock()
        self.running_tasks = {}
        self._running_task_meta = {}
        self.all_tasks_definitions = {"demo/tasks:hello.yaml": {}}
        self.hot_reload = _HotReload()
        self.reload_barrier = None
        self.observability = None


def test_reload_plan_reports_blocking_tasks():
    scheduler = _FakeScheduler()
    scheduler.running_tasks["cid-1"] = object()
    scheduler._running_task_meta["cid-1"] = {"plan_name": "demo", "task_name": "tasks:hello.yaml"}
    service = HotReloadControlService(scheduler)

    plan = service.plan_reload("demo")

    assert plan["status"] == "blocked"
    assert plan["blocked_by"][0]["cid"] == "cid-1"


def test_reload_apply_records_success_and_uses_barrier():
    async def _run():
        scheduler = _FakeScheduler()
        scheduler.reload_barrier = asyncio.Event()
        scheduler.reload_barrier.set()
        service = HotReloadControlService(scheduler)

        async def _fake_reload(_package_id):
            assert not scheduler.reload_barrier.is_set()
            return {"status": "success", "message": "ok"}

        service._reload_package = _fake_reload

        result = await service.apply_reload("demo", mode="package")

        assert result["status"] == "success"
        assert result["package_id"] == "demo"
        assert scheduler.reload_barrier.is_set()

    asyncio.run(_run())
