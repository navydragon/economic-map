from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .database import check_database

app = FastAPI(title="Russia Map API", version="0.1.0")


class HealthResponse(BaseModel):
    status: str


class DatabaseHealthResponse(HealthResponse):
    postgis_version: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/health/db", response_model=DatabaseHealthResponse)
def database_health() -> DatabaseHealthResponse:
    try:
        version = check_database()
    except (SQLAlchemyError, ValidationError) as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return DatabaseHealthResponse(status="ok", postgis_version=version)
