"""Validation API endpoint — validate generated code syntax."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from a2d.validation.syntax_validator import SyntaxValidator

router = APIRouter(prefix="/api", tags=["validate"])

_validator = SyntaxValidator()


class ValidateRequest(BaseModel):
    code: str
    filename: str = "<input>"


class FileValidationResult(BaseModel):
    filename: str
    is_valid: bool
    errors: list[str]


class ValidateResponse(BaseModel):
    results: list[FileValidationResult]
    all_valid: bool


@router.post("/validate", response_model=ValidateResponse)
async def validate_code(req: ValidateRequest) -> ValidateResponse:
    """Validate Python code syntax."""
    result = _validator.validate_string(req.code, filename=req.filename)
    file_result = FileValidationResult(
        filename=result.file_path,
        is_valid=result.is_valid,
        errors=result.errors,
    )
    return ValidateResponse(results=[file_result], all_valid=result.is_valid)
