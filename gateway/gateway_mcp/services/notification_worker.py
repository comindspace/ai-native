import json
import logging
import os
import time
from typing import Any

from gateway_mcp.services.storage import (
    claim_notification_deliveries,
    complete_notification_delivery,
    fail_notification_delivery,
)

LOGGER = logging.getLogger("gateway_mcp.notifications")


def run_once(*, batch_size: int = 25, lease_seconds: int = 120) -> dict[str, int]:
    private_key = os.getenv("GATEWAY_WEB_PUSH_VAPID_PRIVATE_KEY", "").strip()
    subject = os.getenv(
        "GATEWAY_WEB_PUSH_VAPID_SUBJECT", "mailto:admin@example.com"
    ).strip()
    max_attempts = max(
        1, min(int(os.getenv("GATEWAY_NOTIFICATION_MAX_ATTEMPTS", "8")), 25)
    )
    if not private_key:
        return {"claimed": 0, "sent": 0, "retried": 0, "failed": 0}

    deliveries = claim_notification_deliveries(
        limit=batch_size,
        lease_seconds=lease_seconds,
    )
    counters = {"claimed": len(deliveries), "sent": 0, "retried": 0, "failed": 0}
    for delivery in deliveries:
        try:
            _send_delivery(delivery, private_key=private_key, subject=subject)
            complete_notification_delivery(int(delivery["id"]))
            counters["sent"] += 1
        except Exception as exc:  # noqa: BLE001 - push providers raise transport-specific exceptions
            status_code = _status_code(exc)
            endpoint_expired = status_code in {404, 410}
            non_retryable = 400 <= status_code < 500 and status_code not in {
                408,
                425,
                429,
            }
            permanent = non_retryable or int(delivery.get("attempts") or 1) >= max_attempts
            fail_notification_delivery(
                delivery_id=int(delivery["id"]),
                error_code=_error_code(exc, status_code),
                permanent=permanent,
                disable_subscription=endpoint_expired,
            )
            counters["failed" if permanent else "retried"] += 1
            LOGGER.warning(
                "Web Push delivery failed",
                extra={
                    "delivery_id": delivery.get("id"),
                    "notification_id": delivery.get("notification_id"),
                    "error_code": _error_code(exc, status_code),
                    "permanent": permanent,
                },
            )
    return counters


def run_forever(
    *,
    poll_seconds: float | None = None,
    batch_size: int | None = None,
    lease_seconds: int = 120,
) -> None:
    interval = poll_seconds or float(
        os.getenv("GATEWAY_NOTIFICATION_POLL_SECONDS", "2")
    )
    batch = batch_size or int(os.getenv("GATEWAY_NOTIFICATION_BATCH_SIZE", "25"))
    while True:
        try:
            result = run_once(batch_size=batch, lease_seconds=lease_seconds)
            if result["claimed"]:
                LOGGER.info("Processed Web Push deliveries", extra=result)
            time.sleep(max(0.25, interval if not result["claimed"] else 0.25))
        except KeyboardInterrupt:
            return
        except Exception as exc:
            LOGGER.exception(
                "Notification worker iteration failed",
                extra={"error_code": exc.__class__.__name__},
            )
            time.sleep(max(2.0, interval))


def _send_delivery(delivery: dict[str, Any], *, private_key: str, subject: str) -> None:
    from pywebpush import webpush

    payload = json.dumps(
        {
            # Lock-screen previews must not disclose project or customer data.
            "title": "GatewayMCP",
            "body": "Новое уведомление в рабочем центре.",
            "url": "/notifications",
            # A unique tag prevents browsers from silently replacing later pushes.
            "tag": str(delivery["notification_id"]),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    webpush(
        subscription_info={
            "endpoint": delivery["endpoint"],
            "keys": {
                "p256dh": delivery["p256dh"],
                "auth": delivery["auth_secret"],
            },
        },
        data=payload,
        vapid_private_key=private_key,
        vapid_claims={"sub": subject},
        ttl=86400,
        timeout=max(
            1.0,
            min(float(os.getenv("GATEWAY_WEB_PUSH_TIMEOUT_SECONDS", "10")), 60.0),
        ),
    )


def _status_code(exc: Exception) -> int:
    response = getattr(exc, "response", None)
    try:
        return int(getattr(response, "status_code", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _error_code(exc: Exception, status_code: int) -> str:
    return f"http_{status_code}" if status_code else exc.__class__.__name__
