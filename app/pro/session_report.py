"""Deterministic, local Markdown export of an already-recorded agent session.

The report generator only reads messages already held in agent memory. It does
not invoke an LLM, execute tools, follow links, or read referenced files.
"""

from __future__ import annotations

import html
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from app.pro.entitlement import EntitlementVerifier, require_active_pro_subscription
from app.schema import Message, Role


REDACTED_VALUE = "[REDACTED]"
MAX_OUTPUT_CHARS = 600

# The patterns intentionally redact broadly: a report is a summary, not a place
# to preserve credentials or private file references from arbitrary tool output.
_FULL_SECRET_PATTERNS = (
    re.compile(
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
        re.DOTALL,
    ),
    re.compile(
        r"\b(?:sk-(?:proj-|ant-)?|gh[pousr]_|github_pat_|xox[baprs]-|AIza)[A-Za-z0-9_\-]{12,}\b"
    ),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(r"file://[^\s)`>'\"]+", re.IGNORECASE),
    re.compile(r"~/(?:[^\s)`>'\"]+)"),
    re.compile(r"(?<![A-Za-z0-9_])/(?:home|Users|private|var/folders)/[^\s)`>'\"]+"),
    re.compile(r"(?i)[A-Z]:\\Users\\[^\s)`>'\"]+"),
)
_LABELLED_SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|auth(?:orization)?|bearer|client[_-]?secret|"
    r"password|passwd|secret|session[_-]?token|token)\b\s*(?:=|:|\s)\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
_JSON_SECRET_PATTERN = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|secret|token)\b\s*\"?\s*:\s*\")([^\"]*)(\")"
)
_BEARER_SECRET_PATTERN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
_QUERY_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|auth(?:orization)?|client[_-]?secret|password|secret|token)=)[^&#\s]+"
)


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """A single tool call paired with its recorded response, if any."""

    ordinal: int
    name: str
    result: str | None

    @property
    def status(self) -> str:
        """Classify the runner's recorded outcome without interpreting tool data."""
        if self.result is None:
            return "غير مكتمل"
        if self.result.lstrip().startswith("Error:"):
            return "فشل"
        return "نجح"


def redact_sensitive_text(value: str) -> str:
    """Remove common secrets and private file links before any export rendering."""
    redacted = value
    for pattern in _FULL_SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED_VALUE, redacted)
    redacted = _LABELLED_SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}{REDACTED_VALUE}", redacted
    )
    redacted = _JSON_SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}{REDACTED_VALUE}{match.group(3)}", redacted
    )
    redacted = _BEARER_SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}{REDACTED_VALUE}", redacted
    )
    return _QUERY_SECRET_PATTERN.sub(
        lambda match: f"{match.group(1)}{REDACTED_VALUE}", redacted
    )


def _markdown_inline(value: str) -> str:
    """Escape a dynamic value embedded in an inline Markdown code span."""
    safe = html.escape(redact_sensitive_text(value), quote=False)
    safe = safe.replace("\\", "\\\\").replace("`", "\\`")
    return " ".join(safe.splitlines())


def _markdown_code_block(value: str) -> str:
    """Render dynamic text safely inside a fixed Markdown code block."""
    safe = html.escape(redact_sensitive_text(value), quote=False)
    safe = safe.replace("```", "``\u200b`")
    if len(safe) > MAX_OUTPUT_CHARS:
        safe = f"{safe[:MAX_OUTPUT_CHARS]}\n… [تم اختصار المخرج]"
    return f"```text\n{safe}\n```"


def _tool_calls_from_messages(messages: Iterable[Message]) -> list[ToolExecution]:
    """Pair tool calls and tool results in their recorded, chronological order."""
    responses: dict[str, deque[str]] = defaultdict(deque)
    message_list = list(messages)
    for message in message_list:
        if message.role == Role.TOOL and message.tool_call_id:
            responses[message.tool_call_id].append(message.content or "")

    executions: list[ToolExecution] = []
    ordinal = 0
    for message in message_list:
        if message.role != Role.ASSISTANT or not message.tool_calls:
            continue
        for call in message.tool_calls:
            ordinal += 1
            result = responses[call.id].popleft() if responses[call.id] else None
            executions.append(
                ToolExecution(ordinal=ordinal, name=call.function.name, result=result)
            )
    return executions


