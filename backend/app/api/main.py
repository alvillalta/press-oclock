from fastapi import APIRouter

from app.api.routes import login, private, users, mails, utils, questions
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(mails.router)
api_router.include_router(questions.router)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
