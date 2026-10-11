"""T-92/S-67 concrete payment gateway dependency registration."""

from src.config import get_settings
from src.modules.payments.contracts import PaymentGateway
from src.modules.payments.fake_gateway import FakeGateway
from src.modules.payments.vnpay_gateway import VnpayGateway


def get_payment_gateway() -> PaymentGateway | None:
    """Return configured payment gateway adapter; FakeGateway for 'fake', None otherwise."""
    settings = get_settings()
    if settings.payment_gateway == "fake":
        return FakeGateway(
            base_url=str(settings.payment_fake_base_url),
            secret=settings.payment_webhook_secret,
        )
    if (
        settings.payment_gateway == "sandbox"
        and settings.vnpay_tmn_code
        and settings.vnpay_return_url is not None
        and settings.payment_webhook_secret is not None
    ):
        return VnpayGateway(
            tmn_code=settings.vnpay_tmn_code,
            secret=settings.payment_webhook_secret,
            payment_url=settings.vnpay_payment_url,
            return_url=settings.vnpay_return_url,
            expiry_minutes=settings.vnpay_expiry_minutes,
        )
    return None
