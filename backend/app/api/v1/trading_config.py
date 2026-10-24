"""Editable trading settings (day trading, shorting, risk limits, automation)."""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import runtime_settings

router = APIRouter(prefix="/trading-config", tags=["trading-config"])


class ConfigUpdate(BaseModel):
    values: dict
    confirm: bool = False      # required for dangerous switches (e.g. shorting in live mode)


class ConfigReset(BaseModel):
    keys: list[str] | None = None   # None = reset everything editable


def _bad_request(exc: ValueError):
    try:
        detail = json.loads(str(exc))
    except Exception:
        detail = str(exc)
    raise HTTPException(status_code=422, detail=detail)


@router.get("")
async def get_config():
    return runtime_settings.snapshot()


@router.put("")
async def update_config(req: ConfigUpdate):
    if not req.values:
        raise HTTPException(status_code=422, detail="no values given")
    try:
        result = runtime_settings.update(req.values, confirm=req.confirm)
    except ValueError as e:
        _bad_request(e)
    return {**result, **runtime_settings.snapshot()}


@router.post("/reset")
async def reset_config(req: ConfigReset):
    result = runtime_settings.reset(req.keys)
    return {**result, **runtime_settings.snapshot()}


class ProfileSave(BaseModel):
    name: str


@router.get("/profiles")
async def list_profiles():
    return {"profiles": runtime_settings.list_profiles()}


@router.post("/profiles")
async def save_profile(req: ProfileSave):
    try:
        runtime_settings.save_profile(req.name)
    except ValueError as e:
        _bad_request(e)
    return {"profiles": runtime_settings.list_profiles()}


@router.post("/profiles/{name}/apply")
async def apply_profile(name: str):
    try:
        result = runtime_settings.apply_profile(name)
    except ValueError as e:
        _bad_request(e)
    return {**result, **runtime_settings.snapshot()}


@router.delete("/profiles/{name}")
async def delete_profile(name: str):
    try:
        runtime_settings.delete_profile(name)
    except ValueError as e:
        _bad_request(e)
    return {"profiles": runtime_settings.list_profiles()}
