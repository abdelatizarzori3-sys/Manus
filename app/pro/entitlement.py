"""Server-verified subscription boundary for Pro-only functionality.

This module intentionally contains no client-side activation state. A hosting
application must provide an authenticated account identity and a verifier that
obtains subscription status from its server-side billing records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol


class EntitlementConfigurationError(RuntimeError):
    """Raised when a server entitlement verifier has not been configured."""


class ProAccessDeniedError(PermissionError):
    """Raised when an account does not hold an active Pro subscription."""


class SubscriptionState(StrEnum):
    """States accepted from the server-side subscription source of truth."""

    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PAST_DUE = "past_due"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class VerifiedEntitlement:
    """Subscription information returned by a trusted server-side verifier.

    ``account_id`` must come from the authenticated session, not a CLI argument,
    query string, local storage, or a payment return URL.
    """

    account_id: str
    state: SubscriptionState
    expires_at: datetime | None = None

    def is_active(self, *, now: datetime) -> bool:
        """Return whether this entitlement is currently eligible for Pro access."""
        if self.state is not SubscriptionState.ACTIVE:
            return False
        if self.expires_at is None:
            return True
        if self.expires_at.tzinfo is None:
            return False
        return self.expires_at > now


class EntitlementVerifier(Protocol):
    """Adapter implemented by the authenticated application's backend client."""

    def verify_subscription(self, *, account_id: str) -> VerifiedEntitlement:
        """Load the current billing-backed entitlement for ``account_id``."""
        raise NotImplementedError


class UnconfiguredEntitlementVerifier:
    """Default verifier: deny access until a real server integration exists."""

    def verify_subscription(self, *, account_id: str) -> VerifiedEntitlement:
        del account_id
        raise EntitlementConfigurationError(
            "Pro purchase setup is required: configure an authenticated, "
            "server-side subscription verifier before enabling session reports."
        )


def require_active_pro_subscription(
    *,
    account_id: str,
    verifier: EntitlementVerifier,
    now: datetime | None = None,
) -> VerifiedEntitlement:
    """Validate server-backed Pro access for the authenticated account.

    The function fails closed for missing, mismatched, cancelled, expired, or
    malformed entitlements. It never grants access from local configuration.
    """
    normalized_account_id = account_id.strip()
    if not normalized_account_id:
        raise ProAccessDeniedError("An authenticated account is required for Pro access.")

    entitlement = verifier.verify_subscription(account_id=normalized_account_id)
    if entitlement.account_id != normalized_account_id:
        raise ProAccessDeniedError("The verified subscription belongs to another account.")

    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        raise ValueError("The entitlement clock must be timezone-aware.")
    if not entitlement.is_active(now=current_time):
        raise ProAccessDeniedError("An active Pro subscription is required.")

    return entitlement
