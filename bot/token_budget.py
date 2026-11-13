"""Atomic, shared Groq token budgeting backed by Supabase RPCs."""
import logging
import os
import uuid

from bot.db import get_db

DAILY_TOKEN_LIMIT = max(1, int(os.getenv("GROQ_DAILY_TOKEN_LIMIT", "200000")))
CATEGORY_PERCENTAGES = {
    "project": 50,
    "scheduled": 40,
    "emergency": 10,
}
# Covers the compacted request prompt plus a bounded completion. Actual usage
# is settled from Groq's response and unused reservation is returned.
REQUEST_RESERVATION_TOKENS = max(512, int(os.getenv("GROQ_REQUEST_RESERVATION_TOKENS", "3000")))


class GroqBudgetExceeded(RuntimeError):
    """Raised when a feature's daily Groq allocation is exhausted."""


def reserve_tokens(usage_class: str) -> str:
    if usage_class not in CATEGORY_PERCENTAGES:
        raise ValueError(f"Unknown Groq usage class: {usage_class}")
    request_id = str(uuid.uuid4())
    daily_limit = DAILY_TOKEN_LIMIT * CATEGORY_PERCENTAGES[usage_class] // 100
    db = get_db()
    result = db.rpc(
        "reserve_groq_tokens",
        {
            "p_usage_class": usage_class,
            "p_estimate": REQUEST_RESERVATION_TOKENS,
            "p_daily_limit": daily_limit,
            "p_request_id": request_id,
        },
    ).execute()
    if result.data is not True:
        raise GroqBudgetExceeded(
            f"Daily Groq allocation exhausted for {usage_class} "
            f"({CATEGORY_PERCENTAGES[usage_class]}% of {DAILY_TOKEN_LIMIT:,} tokens)."
        )
    logging.info(
        "GROQ BUDGET RESERVED | class=%s | reservation=%s | estimate=%s | daily_limit=%s",
        usage_class, request_id, REQUEST_RESERVATION_TOKENS, daily_limit,
    )
    return request_id


def settle_tokens(request_id: str, actual_tokens: int) -> None:
    db = get_db()
    db.rpc(
        "settle_groq_tokens",
        {
            "p_request_id": request_id,
            "p_actual_tokens": max(0, int(actual_tokens)),
        },
    ).execute()
    logging.info(
        "GROQ TOKEN USAGE SETTLED | reservation=%s | actual_tokens=%s",
        request_id, max(0, int(actual_tokens)),
    )


def release_tokens(request_id: str) -> None:
    """Release a reservation after a failed request that returned no usage data."""
    settle_tokens(request_id, 0)
