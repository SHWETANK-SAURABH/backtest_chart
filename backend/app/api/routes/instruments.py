"""Instrument catalogue."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import InstrumentResponse
from app.database.models import Instrument
from app.database.session import get_session

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("")
def list_instruments(session: Annotated[Session, Depends(get_session)]) -> list[InstrumentResponse]:
    rows = session.scalars(
        select(Instrument).where(Instrument.is_active).order_by(Instrument.symbol)
    )
    return [InstrumentResponse.model_validate(row) for row in rows]
