import asyncio

import pytest

from stumble_radio.network import internet_available, retry_delay


def test_retry_backoff_is_bounded_forever():
    assert [retry_delay(n) for n in range(1, 9)] == [1, 2, 4, 8, 16, 30, 30, 30]
    assert retry_delay(10**9) == 30


async def test_reachability_accepts_either_target_and_closes_socket(monkeypatch):
    writers = []

    class Writer:
        closed = False

        def close(self):
            self.closed = True

        async def wait_closed(self):
            pass

    async def connect(host, port):
        if host == "station.test":
            raise OSError("station unavailable")
        writer = Writer()
        writers.append(writer)
        return None, writer

    monkeypatch.setattr("stumble_radio.network.asyncio.open_connection", connect)
    assert await internet_available("https://station.test/live")
    assert writers and all(writer.closed for writer in writers)


async def test_network_unavailable_when_both_targets_fail(monkeypatch):
    async def connect(host, port):
        raise OSError("network is unreachable")

    monkeypatch.setattr("stumble_radio.network.asyncio.open_connection", connect)
    assert not await internet_available("https://station.test/live")


async def test_slow_probe_is_cancelled_after_another_succeeds(monkeypatch):
    cancelled = asyncio.Event()

    class Writer:
        def close(self):
            pass

        async def wait_closed(self):
            pass

    async def connect(host, port):
        if host == "station.test":
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return None, Writer()

    monkeypatch.setattr("stumble_radio.network.asyncio.open_connection", connect)
    assert await internet_available("https://station.test/live")
    assert cancelled.is_set()


async def test_cancelling_monitor_cleans_up_all_probes(monkeypatch):
    started = asyncio.Event()
    cancelled = []

    async def connect(host, port):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(host)

    monkeypatch.setattr("stumble_radio.network.asyncio.open_connection", connect)
    monitor = asyncio.create_task(internet_available("https://station.test/live"))
    await started.wait()
    monitor.cancel()
    with pytest.raises(asyncio.CancelledError):
        await monitor
    assert len(cancelled) == 2
