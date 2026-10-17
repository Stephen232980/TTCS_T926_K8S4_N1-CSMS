"""Shared SMTP contract, independent from operational alerts and their outbox."""

import smtplib
import socketserver
import threading
from email import policy
from email.parser import BytesParser
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.config import Settings
from src.modules.alerts import worker
from src.platform import email


def config(**overrides):
    return Settings(
        _env_file=None,
        **(
            {
                "smtp_enabled": True,
                "smtp_host": "smtp.example.com",
                "smtp_from": "csms@example.com",
                "alert_smtp_enabled": False,
            }
            | overrides
        ),
    )


@pytest.fixture
def smtp(monkeypatch):
    plain, secure = MagicMock(), MagicMock()
    plain.return_value.__enter__.return_value = plain.return_value
    secure.return_value.__enter__.return_value = secure.return_value
    plain.return_value.__enter__.return_value.send_message.return_value = {}
    secure.return_value.__enter__.return_value.send_message.return_value = {}
    monkeypatch.setattr(email.smtplib, "SMTP", plain)
    monkeypatch.setattr(email.smtplib, "SMTP_SSL", secure)
    return plain, secure


def send(configured):
    email.send_email(
        recipient="driver@example.com",
        subject="Phiên sạc đã dừng",
        text_body="Trạm A: 2 kWh; tiền ước tính 5.000 VND.",
        message_id="<session-42-stop@csms.invalid>",
        config=configured,
    )


@pytest.mark.parametrize("security", ["plain", "starttls", "ssl"])
def test_shared_transport_without_operator_recipients(smtp, security):
    configured = config(
        smtp_security=security, smtp_username="user", smtp_password="pw"
    )
    assert not configured.alert_email_recipients
    send(configured)
    send(configured)
    plain, secure = smtp
    constructor = secure if security == "ssl" else plain
    client = constructor.return_value.__enter__.return_value
    assert client.login.call_args.args == ("user", "pw")
    assert client.starttls.call_count == (2 if security == "starttls" else 0)
    messages = [call.args[0] for call in client.send_message.call_args_list]
    assert [m["Message-ID"] for m in messages] == [
        "<session-42-stop@csms.invalid>",
        "<session-42-stop@csms.invalid>",
    ]
    assert messages[0]["To"] == "driver@example.com"
    assert messages[0]["From"] == "csms@example.com"
    assert messages[0]["Subject"] == "Phiên sạc đã dừng"
    assert "2 kWh" in messages[0].get_content()
    assert (plain if security == "ssl" else secure).call_count == 0


def test_explicit_disabled_never_falls_back_to_legacy(smtp):
    configured = config(
        smtp_enabled=False,
        alert_smtp_enabled=True,
        alert_email_recipients=["ops@example.com"],
    )
    with pytest.raises(email.EmailDisabledError):
        send(configured)
    assert not smtp[0].called and not smtp[1].called


def test_legacy_profile_remains_usable(smtp):
    configured = Settings(
        _env_file=None,
        smtp_enabled="",
        alert_smtp_enabled=True,
        alert_smtp_host="legacy.example.com",
        alert_smtp_from="old@example.com",
        alert_email_recipients=["ops@example.com"],
        alert_smtp_security="plain",
    )
    send(configured)
    assert smtp[0].call_args.args == ("legacy.example.com", 587)
    assert (
        smtp[0].return_value.__enter__.return_value.send_message.call_args.args[0][
            "From"
        ]
        == "old@example.com"
    )


def test_new_profile_does_not_mix_legacy_credentials(smtp):
    configured = config(alert_smtp_username="old", alert_smtp_password="old-secret")
    send(configured)
    smtp[0].return_value.__enter__.return_value.login.assert_not_called()


@pytest.mark.parametrize("error", [OSError("offline"), smtplib.SMTPException("smtp")])
def test_transport_errors_propagate_to_outbox_without_logging(smtp, caplog, error):
    smtp[0].side_effect = error
    with pytest.raises(type(error)):
        send(config())
    assert not caplog.records


def test_recipient_refusal_is_not_success(smtp):
    smtp[0].return_value.__enter__.return_value.send_message.return_value = {
        "driver@example.com": (550, b"refused")
    }
    with pytest.raises(smtplib.SMTPException, match="recipient_refused"):
        send(config())


@pytest.mark.parametrize(
    "options",
    [
        {"smtp_host": ""},
        {"smtp_from": ""},
        {"smtp_username": "missing-password"},
        {"smtp_password": "missing-user"},
        {"smtp_port": 0},
        {"smtp_timeout_seconds": 0},
        {"smtp_security": "unsafe"},
        {"alert_smtp_enabled": True},
    ],
)
def test_shared_configuration_validation(options):
    with pytest.raises(ValidationError):
        config(**options)


def test_g3_can_use_shared_profile_without_legacy_connection():
    configured = config(
        alert_smtp_enabled=True, alert_email_recipients=["ops@example.com"]
    )
    assert configured.alert_smtp_host == ""
    assert email.smtp_enabled(configured)


def test_header_injection_is_rejected_before_network(smtp):
    with pytest.raises(ValueError):
        email.send_email(
            recipient="driver@example.com\nBcc: other@example.com",
            subject="test",
            text_body="test",
            message_id="<safe@csms.invalid>",
            config=config(),
        )
    assert not smtp[0].called and not smtp[1].called


async def test_disabled_alert_channel_does_not_claim_shared_transport_jobs(monkeypatch):
    monkeypatch.setattr(worker.settings, "alert_smtp_enabled", False)
    monkeypatch.setattr(worker.settings, "smtp_enabled", True)
    factory = MagicMock()
    monkeypatch.setattr(worker, "SessionFactory", factory)
    assert await worker.claim_emails() == []
    factory.assert_not_called()


async def test_disabled_shared_transport_does_not_claim_alert_jobs(monkeypatch):
    monkeypatch.setattr(worker.settings, "alert_smtp_enabled", True)
    monkeypatch.setattr(worker.settings, "smtp_enabled", False)
    factory = MagicMock()
    monkeypatch.setattr(worker, "SessionFactory", factory)
    assert await worker.claim_emails() == []
    factory.assert_not_called()


def test_real_smtp_driver_payload_with_alert_channel_disabled():
    received = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 localhost test SMTP\r\n")
            while raw := self.rfile.readline():
                command = raw.decode().strip().upper()
                if command == "DATA":
                    self.wfile.write(b"354 send data\r\n")
                    lines = []
                    while (line := self.rfile.readline()) != b".\r\n":
                        if not line:
                            return
                        lines.append(line)
                    received.append(b"".join(lines))
                    self.wfile.write(b"250 accepted\r\n")
                elif command == "QUIT":
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 OK\r\n")

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            configured = config(
                smtp_host="127.0.0.1",
                smtp_port=server.server_address[1],
                smtp_security="plain",
            )
            send(configured)
            send(configured)
        finally:
            server.shutdown()
            thread.join(timeout=2)
    messages = [BytesParser(policy=policy.default).parsebytes(raw) for raw in received]
    assert len(messages) == 2
    assert {m["Message-ID"] for m in messages} == {"<session-42-stop@csms.invalid>"}
    assert messages[0]["To"] == "driver@example.com"
    assert messages[0]["Subject"] == "Phiên sạc đã dừng"
    assert "tiền ước tính" in messages[0].get_content()
