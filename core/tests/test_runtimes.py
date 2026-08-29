"""Runtime Manager tests: one runtime per bot, lifecycle, isolation."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from jadabot.runtimes import (
    RuntimeManager,
    RuntimeRegistry,
    RuntimeSpawner,
    RuntimeState,
)


class FakeSpawner(RuntimeSpawner):
    """Records spawns/terminations without starting real processes."""

    def __init__(self) -> None:
        self.spawned: list[dict] = []
        self.terminated: list[object] = []
        self.alive: dict[int, bool] = {}
        self._next = 0

    def spawn(self, bot_id: str, workdir: Path, port: int, gateway_url: str, bot_token: str) -> object:
        handle = self._next
        self._next += 1
        self.spawned.append(
            {
                "handle": handle,
                "bot_id": bot_id,
                "workdir": Path(workdir),
                "port": port,
                "gateway_url": gateway_url,
                "bot_token": bot_token,
            }
        )
        self.alive[handle] = True
        return handle

    def terminate(self, handle: object) -> None:
        self.terminated.append(handle)
        self.alive[handle] = False  # type: ignore[index]

    def is_alive(self, handle: object) -> bool:
        return self.alive.get(handle, False)  # type: ignore[arg-type]


@pytest.fixture
def spawner() -> FakeSpawner:
    return FakeSpawner()


@pytest.fixture
def manager(spawner: FakeSpawner, tmp_path: Path) -> RuntimeManager:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    return RuntimeManager(
        spawner,
        RuntimeRegistry(),
        runtimes_root=tmp_path / "runtimes",
        gateway_url="http://gateway.test",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_start_provisions_isolated_workdirs(manager: RuntimeManager, spawner: FakeSpawner) -> None:
    info_a = manager.start("bot-a", "token-a")
    info_b = manager.start("bot-b", "token-b")

    assert info_a.workdir != info_b.workdir
    assert (Path(info_a.workdir) / "data").is_dir()
    assert (Path(info_a.workdir) / "skills").is_dir()
    assert info_a.endpoint != info_b.endpoint
    assert spawner.spawned[0]["bot_token"] == "token-a"
    assert spawner.spawned[0]["gateway_url"] == "http://gateway.test"


def test_one_runtime_per_bot(manager: RuntimeManager, spawner: FakeSpawner) -> None:
    first = manager.start("bot-a", "token-a")
    second = manager.start("bot-a", "token-a")
    assert first is second
    assert len(spawner.spawned) == 1


def test_registry_endpoint_lookup(manager: RuntimeManager) -> None:
    info = manager.start("bot-a", "token-a")
    assert manager.registry.endpoint_for("bot-a") == info.endpoint
    with pytest.raises(KeyError):
        manager.registry.endpoint_for("bot-unknown")


def test_stop_and_purge(manager: RuntimeManager, spawner: FakeSpawner) -> None:
    info = manager.start("bot-a", "token-a")
    workdir = Path(info.workdir)
    assert workdir.is_dir()
    manager.stop("bot-a", purge=True)
    assert manager.registry.get("bot-a") is None
    assert spawner.terminated == [0]
    assert not workdir.exists()


async def test_health_check_states(manager: RuntimeManager, spawner: FakeSpawner) -> None:
    manager.start("bot-a", "token-a")
    assert await manager.health_check("bot-a") is RuntimeState.RUNNING

    spawner.alive[0] = False  # simulate a crash
    assert await manager.health_check("bot-a") is RuntimeState.STOPPED
    assert await manager.health_check("bot-unknown") is RuntimeState.STOPPED


async def test_ensure_running_restarts_crashed_runtime(
    manager: RuntimeManager, spawner: FakeSpawner
) -> None:
    manager.start("bot-a", "token-a")
    spawner.alive[0] = False  # simulate a crash
    info = await manager.ensure_running("bot-a")
    assert len(spawner.spawned) == 2
    assert spawner.spawned[1]["bot_token"] == "token-a"
    assert manager.registry.endpoint_for("bot-a") == info.endpoint
