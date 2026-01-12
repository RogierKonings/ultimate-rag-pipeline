"""Session management endpoints for the Orchestrator Service.

This module provides CRUD endpoints for conversation sessions:
- POST /api/v1/sessions - Create a new session
- GET /api/v1/sessions/{id} - Get session details
- GET /api/v1/sessions/{id}/history - Get conversation history
- DELETE /api/v1/sessions/{id} - Delete a session
- POST /api/v1/sessions/{id}/clear - Clear session messages
"""

from uuid import UUID

from api.dependencies import SessionManagerDep
from api.models.requests import CreateSessionRequest
from api.models.responses import (
    ClearSessionResponse,
    DeleteSessionResponse,
    ErrorResponse,
    HistoryResponse,
    MessageInfo,
    SessionInfo,
    SessionResponse,
)
from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/api/v1/sessions", tags=["Sessions"])


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new session",
    description="Create a new conversation session with optional configuration.",
    responses={
        201: {"description": "Session created successfully"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
)
async def create_session(
    request: CreateSessionRequest,
    session_manager: SessionManagerDep,
) -> SessionResponse:
    """Create a new conversation session.

    Args:
        request: Session creation request with optional user_id, tenant_id, system_prompt.
        session_manager: Injected session manager.

    Returns:
        SessionResponse with the created session information.
    """
    session = await session_manager.create_session(
        user_id=request.user_id,
        tenant_id=request.tenant_id,
        system_prompt=request.system_prompt,
    )

    return SessionResponse(
        session=SessionInfo(
            id=session.id,
            user_id=session.user_id,
            tenant_id=session.tenant_id,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=len(session.messages),
            total_tokens=session.total_tokens,
        ),
        message="Session created successfully",
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get session details",
    description="Retrieve details for a specific session.",
    responses={
        200: {"description": "Session found"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
)
async def get_session(
    session_id: UUID,
    session_manager: SessionManagerDep,
) -> SessionResponse:
    """Get session details by ID.

    Args:
        session_id: The session identifier.
        session_manager: Injected session manager.

    Returns:
        SessionResponse with session information.

    Raises:
        HTTPException: If session is not found.
    """
    session = await session_manager.get_session(session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    return SessionResponse(
        session=SessionInfo(
            id=session.id,
            user_id=session.user_id,
            tenant_id=session.tenant_id,
            created_at=session.created_at,
            updated_at=session.updated_at,
            message_count=len(session.messages),
            total_tokens=session.total_tokens,
        ),
    )


@router.get(
    "/{session_id}/history",
    response_model=HistoryResponse,
    summary="Get session history",
    description="Retrieve conversation history for a session.",
    responses={
        200: {"description": "History retrieved"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
)
async def get_session_history(
    session_id: UUID,
    session_manager: SessionManagerDep,
) -> HistoryResponse:
    """Get conversation history for a session.

    Args:
        session_id: The session identifier.
        session_manager: Injected session manager.

    Returns:
        HistoryResponse with messages and optional summary.

    Raises:
        HTTPException: If session is not found.
    """
    session = await session_manager.get_session(session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    messages = [
        MessageInfo(
            id=msg.id,
            role=msg.role.value,
            content=msg.content,
            timestamp=msg.timestamp,
            sources=msg.sources,
        )
        for msg in session.messages
    ]

    return HistoryResponse(
        session_id=session.id,
        messages=messages,
        has_summary=session.summary is not None,
        summary=session.summary,
    )


@router.delete(
    "/{session_id}",
    response_model=DeleteSessionResponse,
    summary="Delete a session",
    description="Delete a session and all its data.",
    responses={
        200: {"description": "Session deleted"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
)
async def delete_session(
    session_id: UUID,
    session_manager: SessionManagerDep,
) -> DeleteSessionResponse:
    """Delete a session entirely.

    Args:
        session_id: The session identifier.
        session_manager: Injected session manager.

    Returns:
        DeleteSessionResponse confirming deletion.

    Raises:
        HTTPException: If session is not found.
    """
    deleted = await session_manager.delete_session(session_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    return DeleteSessionResponse(
        success=True,
        session_id=session_id,
        message="Session deleted successfully",
    )


@router.post(
    "/{session_id}/clear",
    response_model=ClearSessionResponse,
    summary="Clear session messages",
    description="Clear all messages from a session while keeping the session active.",
    responses={
        200: {"description": "Session cleared"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
)
async def clear_session(
    session_id: UUID,
    session_manager: SessionManagerDep,
) -> ClearSessionResponse:
    """Clear all messages from a session.

    This keeps the session active but removes all conversation history.

    Args:
        session_id: The session identifier.
        session_manager: Injected session manager.

    Returns:
        ClearSessionResponse confirming the clear operation.

    Raises:
        HTTPException: If session is not found.
    """
    cleared = await session_manager.clear_session(session_id)

    if not cleared:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    return ClearSessionResponse(
        success=True,
        session_id=session_id,
        message="Session cleared successfully",
    )
