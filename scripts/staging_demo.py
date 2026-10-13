"""Persistent, named staging demo. Only the explicitly registered 20 demo chargers."""

import argparse
import asyncio
import json
import os
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.modules.identity.models import Role, User, UserRole
from src.modules.identity.security import hash_password, verify_password
from src.modules.stations.models import Station
from src.platform.audit.service import ghi_nhat_ky
from src.platform.database.session import SessionFactory, engine

ROOT = Path(os.environ.get("CSMS_DEMO_DIR", ".local/csms-staging-demo"))
STATE = ROOT / "state.json"
STOP = ROOT / "stop.request"
BASE = "https://csms-staging.daominhtam2k6.id.vn/api/v1"
OCPP = "wss://csms-staging.daominhtam2k6.id.vn"
MARKER = "Trạm ảo dành riêng cho demo staging CSMS; không phải điểm sạc thực tế."


async def api(client, method, path, **kwargs):
    r = await client.request(method, path, **kwargs)
    if not r.is_success:
        raise RuntimeError(
            f"{method} {path.split('?')[0]} failed ({r.status_code}); inspect demo resources, no overwrite"
        )
    return r.json() if r.content else None


async def login(client, account):
    await api(
        client,
        "POST",
        "/auth/login",
        json={"email": account["email"], "password": account["password"]},
    )


