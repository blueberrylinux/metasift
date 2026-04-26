"""Error taxonomy for the port.

Every error the API returns maps to one of these codes so the React UI can
render the right affordance — "click Refresh metadata" vs "paste an LLM key"
vs "your FQN is wrong". Frees the frontend from pattern-matching on error
strings.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel


class ErrorCode(str, Enum):
    """Stable error codes. Never rename — frontend keys UX off these."""

    # Infrastructure
    OM_UNREACHABLE = "om_unreachable"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_QUOTA_EXCEEDED = "llm_quota_exceeded"

    # Preconditions
    NO_METADATA_LOADED = "no_metadata_loaded"
    SCAN_NOT_RUN = "scan_not_run"
    CONVERSATION_NOT_FOUND = "conversation_not_found"
    REVIEW_ITEM_NOT_FOUND = "review_item_not_found"

    # Validation
    INVALID_FQN = "invalid_fqn"
    INVALID_REQUEST = "invalid_request"

    # Runtime
    PARSE_ERROR = "parse_error"
    AGENT_LOOP_LIMIT = "agent_loop_limit"
    SCAN_ALREADY_RUNNING = "scan_already_running"
    PATCH_FAILED = "patch_failed"

    # Catch-all — avoid if possible
    INTERNAL_ERROR = "internal_error"


class ErrorShape(BaseModel):
    """Standard JSON shape for every non-2xx response."""

    code: ErrorCode
    message: str
    detail: dict[str, Any] | None = None


class ApiError(HTTPException):
    """Raise from routes to emit a structured error response.

    Usage:
        raise ApiError(ErrorCode.NO_METADATA_LOADED,
                       "Click Refresh metadata to populate the store.")
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        detail: dict[str, Any] | None = None,
    ) -> None:
        body = ErrorShape(code=code, message=message, detail=detail).model_dump(
            mode="json", exclude_none=True
        )
        super().__init__(status_code=status_code, detail=body)


# Convenience constructors for the most common cases — keeps route code tight.


def no_metadata_loaded() -> ApiError:
    return ApiError(
        ErrorCode.NO_METADATA_LOADED,
        "No metadata loaded yet. POST /api/v1/analysis/refresh first.",
    )


def invalid_fqn(fqn: str, *, examples: list[str] | None = None) -> ApiError:
    """Raised when the user references a fully-qualified name that doesn't
    exist in `om_tables`. 404 is the natural semantic for browser-driven
    callers (e.g. GET /dq/impact/{fqn}) — the resource genuinely is not
    found, as opposed to "your request is malformed" which is 400."""
    return ApiError(
        ErrorCode.INVALID_FQN,
        f"FQN `{fqn}` not found in catalog.",
        detail={"fqn": fqn, "examples": examples or []},
        status_code=status.HTTP_404_NOT_FOUND,
    )


def conversation_not_found(convo_id: str) -> ApiError:
    return ApiError(
        ErrorCode.CONVERSATION_NOT_FOUND,
        f"Conversation `{convo_id}` not found.",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def review_item_not_found(item_id: str) -> ApiError:
    return ApiError(
        ErrorCode.REVIEW_ITEM_NOT_FOUND,
        f"Review item `{item_id}` not found or already resolved.",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def om_unreachable() -> ApiError:
    return ApiError(
        ErrorCode.OM_UNREACHABLE,
        "OpenMetadata is not reachable. Start the stack with `make stack-up`.",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
