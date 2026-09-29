class StationOwnershipDeniedError(Exception):
    pass


class StationIdempotencyConflictError(Exception):
    pass


class ChargePointCodeAlreadyExistsError(Exception):
    pass
