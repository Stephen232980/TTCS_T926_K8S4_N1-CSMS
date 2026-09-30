class StationOwnershipDeniedError(Exception):
    pass


class StationIdempotencyConflictError(Exception):
    pass


class ChargePointCodeAlreadyExistsError(Exception):
    pass


class ChargePointCodeLockedError(Exception):
    pass


class ChargePointOwnershipDeniedError(Exception):
    pass
