"""Pro-only features with server-verified entitlement boundaries."""

from app.pro.entitlement import (
    EntitlementConfigurationError,
    EntitlementVerifier,
    ProAccessDeniedError,
    SubscriptionState,
    UnconfiguredEntitlementVerifier,
    VerifiedEntitlement,
)
from app.pro.session_report import render_session_report, write_pro_session_report

__all__ = [
    "EntitlementConfigurationError",
    "EntitlementVerifier",
    "ProAccessDeniedError",
    "SubscriptionState",
    "UnconfiguredEntitlementVerifier",
    "VerifiedEntitlement",
    "render_session_report",
    "write_pro_session_report",
]
