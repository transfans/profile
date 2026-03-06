import asyncio
import io
import logging
import uuid

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_USE_SSL,
        )
    return _client


def ensure_bucket_exists() -> None:
    client = get_minio_client()
    bucket = settings.MINIO_BUCKET_NAME
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info("Created MinIO bucket: %s", bucket)


def _get_extension(content_type: str) -> str:
    mapping = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }
    return mapping.get(content_type, "bin")


def _upload_object(
    user_id: uuid.UUID,
    file_data: bytes,
    content_type: str,
) -> str:
    client = get_minio_client()
    ext = _get_extension(content_type)
    object_name = f"{user_id}/{uuid.uuid4()}.{ext}"

    client.put_object(
        settings.MINIO_BUCKET_NAME,
        object_name,
        io.BytesIO(file_data),
        length=len(file_data),
        content_type=content_type,
    )
    return object_name


def _delete_object(object_name: str) -> None:
    client = get_minio_client()
    try:
        client.remove_object(settings.MINIO_BUCKET_NAME, object_name)
    except S3Error:
        logger.warning("Failed to delete object: %s", object_name, exc_info=True)


def _generate_presigned_url(object_name: str) -> str:
    from datetime import timedelta

    client = get_minio_client()
    return client.get_presigned_url(
        "GET",
        settings.MINIO_BUCKET_NAME,
        object_name,
        expires=timedelta(hours=1),
    )


async def upload_avatar(user_id: uuid.UUID, file_data: bytes, content_type: str) -> str:
    return await asyncio.to_thread(_upload_object, user_id, file_data, content_type)


async def delete_avatar(object_name: str) -> None:
    await asyncio.to_thread(_delete_object, object_name)


async def get_avatar_presigned_url(object_name: str) -> str:
    return await asyncio.to_thread(_generate_presigned_url, object_name)
