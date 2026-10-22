"""Blocking SMTP transport shared by domain outbox workers.

Call with asyncio.to_thread outside DB transactions. The caller owns recipient
authorization, templates, durable intent, retries and a stable Message-ID.
"""

import smtplib
import ssl
from email.message import EmailMessage

from src.config import Settings, settings


class EmailDisabledError(ValueError):
    """Transport is disabled; the outbox must retain its pending intent."""


def smtp_enabled(config: Settings = settings) -> bool:
    return (
        config.smtp_enabled
        if config.smtp_enabled is not None
        else config.alert_smtp_enabled
    )


def send_email(
    *,
    recipient: str,
    subject: str,
    text_body: str,
    message_id: str,
    config: Settings = settings,
) -> None:
    """Submit one message or raise OSError/SMTPException/ValueError.

    Success means SMTP acceptance, not inbox delivery. Never generate identity
    here: retries must supply the same message_id. No DB, logging or retries.
    """
    if not smtp_enabled(config):
        raise EmailDisabledError("smtp_disabled")
    shared = config.smtp_enabled is not None
    host = config.smtp_host if shared else config.alert_smtp_host
    port = config.smtp_port if shared else config.alert_smtp_port
    security = config.smtp_security if shared else config.alert_smtp_security
    sender = config.smtp_from if shared else config.alert_smtp_from
    username = config.smtp_username if shared else config.alert_smtp_username
    password = config.smtp_password if shared else config.alert_smtp_password
    timeout = (
        config.smtp_timeout_seconds if shared else config.alert_smtp_timeout_seconds
    )
    if not host or not sender or not recipient or not message_id:
        raise ValueError("smtp_missing_configuration_or_identity")
    message = EmailMessage()
    message["From"] = str(sender)
    message["To"] = recipient
    message["Message-ID"] = message_id
    message["Subject"] = subject
    message.set_content(text_body)
    context = ssl.create_default_context()
    client: smtplib.SMTP
    if security == "ssl":
        client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)
    with client:
        if security == "starttls":
            client.starttls(context=context)
        if username and password:
            client.login(username, password.get_secret_value())
        if client.send_message(message):
            raise smtplib.SMTPException("recipient_refused")
