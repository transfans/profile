from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.db.session import get_db
from app.schemas.profile import AvatarResponse
from app.services.avatar_service import (
    ALLOWED_CONTENT_TYPES,
    MAX_FILE_SIZE,
    delete_avatar,
    get_avatar_presigned_url,
    upload_avatar,
)
from app.events.publisher import publish_event
from app.services.profile_service import get_or_create_profile, set_avatar_url

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.post("/me/avatar", response_model=AvatarResponse)
async def upload_profile_avatar(
    file: UploadFile,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AvatarResponse:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_CONTENT_TYPES)}",
        )

    file_data = await file.read()

    if len(file_data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

    email = current_user.email or f"{current_user.id}@unknown"
    profile = await get_or_create_profile(db, current_user.id, email)

    if profile.avatar_url:
        await delete_avatar(profile.avatar_url)

    object_name = await upload_avatar(current_user.id, file_data, file.content_type)
    await set_avatar_url(db, profile, object_name)

    if profile.is_creator:
        await publish_event("creator.updated", {"creator_id": str(current_user.id)})

    presigned_url = await get_avatar_presigned_url(object_name)
    return AvatarResponse(avatar_url=presigned_url)
