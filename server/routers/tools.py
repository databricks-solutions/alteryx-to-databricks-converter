"""Tool matrix endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from server.models.responses import ToolMatrixResponse, ToolResponse
from server.services.tool_matrix import get_tool_matrix

router = APIRouter(prefix="/api", tags=["tools"])


@router.get("/tools", response_model=ToolMatrixResponse)
async def tools() -> ToolMatrixResponse:
    categories_raw = get_tool_matrix()
    categories: dict[str, list[ToolResponse]] = {}
    total = 0
    supported = 0

    for cat, tool_list in categories_raw.items():
        responses = []
        for t in tool_list:
            responses.append(ToolResponse(**t))
            total += 1
            if t["supported"]:
                supported += 1
        categories[cat] = responses

    return ToolMatrixResponse(
        categories=categories,
        total_tools=total,
        supported_tools=supported,
    )
