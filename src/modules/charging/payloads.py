from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Tag = Annotated[str, Field(min_length=1, max_length=20)]
Counter = Annotated[int, Field(ge=-2147483648, le=2147483647)]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="after")
    def reject_null_properties(self) -> Self:
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("Null OCPP property")
        return self


class AuthorizePayload(Payload):
    idTag: Tag


class StartPayload(AuthorizePayload):
    connectorId: Annotated[int, Field(ge=1)]
    meterStart: Counter
    timestamp: AwareDatetime
    reservationId: Counter | None = None


class SamplePayload(Payload):
    value: Annotated[str, Field(max_length=100)]
    measurand: Annotated[str, Field(max_length=50)] = "Energy.Active.Import.Register"
    unit: Annotated[str, Field(max_length=20)] | None = None
    phase: Literal[
        "", "L1", "L2", "L3", "N", "L1-N", "L2-N", "L3-N", "L1-L2", "L2-L3", "L3-L1"
    ] = ""
    location: Literal["Cable", "EV", "Inlet", "Outlet", "Body"] = "Outlet"
    context: Literal[
        "Interruption.Begin",
        "Interruption.End",
        "Sample.Clock",
        "Sample.Periodic",
        "Transaction.Begin",
        "Transaction.End",
        "Trigger",
        "Other",
    ] = "Sample.Periodic"
    format: Literal["Raw", "SignedData"] = "Raw"


class MeterBlock(Payload):
    timestamp: AwareDatetime
    sampledValue: Annotated[list[SamplePayload], Field(min_length=1, max_length=256)]


class TransactionBlock(MeterBlock):
    sampledValue: Annotated[list[SamplePayload], Field(max_length=256)]


class MeterPayload(Payload):
    connectorId: Annotated[int, Field(ge=0)]
    transactionId: Counter | None = None
    meterValue: Annotated[list[MeterBlock], Field(min_length=1, max_length=256)]


class StopPayload(Payload):
    transactionId: Counter
    meterStop: Counter
    timestamp: AwareDatetime
    idTag: Tag | None = None
    reason: Literal[
        "EmergencyStop",
        "EVDisconnected",
        "HardReset",
        "Local",
        "Other",
        "PowerLoss",
        "Reboot",
        "Remote",
        "SoftReset",
        "UnlockCommand",
        "DeAuthorized",
    ] = "Local"
    transactionData: Annotated[list[TransactionBlock], Field(max_length=256)] = []
