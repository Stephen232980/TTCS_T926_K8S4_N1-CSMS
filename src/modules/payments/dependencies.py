"""T-92/S-67 concrete payment gateway dependency registration."""

from src.config import get_settings
from src.modules.payments.contracts import PaymentGateway
from src.modules.payments.fake_gateway import FakeGateway


def get_payment_gateway() -> PaymentGateway | None:
    """Return configured payment gateway adapter; FakeGateway for 'fake', None otherwise."""
    settings = get_settings()
    if settings.payment_gateway == "fake":
        return FakeGateway(
            base_url=str(settings.payment_fake_base_url),
            secret=settings.payment_webhook_secret,
        )
    return None
