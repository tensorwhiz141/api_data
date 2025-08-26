
# app/api/v1/routes_persona.py
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorCollection
from typing import Literal
from app.core.db import get_collection
from app.models.persona import PersonaProfile
from app.models.logs import DomainInteractionLog

router = APIRouter(prefix="/persona", tags=["persona"])

COLL_PERSONA: AsyncIOMotorCollection = get_collection("persona_profiles")
COLL_LOGS: AsyncIOMotorCollection = get_collection("domain_interaction_logs")

@router.get("/{user_id}", response_model=PersonaProfile)
async def get_persona(user_id: str):
    doc = await COLL_PERSONA.find_one({"user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Profile not found")
    return PersonaProfile(**doc)

@router.post("/update-domain", status_code=status.HTTP_204_NO_CONTENT)
async def update_domain_score(
    user_id: str,
    domain: Literal["gurukul", "finance"],
    updates: dict
):
    # Pull, patch, push
    profile = await COLL_PERSONA.find_one({"user_id": user_id})
    if not profile:
        raise HTTPException(404, "Profile not found")
    profile["domains"][domain].update(updates)
    await COLL_PERSONA.replace_one({"user_id": user_id}, profile)

@router.post("/feedback/domain", status_code=status.HTTP_204_NO_CONTENT)
async def log_feedback(
    payload: DomainInteractionLog,
):
    await COLL_LOGS.insert_one(payload.dict())

@router.post("/domain/log", status_code=status.HTTP_204_NO_CONTENT)
async def log_interaction(payload: DomainInteractionLog):
    await COLL_LOGS.insert_one(payload.dict())
