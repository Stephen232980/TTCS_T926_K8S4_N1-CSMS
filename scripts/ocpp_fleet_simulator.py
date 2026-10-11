"""Automatically connect registered local chargers, including newly created ones."""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Collection
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocpp_control_simulator import load_connectors, run


async def discover_codes() -> set[str]:
    from sqlalchemy import text

    from src.platform.database.session import SessionFactory

    async with SessionFactory() as session:
        return set(
            await session.scalars(
                text("""
                    SELECT p.code FROM charge_points p
                    JOIN stations s ON s.id = p.station_id
                    WHERE p.archived_at IS NULL AND s.archived_at IS NULL
                      AND s.status != 'blocked'
                      AND EXISTS (SELECT 1 FROM connectors c
                                  WHERE c.charge_point_id = p.id
                                    AND c.archived_at IS NULL)
                """)
            )
        )


async def simulate(url: str, code: str, stop: asyncio.Event) -> None:
    connectors = await load_connectors(code, dispose_engine=False)
    print(f"Auto-connect {code}: connectors {sorted(connectors)}", flush=True)
    await run(
        url, code, None, "Accepted", False, connectors=connectors, stop_event=stop
    )


async def watch_fleet(
    url: str,
    stop: asyncio.Event,
    *,
    excluded: Collection[str] = (),
    interval: float = 5,
    discover: Callable[[], Awaitable[set[str]]] = discover_codes,
    runner: Callable[[str, str, asyncio.Event], Awaitable[None]] = simulate,
) -> None:
    """One task per charger; retry failures without interrupting other chargers."""
    tasks: dict[str, tuple[asyncio.Task[None], asyncio.Event]] = {}
    excluded_codes = {code.strip().lower() for code in excluded}
    try:
        while not stop.is_set():
            try:
                codes = await discover()
            except (SQLAlchemyError, OSError) as error:
                print(
                    f"Fleet discovery failed ({type(error).__name__}); retrying.",
                    flush=True,
                )
            else:
                codes = {c for c in codes if c.strip().lower() not in excluded_codes}
                for code, (task, signal) in list(tasks.items()):
                    if task.done():
                        if not task.cancelled() and task.exception() is not None:
                            print(
                                f"{code} disconnected; retrying next scan.", flush=True
                            )
                        del tasks[code]
                    elif code not in codes:
                        signal.set()
                for code in sorted(codes - tasks.keys()):
                    signal = asyncio.Event()
                    tasks[code] = (
                        asyncio.create_task(runner(url, code, signal)),
                        signal,
                    )
            try:
                await asyncio.wait_for(stop.wait(), interval)
            except TimeoutError:
                pass
    finally:
        for _, signal in tasks.values():
            signal.set()
        if tasks:
            group = asyncio.gather(
                *(task for task, _ in tasks.values()), return_exceptions=True
            )
            try:
                await asyncio.wait_for(group, 35)
            except TimeoutError:
                print(
                    "Fleet shutdown timed out; inspect unfinished sessions.", flush=True
                )


async def main(args: argparse.Namespace) -> None:
    stop = asyncio.Event()
    try:
        await watch_fleet(args.url, stop, interval=args.scan_seconds)
    finally:
        from src.platform.database.session import engine

        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8001")
    parser.add_argument("--scan-seconds", type=float, default=5)
    args = parser.parse_args()
    if args.scan_seconds <= 0:
        parser.error("--scan-seconds must be positive")
    try:
        if sys.platform == "win32":
            import selectors

            asyncio.run(
                main(args),
                loop_factory=lambda: asyncio.SelectorEventLoop(
                    selectors.SelectSelector()
                ),
            )
        else:
            asyncio.run(main(args))
    except KeyboardInterrupt:
        print("Fleet stopped.")
