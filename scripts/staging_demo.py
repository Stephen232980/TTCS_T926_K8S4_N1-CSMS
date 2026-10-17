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
                        json={
                            "amount_vnd": 500000,
                            "reason": "Staging demo funding",
                            "receipt_code": receipt,
                        },
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
        self.reservations = {}
        self.remote_configuration = {
            "HeartbeatInterval": 30,
            "MeterValueSampleInterval": 10,
        }
        path = ROOT / (self.config["code"] + ".configuration.json")
        if path.exists():
            try:
                saved = json.loads(path.read_text())
            except (OSError, ValueError):
                saved = {}
            if not isinstance(saved, dict):
                saved = {}
            for key, (low, high) in {
                "HeartbeatInterval": (30, 600),
                "MeterValueSampleInterval": (5, 300),
            }.items():
                if type(saved.get(key)) is int and low <= saved[key] <= high:
                    self.remote_configuration[key] = saved[key]

    def power_state(self, number):
        from scripts.ocpp_control_simulator import ConnectorState

        state = self.telemetry.setdefault(
            number, ConnectorState(meter_wh=self.meters[number])
        )
        state.transaction_id = self.transactions.get(number)
        return state

    def integrate_power(self, number):
        from scripts.ocpp_control_simulator import meter_samples

        state = self.power_state(number)
        if state.transaction_id is not None and state.last_meter_at is not None:
            tick = monotonic()
            meter_samples(state, max(0, tick - state.last_meter_at))
            state.last_meter_at = tick
            self.meters[number] = state.meter_wh

    def save_power_profiles(self):
        path = ROOT / (self.config["code"] + ".power.private.json")
        data = {
            str(n): {
                key: getattr(self.power_state(n), key)
                for key in (
                    "default_limit_w",
                    "default_profile_id",
                    "transaction_id",
                    "transaction_limit_w",
                    "transaction_profile_id",
                )
            }
            for n in self.meters
        }
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf8") as stream:
            os.chmod(temporary, 0o600)
            json.dump({"version": 1, "connectors": data}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)

    def load_power_profiles(self):
        path = ROOT / (self.config["code"] + ".power.private.json")
        if not path.exists():
            if self.transactions:
                raise RuntimeError(
                    "Missing profiles for open demo sessions; refusing to boot"
                )
            return
        try:
            stored = json.loads(path.read_text(encoding="utf8"))
        except (ValueError, UnicodeError) as error:
            raise RuntimeError(
                "Invalid persisted demo power profiles; refusing to boot"
            ) from error
        if (
            not isinstance(stored, dict)
            or type(stored.get("version")) is not int
            or stored.get("version") != 1
            or not isinstance(stored.get("connectors"), dict)
        ):
            raise RuntimeError(
                "Invalid persisted demo power profiles; refusing to boot"
            )
        if set(stored["connectors"]) != {str(n) for n in self.meters}:
            raise RuntimeError("Incomplete persisted demo connectors; refusing to boot")
        for key, prior in stored["connectors"].items():
            number = int(key)
            if number not in self.meters or not isinstance(prior, dict):
                raise RuntimeError(
                    "Persisted power connectors changed; refusing to boot"
                )
            if set(prior) != {
                "default_limit_w",
                "default_profile_id",
                "transaction_id",
                "transaction_limit_w",
                "transaction_profile_id",
            }:
                raise RuntimeError(
                    "Incomplete persisted demo power fields; refusing to boot"
                )
            for field in (
                "default_limit_w",
                "default_profile_id",
                "transaction_id",
                "transaction_limit_w",
                "transaction_profile_id",
            ):
                value = prior.get(field)
                if value is not None and (type(value) is not int or value < 0):
                    raise RuntimeError(
                        "Invalid persisted demo power value; refusing to boot"
                    )
            for prefix in ("default", "transaction"):
                if (prior.get(prefix + "_limit_w") is None) != (
                    prior.get(prefix + "_profile_id") is None
                ):
                    raise RuntimeError(
                        "Incomplete persisted demo power profile; refusing to boot"
                    )
            state = self.power_state(number)
            state.default_limit_w = prior.get("default_limit_w")
            state.default_profile_id = prior.get("default_profile_id")
            if (
                state.transaction_id is not None
                and prior.get("transaction_id") == state.transaction_id
            ):
                state.transaction_limit_w = prior.get("transaction_limit_w")
                state.transaction_profile_id = prior.get("transaction_profile_id")

    def power_command(self, action, payload):
        """Only the constant, indefinite W profiles emitted by the CSMS worker."""
        if not isinstance(payload, dict):
            return {"status": "Rejected"}
        number = payload.get("connectorId")
        if action == "GetCompositeSchedule":
            duration = payload.get("duration")
            if (
                type(number) is not int
                or number not in self.meters
                or type(duration) is not int
                or not 0 < duration <= 86400
                or payload.get("chargingRateUnit", "W") != "W"
            ):
                return {"status": "Rejected"}
            limit = self.power_state(number).offered_watts
            return {
                "status": "Accepted",
                "connectorId": number,
                "scheduleStart": datetime.now(UTC).isoformat(),
                "chargingSchedule": {
                    "duration": duration,
                    "chargingRateUnit": "W",
                    "chargingSchedulePeriod": [
                        {
                            "startPeriod": 0,
                            "limit": limit if limit is not None else 7920,
                        }
                    ],
                },
            }
        updates = []
        if action == "SetChargingProfile":
            details = payload.get("csChargingProfiles")
            if (
                type(number) is not int
                or number not in self.meters
                or not isinstance(details, dict)
            ):
                return {"status": "Rejected"}
            schedule = details.get("chargingSchedule")
            if not isinstance(schedule, dict):
                return {"status": "Rejected"}
            periods = schedule.get("chargingSchedulePeriod")
            if (
                not isinstance(periods, list)
                or len(periods) != 1
                or not isinstance(periods[0], dict)
                or type(periods[0].get("startPeriod")) is not int
                or periods[0]["startPeriod"] != 0
                or type(periods[0].get("limit")) is not int
                or periods[0]["limit"] < 0
                or schedule.get("chargingRateUnit") != "W"
                or any(
                    key in schedule
                    for key in ("duration", "startSchedule", "minChargingRate")
                )
                or details.get("chargingProfileKind") != "Absolute"
                or any(
                    key in details for key in ("validFrom", "validTo", "recurrencyKind")
                )
                or type(details.get("chargingProfileId")) is not int
                or details["chargingProfileId"] < 0
                or type(details.get("stackLevel")) is not int
            ):
                return {"status": "Rejected"}
            state = self.power_state(number)
            purpose = details.get("chargingProfilePurpose")
            if (
                purpose == "TxDefaultProfile"
                and details["stackLevel"] == 0
                and "transactionId" not in details
            ):
                prefix = "default"
            elif (
                purpose == "TxProfile"
                and details["stackLevel"] == 1
                and type(details.get("transactionId")) is int
                and state.transaction_id is not None
                and details["transactionId"] == state.transaction_id
            ):
                prefix = "transaction"
            else:
                return {"status": "Rejected"}
            updates = [
                (number, prefix, periods[0]["limit"], details["chargingProfileId"])
            ]
        elif action == "ClearChargingProfile":
            for key in ("id", "connectorId", "stackLevel"):
                if key in payload and (
                    type(payload[key]) is not int or payload[key] < 0
                ):
                    return {"status": "Unknown"}
            if "chargingProfilePurpose" in payload and payload[
                "chargingProfilePurpose"
            ] not in {"TxDefaultProfile", "TxProfile"}:
                return {"status": "Unknown"}
            for n in self.meters:
                if "connectorId" in payload and payload["connectorId"] != n:
                    continue
                state = self.power_state(n)
                for prefix, purpose, stack in (
                    ("default", "TxDefaultProfile", 0),
                    ("transaction", "TxProfile", 1),
                ):
                    profile_id = getattr(state, prefix + "_profile_id")
                    if (
                        profile_id is not None
                        and ("id" not in payload or payload["id"] == profile_id)
                        and (
                            "stackLevel" not in payload
                            or payload["stackLevel"] == stack
                        )
                        and (
                            "chargingProfilePurpose" not in payload
                            or payload["chargingProfilePurpose"] == purpose
                        )
                    ):
                        updates.append((n, prefix, None, None))
            if not updates:
                return {"status": "Unknown"}
        else:
            return {"status": "Rejected"}
        before = []
        for n, prefix, limit, profile_id in updates:
            self.integrate_power(n)
            state = self.power_state(n)
            before.append(
                (
                    state,
                    prefix,
                    getattr(state, prefix + "_limit_w"),
                    getattr(state, prefix + "_profile_id"),
                )
            )
            setattr(state, prefix + "_limit_w", limit)
            setattr(state, prefix + "_profile_id", profile_id)
        try:
            self.save_power_profiles()
        except OSError:
            for state, prefix, limit, profile_id in before:
                setattr(state, prefix + "_limit_w", limit)
                setattr(state, prefix + "_profile_id", profile_id)
            return {
                "status": "Rejected" if action == "SetChargingProfile" else "Unknown"
            }
        return {"status": "Accepted"}

    def save_reservations(self):
        path = ROOT / (self.config["code"] + ".reservations.private.json")
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(self.reservations, stream)
        temporary.replace(path)

    def reservation_for(self, connector):
        reservation = self.reservations.get(connector)
        if reservation and datetime.fromisoformat(
            reservation["expiryDate"]
        ) <= datetime.now(UTC):
            del self.reservations[connector]
            self.save_reservations()
            return None
        return reservation

    def schedule_status(self, connector, status):
        task = asyncio.create_task(self.status(connector, status))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def reservation_command(self, action, payload):
        if action == "ChangeConfiguration":
            key, value = payload.get("key"), payload.get("value")
            limits = {
                "HeartbeatInterval": (30, 600),
                "MeterValueSampleInterval": (5, 300),
            }
            if key not in limits:
                return {"status": "NotSupported"}
            if (
                not isinstance(value, str)
                or len(value) > 3
                or not value.isascii()
                or not value.isdigit()
            ):
                return {"status": "Rejected"}
            number = int(value)
            low, high = limits[key]
            if not low <= number <= high:
                return {"status": "Rejected"}
            updated = {**self.remote_configuration, key: number}
            path = ROOT / (self.config["code"] + ".configuration.json")
            tmp = path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(updated))
                tmp.chmod(0o600)
                tmp.replace(path)
            except OSError:
                return {"status": "Rejected"}
            self.remote_configuration = updated
            return {"status": "Accepted"}
        if action == "GetConfiguration":
            values = {
                "SupportedFeatureProfiles": "Core,Reservation,SmartCharging",
                "ReserveConnectorZeroSupported": "false",
                "ChargingScheduleAllowedChargingRateUnit": "Power",
                "ChargeProfileMaxStackLevel": "1",
                **{key: str(value) for key, value in self.remote_configuration.items()},
            }
            keys = payload.get("key") or list(values)
            return {
                "configurationKey": [
                    {
                        "key": key,
                        "readonly": key not in self.remote_configuration,
                        "value": values[key],
                    }
                    for key in keys
                    if key in values
                ],
                "unknownKey": [key for key in keys if key not in values],
            }
        if action == "CancelReservation":
            target = next(
                (
                    n
                    for n, r in self.reservations.items()
                    if r["reservationId"] == payload.get("reservationId")
                ),
                None,
            )
            if target is None:
                return {"status": "Rejected"}
            del self.reservations[target]
            self.save_reservations()
            self.schedule_status(target, "Available")
            return {"status": "Accepted"}
        number = payload.get("connectorId")
        if type(number) is not int or number not in self.meters:
            return {"status": "Rejected"}
        if number == self.config["fault_connector"]:
            return {"status": "Faulted"}
        if (
            number in self.transactions
            or number in self.starting
            or number in self.awaiting_unplug
            or self.reservation_for(number)
        ):
            return {"status": "Occupied"}
        try:
            expiry = datetime.fromisoformat(payload["expiryDate"])
            valid = (
                expiry.tzinfo is not None
                and expiry > datetime.now(UTC)
                and type(payload.get("reservationId")) is int
                and payload["reservationId"] > 0
                and isinstance(payload.get("idTag"), str)
                and 0 < len(payload["idTag"]) <= 20
            )
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            return {"status": "Rejected"}
        self.reservations[number] = {
            key: payload[key] for key in ("reservationId", "idTag", "expiryDate")
        }
        self.save_reservations()
        self.schedule_status(number, "Reserved")
        return {"status": "Accepted"}

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
                reservation = self.reservation_for(connector)
                if connector in self.awaiting_unplug or (
                    reservation and reservation["idTag"] != tag
                ):
                    return
                result = await self.call(
                    "StartTransaction",
                    {
                        "connectorId": connector,
                        "idTag": tag,
                        "meterStart": self.meters[connector],
                        **(
                            {"reservationId": reservation["reservationId"]}
                            if reservation
                            else {}
                        ),
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
                self.transactions[connector] = result["transactionId"]
                if result.get("idTagInfo", {}).get("status") != "Accepted":
                    await self.stop_connector(connector, "DeAuthorized")
                    return
                if reservation:
                    self.reservations.pop(connector, None)
                    self.save_reservations()
                state = self.power_state(connector)
                state.status = "Charging"
                state.transaction_limit_w = state.transaction_profile_id = None
                state.last_meter_at = monotonic()
                self.save_power_profiles()
                await self.status(connector, "Charging")
        finally:
            self.starting.discard(connector)

    async def stop_connector(self, connector, reason):
        transaction = self.transactions.get(connector)
        if transaction is None:
            return
        self.integrate_power(connector)
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
        state = self.power_state(connector)
        state.transaction_limit_w = state.transaction_profile_id = None
        state.last_meter_at = None
        self.save_power_profiles()
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
                if action in {
                    "SetChargingProfile",
                    "GetCompositeSchedule",
                    "ClearChargingProfile",
                }:
                    response = self.power_command(action, payload)
                    await self.socket.send(json.dumps([3, frame[1], response]))
                    continue
                if action in {
                    "GetConfiguration",
                    "ChangeConfiguration",
                    "ReserveNow",
                    "CancelReservation",
                }:
                    response = self.reservation_command(action, payload)
                    await self.socket.send(json.dumps([3, frame[1], response]))
                    continue
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
                        and connector not in self.awaiting_unplug
                        and (
                            not self.reservation_for(connector)
                            or self.reservations[connector]["idTag"]
                            == payload.get("idTag")
                        )
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
                from scripts.ocpp_control_simulator import meter_samples

                state = self.power_state(connector)
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

        path = ROOT / (self.config["code"] + ".reservations.private.json")
        if path.exists():
            self.reservations = {
                int(n): r for n, r in json.loads(path.read_text()).items()
            }
        for number in list(self.reservations):
            self.reservation_for(number)
        registered = await load_connectors(self.config["code"], dispose_engine=False)
        self.meters = {n: state.meter_wh for n, state in registered.items()}
        self.transactions = {
            n: state.transaction_id
            for n, state in registered.items()
            if state.transaction_id is not None
        }
        self.telemetry = registered
        self.load_power_profiles()
        for number in self.transactions:
            self.power_state(number).last_meter_at = monotonic()
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
                        "firmwareVersion": "demo-3-smart-charging",
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
                        else "Reserved"
                        if self.reservation_for(c)
                        else "Available",
                    )
                if receiver.done():
                    await receiver
                self.online = True
                print(
                    f"{self.config['code']} online; transactions {self.transactions or '-'}",
                    flush=True,
                )
                heartbeat_at = meter_at = 0.0
                while not STOP.exists():
                    tick = monotonic()
                    if (
                        tick - heartbeat_at
                        >= self.remote_configuration["HeartbeatInterval"]
                    ):
                        await self.call("Heartbeat", {})
                        heartbeat_at = tick
                    if (
                        tick - meter_at
                        >= self.remote_configuration["MeterValueSampleInterval"]
                    ):
                        await self.meter_values()
                        meter_at = tick
                    for number in list(self.reservations):
                        if self.reservation_for(number) is None:
                            await self.status(number, "Available")
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
