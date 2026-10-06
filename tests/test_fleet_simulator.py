import asyncio

from scripts.ocpp_fleet_simulator import watch_fleet


async def test_fleet_discovers_new_chargers_and_stops_removed_ones():
    codes = {"EXISTING", "MANAGED-BY-DEMO"}
    started = []
    stopped = []
    stop = asyncio.Event()

    async def discover():
        return set(codes)

    async def runner(url, code, signal):
        started.append(code)
        await signal.wait()
        stopped.append(code)

    async def until(predicate):
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0.01)

    task = asyncio.create_task(
        watch_fleet(
            "ws://local",
            stop,
            excluded=["managed-by-demo"],
            interval=0.01,
            discover=discover,
            runner=runner,
        )
    )
    try:
        await until(lambda: "EXISTING" in started)
        codes.add("NEW")
        await until(lambda: "NEW" in started)
        await asyncio.sleep(0.04)
        assert started.count("NEW") == 1
        assert "MANAGED-BY-DEMO" not in started
        codes.remove("EXISTING")
        await until(lambda: "EXISTING" in stopped)
        assert "NEW" not in stopped
    finally:
        stop.set()
        await task
    assert "NEW" in stopped