def render_session_report(messages: Sequence[Message]) -> str:
    """Build a deterministic report from the supplied in-memory execution log.

    The output intentionally omits prompts, tool arguments, call IDs, images,
    and link targets. These values can contain credentials or private data and
    are unnecessary to state the actual tool execution outcomes.
    """
    executions = _tool_calls_from_messages(messages)
    succeeded = sum(execution.status == "نجح" for execution in executions)
    failed = sum(execution.status == "فشل" for execution in executions)
    incomplete = sum(execution.status == "غير مكتمل" for execution in executions)

    lines = [
        "# تقرير جلسة التنفيذ",
        "",
        "## النطاق",
        "هذا التقرير مشتق محليًا من سجل رسائل الجلسة الموجود بالفعل. لم يُستدعَ نموذج لغوي، ولم تُنفذ أدوات أو تُفتح روابط أو تُقرأ ملفات أثناء التصدير.",
        "",
        "## الملخص الحتمي",
        f"- إجمالي استدعاءات الأدوات: {len(executions)}",
        f"- نجح التنفيذ: {succeeded}",
        f"- فشل التنفيذ: {failed}",
        f"- غير مكتمل (لا يوجد ناتج مسجل): {incomplete}",
        "",
        "## الأدوات",
    ]

    if not executions:
        lines.extend(["لا يحتوي سجل الجلسة على أي استدعاء أداة.", ""])
    else:
        for execution in executions:
            safe_name = _markdown_inline(execution.name)
            lines.extend(
                [
                    f"### {execution.ordinal}. `{safe_name}` — {execution.status}",
                    "",
                    "لا تُصدّر المعلمات أو معرّفات الاستدعاء. المخرج أدناه من السجل الفعلي بعد التنقيح والاختصار.",
                    "",
                ]
            )
            if execution.result is None:
                lines.extend(["لا يوجد ناتج أداة مسجل لهذه الدعوة.", ""])
            else:
                lines.extend([_markdown_code_block(execution.result), ""])

    lines.extend(
        [
            "## ملاحظات السلامة",
            "نُقحت المفاتيح والرموز المميزة وكلمات المرور والأسرار وروابط الملفات الخاصة قبل العرض. حالة «نجح» تعني أن منفذ الأدوات سجل ناتجًا غير بادئ بـ `Error:`؛ ولا تعني تحقق صحة محتوى ذلك الناتج أو إتمام هدف المستخدم.",
            "",
        ]
    )
    return "\n".join(lines)


def _safe_report_destination(destination: Path, workspace_root: Path) -> Path:
    """Limit report writes to the configured workspace and reject existing files."""
    resolved_workspace = workspace_root.resolve()
    resolved_destination = destination.resolve()
    try:
        resolved_destination.relative_to(resolved_workspace)
    except ValueError as error:
        raise PermissionError(
            "Session reports may only be written inside the workspace."
        ) from error
    return resolved_destination


def write_pro_session_report(
    *,
    account_id: str,
    verifier: EntitlementVerifier,
    messages: Sequence[Message],
    destination: Path,
    workspace_root: Path,
) -> Path:
    """Authorize and write a private Markdown session report without extra execution."""
    require_active_pro_subscription(account_id=account_id, verifier=verifier)
    safe_destination = _safe_report_destination(destination, workspace_root)
    safe_destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    content = render_session_report(messages)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(safe_destination, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as report_file:
            report_file.write(content)
    except Exception:
        try:
            safe_destination.unlink()
        except FileNotFoundError:
            pass
        raise
    return safe_destination
