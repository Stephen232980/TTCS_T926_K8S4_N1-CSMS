import json
import subprocess
import sys

import httpx
import pytest

from scripts import reconcile_vnpay_topup as cli


def test_help_does_not_prompt_or_login():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.reconcile_vnpay_topup", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert (
        "preview only" in result.stdout and "Administrator email:" not in result.stdout
    )


@pytest.mark.parametrize("apply", [False, True])
def test_cli_authenticated_preview_apply_logout_and_no_secret(
    monkeypatch, capsys, apply
):
    order = "vnpay" + "a" * 32
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/login"):
            assert json.loads(request.content)["password"] == "private-password"
            return httpx.Response(
                200,
                headers={"set-cookie": "session=private-cookie; Secure; Path=/"},
                json={"status": "authenticated"},
            )
        if request.url.path.endswith("/logout"):
            return httpx.Response(204)
        assert request.headers["cookie"] == "session=private-cookie"
        assert json.loads(request.content)["apply"] is apply
        return httpx.Response(
            200,
            json={
                "order_id": order,
                "applied": apply,
                "vnp_SecureHash": "private-signature",
            },
        )

    original = httpx.Client
    monkeypatch.setattr(
        cli.httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "admin@example.com")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "private-password")
    monkeypatch.setattr(
        sys, "argv", ["reconcile", "--order", order] + (["--apply"] if apply else [])
    )
    cli.main()
    output = capsys.readouterr().out
    assert "private" not in output
    assert paths == [
        "/api/v1/auth/login",
        "/api/v1/admin/payments/vnpay/topups/" + order + "/reconcile",
        "/api/v1/auth/logout",
    ]
