from __future__ import annotations

import stat
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.pro.entitlement import (
    EntitlementConfigurationError,
    ProAccessDeniedError,
    SubscriptionState,
    UnconfiguredEntitlementVerifier,
    VerifiedEntitlement,
)
from app.pro.session_report import render_session_report, write_pro_session_report
from app.schema import Function, Message, Role, ToolCall


class StaticVerifier:
    """Test-only verifier injected at the service boundary."""

    def __init__(self, entitlement: VerifiedEntitlement):
        self.entitlement = entitlement

    def verify_subscription(self, *, account_id: str) -> VerifiedEntitlement:
        self.last_account_id = account_id
        return self.entitlement


def session_messages() -> list[Message]:
    return [
        Message(
            role=Role.ASSISTANT,
            tool_calls=[
                ToolCall(
                    id="call-success",
                    function=Function(
                        name="browser<fetch>\n# injected heading",
                        arguments='{"token": "must-not-appear"}',
                    ),
                ),
                ToolCall(
                    id="call-failure",
                    function=Function(name="python_execute", arguments="{}"),
                ),
                ToolCall(
                    id="call-missing", function=Function(name="search", arguments="{}")
                ),
            ],
        ),
        Message.tool_message(
            name="browser<fetch>\n# injected heading",
            tool_call_id="call-success",
            content=(
                "Observed output: api_key=sk-proj-abcdefghijklmnopqrstuv "
                "file:///home/alice/private.txt <script>alert(1)</script> "
                "Authorization: Bearer a-very-secret-token"
            ),
        ),
        Message.tool_message(
            name="python_execute",
            tool_call_id="call-failure",
            content="Error: password='do-not-export'",
        ),
    ]


class SessionReportTests(unittest.TestCase):
    def test_report_is_deterministic_and_redacts_sensitive_output(self) -> None:
        messages = session_messages()

        report = render_session_report(messages)

        self.assertEqual(report, render_session_report(messages))
        self.assertIn("إجمالي استدعاءات الأدوات: 3", report)
        self.assertIn("نجح التنفيذ: 1", report)
        self.assertIn("فشل التنفيذ: 1", report)
        self.assertIn("غير مكتمل (لا يوجد ناتج مسجل): 1", report)
        self.assertIn("`browser&lt;fetch&gt; # injected heading` — نجح", report)
        self.assertIn("`python_execute` — فشل", report)
        self.assertIn("`search` — غير مكتمل", report)
        self.assertNotIn("sk-proj-abcdefghijklmnopqrstuv", report)
        self.assertNotIn("must-not-appear", report)
        self.assertNotIn("do-not-export", report)
        self.assertNotIn("file:///home/alice/private.txt", report)
        self.assertNotIn("/home/alice/private.txt", report)
        self.assertNotIn("<script>", report)
        self.assertIn("[REDACTED]", report)
        self.assertIn("&lt;script&gt;", report)

    def test_active_subscription_writes_private_report_in_workspace(self) -> None:
        entitlement = VerifiedEntitlement(
            account_id="account-1",
            state=SubscriptionState.ACTIVE,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        verifier = StaticVerifier(entitlement)
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            destination = workspace / "reports" / "session.md"

            written = write_pro_session_report(
                account_id="account-1",
                verifier=verifier,
                messages=session_messages(),
                destination=destination,
                workspace_root=workspace,
            )

            self.assertEqual(written, destination.resolve())
            self.assertTrue(written.is_file())
            self.assertEqual(stat.S_IMODE(written.stat().st_mode), 0o600)
            self.assertEqual(verifier.last_account_id, "account-1")

    def test_unconfigured_verifier_and_inactive_subscription_cannot_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory) / "workspace"
            destination = workspace / "session.md"

            with self.assertRaises(EntitlementConfigurationError):
                write_pro_session_report(
                    account_id="account-1",
                    verifier=UnconfiguredEntitlementVerifier(),
                    messages=session_messages(),
                    destination=destination,
                    workspace_root=workspace,
                )
            self.assertFalse(destination.exists())

            expired = StaticVerifier(
                VerifiedEntitlement(
                    account_id="account-1",
                    state=SubscriptionState.EXPIRED,
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
            with self.assertRaises(ProAccessDeniedError):
                write_pro_session_report(
                    account_id="account-1",
                    verifier=expired,
                    messages=session_messages(),
                    destination=destination,
                    workspace_root=workspace,
                )
            self.assertFalse(destination.exists())

    def test_report_destination_cannot_escape_workspace(self) -> None:
        verifier = StaticVerifier(
            VerifiedEntitlement(account_id="account-1", state=SubscriptionState.ACTIVE)
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            outside = base / "outside.md"

            with self.assertRaises(PermissionError):
                write_pro_session_report(
                    account_id="account-1",
                    verifier=verifier,
                    messages=session_messages(),
                    destination=outside,
                    workspace_root=base / "workspace",
                )
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
