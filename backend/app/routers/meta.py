"""Static reference data the frontend needs (no auth required)."""

from fastapi import APIRouter

from app.constants.indian_states import INDIAN_STATES

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/states")
def list_states() -> list[dict]:
    """The 37 Indian states / UTs with GST codes, canonical value string."""
    return [
        {"code": code, "name": name, "value": f"{code}-{name}"}
        for code, name in INDIAN_STATES
    ]
