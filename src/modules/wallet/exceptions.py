"""Wallet domain errors do not commit or roll back the caller's transaction."""


class WalletError(Exception):
    pass


class WalletNotFoundError(WalletError):
    pass


class WalletLockedError(WalletError):
    pass


class WalletLedgerConflictError(WalletError):
    pass


class WalletAmountError(WalletError, ValueError):
    pass


class WalletAdjustmentAuditError(WalletError):
    pass


class WalletAdminRequiredError(WalletError):
    pass