async def seed():
    accounts = json.loads((ROOT / "accounts.json").read_text(encoding="utf-8"))
    members = {a["key"]: a for a in accounts}
    # The namespace administrator is the only bootstrap exception. All remaining
    # accounts, cards, stations, tariffs and receipts use the application's APIs.
    a = members["admin"]
    async with SessionFactory() as db, db.begin():
        await db.execute(text("SELECT pg_advisory_xact_lock(610013)"))
        user = await db.scalar(select(User).where(User.email == a["email"]))
        if user is None:
            user = User(
                email=a["email"],
                password_hash=hash_password(a["password"]),
                status="active",
            )
            db.add(user)
            await db.flush()
            rid = await db.scalar(select(Role.id).where(Role.code == "admin"))
            if rid is None:
                raise RuntimeError("Missing migrated admin role")
            db.add(UserRole(user_id=user.id, role_id=rid))
            await db.flush()
            await ghi_nhat_ky(
                db,
                actor_id=user.id,
                action="staging_demo.account_bootstrap",
                object_type="user",
                object_id=str(user.id),
                data={"namespace": "csms-staging-demo"},
                actor_roles=["admin"],
            )
        roles = set(
            await db.scalars(
                select(Role.code).join(UserRole).where(UserRole.user_id == user.id)
            )
        )
        if (
            user.status != "active"
            or roles != {"admin"}
            or not verify_password(user.password_hash, a["password"])
        ):
            raise RuntimeError(
                "Demo administrator changed; refusing to reset credentials/roles"
            )
    async with httpx.AsyncClient(base_url=BASE, timeout=40) as admin:
        await login(admin, a)
        for member in accounts:
            data = await api(
                admin, "GET", "/admin/accounts", params={"search": member["email"]}
            )
            row = next(
                (r for r in data["items"] if r["email"] == member["email"]), None
            )
            if row is None:
                row = await api(
                    admin,
                    "POST",
                    "/admin/accounts",
                    json={
                        "email": member["email"],
                        "password": member["password"],
                        "roles": [member["role"]],
                    },
                )
            if row["status"] != "active" or row["roles"] != [member["role"]]:
                raise RuntimeError(
                    "Demo account ownership/status changed; no overwrite"
                )
            member["id"] = row["id"]
            if member["role"] == "driver":
                receipt = "STAGING-DEMO-INITIAL-" + member["key"]
                async with SessionFactory() as db:
                    funded = await db.scalar(
                        text(
                            "SELECT id FROM wallet_ledger WHERE entry_type='manual_topup' AND reference_id=:receipt"
                        ),
                        {"receipt": receipt},
                    )
                if funded is None:
                    await api(
                        admin,
                        "POST",
                        f"/admin/drivers/{row['id']}/wallet/manual-topups",
                        json={"amount_vnd": 500000, "receipt_code": receipt},
                    )
    chargers = []
    stations = []
    for key, place, prefix, lat, lon in [
        ("owner", "Thảo Điền", "TD", 10.8032, 106.7325),
        ("owner2", "Bình Thạnh", "BT", 10.8132, 106.7125),
    ]:
        owner_account = members[key]
        name = "CSMS Demo · " + place
        async with httpx.AsyncClient(base_url=BASE, timeout=40) as owner:
            await login(owner, owner_account)
            data = await api(owner, "GET", "/stations", params={"page_size": 100})
            station = next((s for s in data["items"] if s["name"] == name), None)
            if station is None:
                station = await api(
                    owner,
                    "POST",
                    "/stations",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={
                        "name": name,
                        "address": MARKER,
                        "latitude": lat,
                        "longitude": lon,
                        "timezone": "Asia/Ho_Chi_Minh",
                    },
                )
            async with SessionFactory() as db, db.begin():
                row = await db.scalar(
                    select(Station)
                    .where(
                        Station.id == UUID(station["id"]),
                        Station.owner_id == UUID(owner_account["id"]),
                        Station.name == name,
                    )
                    .with_for_update()
                )
                if (
                    row is None
                    or row.address != MARKER
                    or row.status not in {"active", "inactive"}
                    or row.archived_at is not None
                ):
                    raise RuntimeError(
                        "Named demo station changed; refusing to activate: "
                        + str(
                            {
                                "found": row is not None,
                                "address": row.address if row else None,
                                "expected_address": MARKER,
                                "status": row.status if row else None,
                                "archived": str(row.archived_at) if row else None,
                            }
                        )
                    )
                if row.status == "inactive":
                    row.status = "active"
                    await ghi_nhat_ky(
                        db,
                        actor_id=UUID(members["admin"]["id"]),
                        action="staging_demo.station_activated",
                        object_type="station",
                        object_id=str(row.id),
                        data={"namespace": "csms-staging-demo"},
                        actor_roles=["admin"],
                    )
            context = await api(
                owner, "GET", f"/owner/stations/{station['id']}/tariffs/context"
            )
            if not context["has_versions"]:
                await api(
                    owner,
                    "POST",
                    f"/owner/stations/{station['id']}/tariffs",
                    json={
                        "effective_from": context["today"],
                        "energy_rate_vnd_per_kwh": 3000,
                        "idle_rate_vnd_per_minute": 500,
                        "grace_minutes": 2,
                    },
                )
            elif context["current"] is None:
                raise RuntimeError(
                    "Demo station has no effective tariff; inspect instead of changing history"
                )
            # Cards let the same drivers use either demo station through the UI.
            cards = await api(owner, "GET", "/charging/cards")
            for driver_key in ["driver", "driver2"]:
                tag = (
                    "STG-"
                    + prefix
                    + "-"
                    + ("DRIVER1" if driver_key == "driver" else "DRIVER2")
                )
                if not any(
                    c["tag_tail"] == tag[-4:]
                    and c["driver_email"] == members[driver_key]["email"]
                    for c in cards
                ):
                    await api(
                        owner,
                        "POST",
                        "/charging/cards",
                        json={
                            "id_tag": tag,
                            "driver_email": members[driver_key]["email"],
                        },
                    )
            data = await api(
                owner,
                "GET",
                f"/stations/{station['id']}/charge-points",
                params={"page_size": 100},
            )
            for n in range(1, 11):
                code = f"DEMO-STG-{prefix}-{n:03d}"
                display = f"{place} — Trụ {n:02d}"
                charger = next((c for c in data["items"] if c["code"] == code), None)
                if charger is None:
                    charger = await api(
                        owner,
                        "POST",
                        f"/stations/{station['id']}/charge-points",
                        json={
                            "code": code,
                            "name": display,
                            "connector_count": 4,
                            "connectors": [
                                {
                                    "connector_number": c,
                                    "connector_type": "Type 2",
                                    "current_type": "AC",
                                    "max_power_kw": 22,
                                    "voltage": 230,
                                    "amperage": 32,
                                }
                                for c in range(1, 5)
                            ],
                        },
                    )
                if charger["name"] != display:
                    raise RuntimeError("Demo charger name changed; no overwrite")
                chargers.append(
                    {
                        "code": code,
                        "name": display,
                        "id": charger["id"],
                        "station_id": station["id"],
                        "fault_connector": None,
                        "charging": False,
                    }
                )
            stations.append(
                {
                    "id": station["id"],
                    "name": name,
                    "owner_email": owner_account["email"],
                }
            )
    STATE.write_text(
        json.dumps(
            {
                "namespace": "csms-staging-demo",
                "stations": stations,
                "chargers": chargers,
                "seeded_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        "Prepared 2 named stations, 20 chargers, 80 connectors; existing wallet receipts retained.",
        flush=True,
    )
    await engine.dispose()


class Charger:
    def __init__(self, config):
        self.config = config
        self.transactions = {}
        self.meters = {c: 1000 for c in range(1, 5)}
        self.starting = set()
        self.pending = {}
        self.tasks = set()
        self.lock = asyncio.Lock()
        self.online = False
        self.counter = 0
        self.telemetry = {}
        self.awaiting_unplug = {}

    async def call(self, action, payload):
        uid = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[uid] = future
        try:
            await self.socket.send(json.dumps([2, uid, action, payload]))
            return await asyncio.wait_for(future, 20)
        finally:
            self.pending.pop(uid, None)

    async def status(self, connector, status):
        await self.call(
            "StatusNotification",
            {
                "connectorId": connector,
                "status": status,
                "errorCode": "GroundFailure" if status == "Faulted" else "NoError",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def start(self, tag, connector=1):
        try:
            async with self.lock:
                if (
                    connector in self.transactions
                    or connector == self.config["fault_connector"]
                ):
                    return
                result = await self.call(
                    "StartTransaction",
                    {
                        "connectorId": connector,
                        "idTag": tag,
                        "meterStart": self.meters[connector],
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                self.transactions[connector] = result["transactionId"]
                if result.get("idTagInfo", {}).get("status") != "Accepted":
                    await self.stop_connector(connector, "DeAuthorized")
                    return
                self.telemetry.pop(connector, None)
                await self.status(connector, "Charging")
        finally:
            self.starting.discard(connector)

    async def stop_connector(self, connector, reason):
        transaction = self.transactions.get(connector)
        if transaction is None:
            return
        await self.call(
            "StopTransaction",
            {
                "transactionId": transaction,
                "meterStop": self.meters[connector],
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
        del self.transactions[connector]
        if reason == "Remote":
            self.awaiting_unplug[connector] = transaction
            await self.status(connector, "Finishing")
        else:
            self.awaiting_unplug.pop(connector, None)
            await self.status(connector, "Available")

    async def stop(self, reason="EVDisconnected", connector=None):
        async with self.lock:
            for number in list(self.transactions) if connector is None else [connector]:
                await self.stop_connector(number, reason)

    async def receive(self):
        async for raw in self.socket:
            frame = json.loads(raw)
            if frame[0] == 2 and frame[2] == "DataTransfer":
                payload = frame[3]
                accepted = False
                number = None
                try:
                    data = json.loads(payload.get("data", "{}"))
                    number = data.get("connectorId")
                    transaction = data.get("transactionId")
                    accepted = (
                        self.online
                        and payload.get("vendorId") == "CSMS-DEMO"
                        and payload.get("messageId") == "Unplug"
                        and type(number) is int
                        and type(transaction) is int
                        and (
                            self.transactions.get(number) == transaction
                            or self.awaiting_unplug.get(number) == transaction
                        )
                    )
                except (ValueError, TypeError, AttributeError):
                    pass
                await self.socket.send(
                    json.dumps(
                        [
                            3,
                            frame[1],
                            {"status": "Accepted" if accepted else "Rejected"},
                        ]
                    )
                )
                if accepted:
                    task = asyncio.create_task(self.unplug(number))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                continue
            if frame[0] in {3, 4}:
                future = self.pending.get(frame[1])
                if future is not None and not future.done():
                    if frame[0] == 3:
                        future.set_result(frame[2])
                    else:
                        future.set_exception(
                            RuntimeError(f"OCPP CALLERROR: {frame[2]}")
                        )
            elif frame[0] == 2:
                action, payload = frame[2:4]
                connector = payload.get("connectorId")
                stop_connector = next(
                    (
                        c
                        for c, tx in self.transactions.items()
                        if tx == payload.get("transactionId")
                    ),
                    None,
                )
                accepted = (
                    action == "Reset"
                    or (
                        action == "RemoteStopTransaction" and stop_connector is not None
                    )
                    or (
                        action == "RemoteStartTransaction"
                        and type(connector) is int
                        and connector in self.meters
                        and connector != self.config["fault_connector"]
                        and connector not in self.transactions
                        and connector not in self.starting
                    )
                )
                if accepted and action == "RemoteStartTransaction":
                    self.starting.add(connector)
                await self.socket.send(
                    json.dumps(
                        [
                            3,
                            frame[1],
                            {"status": "Accepted" if accepted else "Rejected"},
                        ]
                    )
                )
                if accepted and action != "Reset":
                    task = asyncio.create_task(
                        self.stop("Remote", stop_connector)
                        if action == "RemoteStopTransaction"
                        else self.start(payload["idTag"], connector)
                    )
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                print(
                    f"{self.config['code']}: {action} {'Accepted' if accepted else 'Rejected'}",
                    flush=True,
                )

    async def unplug(self, number):
        async with self.lock:
            if number in self.transactions:
                await self.stop_connector(number, "EVDisconnected")
            elif number in self.awaiting_unplug:
                await self.status(number, "Available")
                self.awaiting_unplug.pop(number, None)

    async def meter_values(self):
        async with self.lock:
            for connector, transaction in list(self.transactions.items()):
                from scripts.ocpp_control_simulator import ConnectorState, meter_samples

                state = self.telemetry.setdefault(
                    connector, ConnectorState(meter_wh=self.meters[connector])
                )
                now = monotonic()
                elapsed = (
                    now - state.last_meter_at if state.last_meter_at is not None else 10
                )
                state.last_meter_at = now
                values = meter_samples(state, elapsed)
                self.meters[connector] = state.meter_wh
                await self.call(
                    "MeterValues",
                    {
                        "connectorId": connector,
                        "transactionId": transaction,
                        "meterValue": [
                            {
                                "timestamp": datetime.now(UTC).isoformat(),
                                "sampledValue": values,
                            }
                        ],
                    },
                )
            self.counter += 1

    async def run(self):
        from scripts.ocpp_control_simulator import load_connectors

        registered = await load_connectors(self.config["code"], dispose_engine=False)
        self.meters = {n: state.meter_wh for n, state in registered.items()}
        self.transactions = {
            n: state.transaction_id
            for n, state in registered.items()
            if state.transaction_id is not None
        }
        async with SessionFactory() as db:
            waiting = (
                await db.execute(
                    text("""
                SELECT c.connector_number, s.id FROM charging_sessions s
                JOIN connectors c ON c.id = s.connector_id
                JOIN charge_points p ON p.id = c.charge_point_id
                WHERE lower(p.code) = :code AND s.ended_at IS NOT NULL
                  AND s.connector_released_at IS NULL AND s.billing_lifecycle_version = 1
            """),
                    {"code": self.config["code"].lower()},
                )
            ).all()
        self.awaiting_unplug = {number: tx for number, tx in waiting}
        async with connect(
            f"{OCPP}/ocpp/{self.config['code']}", subprotocols=["ocpp1.6"]
        ) as self.socket:
            receiver = asyncio.create_task(self.receive())
            try:
                result = await self.call(
                    "BootNotification",
                    {
                        "chargePointVendor": "CSMS Demo",
                        "chargePointModel": "Live UI Demo",
                        "firmwareVersion": "demo-1",
                    },
                )
                if result.get("status") != "Accepted":
                    raise RuntimeError("Boot rejected")
                await self.status(0, "Available")
                for c in self.meters:
                    await self.status(
                        c,
                        "Faulted"
                        if c == self.config["fault_connector"]
                        else "Charging"
                        if c in self.transactions
                        else "Finishing"
                        if c in self.awaiting_unplug
                        else "Available",
                    )
                if receiver.done():
                    await receiver
                self.online = True
                print(
                    f"{self.config['code']} online; transactions {self.transactions or '-'}",
                    flush=True,
                )
                while not STOP.exists():
                    await self.call("Heartbeat", {})
                    await self.meter_values()
                    for _ in range(10):
                        if STOP.exists():
                            break
                        await asyncio.sleep(1)
                if self.tasks:
                    await asyncio.gather(*self.tasks)
                await self.stop()
                for number in list(self.awaiting_unplug):
                    await self.unplug(number)
            finally:
                self.online = False
                receiver.cancel()
                await asyncio.gather(receiver, *self.tasks, return_exceptions=True)


async def live():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    if state["namespace"] != "csms-staging-demo" or len(state["chargers"]) != 20:
        raise RuntimeError("Invalid demo manifest")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop():
        STOP.touch()
        stop.set()

    for sig in [signal.SIGTERM, signal.SIGINT]:
        loop.add_signal_handler(sig, request_stop)
    chargers = [Charger(c) for c in state["chargers"]]

    async def worker(charger):
        while not STOP.exists():
            try:
                await charger.run()
            except (
                OSError,
                RuntimeError,
                TimeoutError,
                SQLAlchemyError,
                ConnectionClosed,
            ) as error:
                charger.online = False
                print(
                    f"{charger.config['code']}: disconnected ({type(error).__name__}: {error}), reconnect in 5s",
                    flush=True,
                )
                try:
                    await asyncio.wait_for(stop.wait(), 5)
                except TimeoutError:
                    pass

    async def progress():
        while not STOP.exists():
            online = [c.config["code"] for c in chargers if c.online]
            (ROOT / "runtime.json").write_text(
                json.dumps(
                    {
                        "online": len(online),
                        "total": 20,
                        "codes": online,
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            await asyncio.sleep(1)
        stop.set()

    await asyncio.gather(*(worker(c) for c in chargers), progress())
    (ROOT / "runtime.json").write_text(
        json.dumps(
            {"online": 0, "total": 20, "stopped_at": datetime.now(UTC).isoformat()}
        ),
        encoding="utf-8",
    )
    await engine.dispose()
    print(
        "Graceful stop: active demo sessions stopped, financial history retained.",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["seed", "live"])
    args = parser.parse_args()
    try:
        asyncio.run(seed() if args.action == "seed" else live())
    except (
        OSError,
        RuntimeError,
        TimeoutError,
        SQLAlchemyError,
        ConnectionClosed,
    ) as error:
        print(
            f"Demo failed: {type(error).__name__}; inspect demo resources", flush=True
        )
        raise SystemExit(1)
