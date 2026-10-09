"""T-92/S-67 register concrete adapters here; never invent a payment redirect."""

from src.modules.payments.contracts import PaymentGateway


def get_payment_gateway() -> PaymentGateway | None:
    # No adapter exists yet, including when configuration selects fake/sandbox.
    # T-92 should select FakeGateway only for settings.payment_gateway == "fake".
    return None
