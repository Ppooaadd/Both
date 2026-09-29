"""Direct-to-storage uploads via presigned POST (size-limited, fixed key)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, status

from pianoforge.api.deps import CurrentUser, DbDep, SettingsDep, StorageDep, user_rate_limit
from pianoforge.api.errors import APIError, PayloadTooLarge
from pianoforge.api.schemas import FORMATS_HINT, UploadCreateIn, UploadCreateOut
from pianoforge.db.enums import AssetStatus
from pianoforge.db.models import AudioAsset
from pianoforge.storage import keys as K

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post(
    "",
    response_model=UploadCreateOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(user_rate_limit("uploads"))],
)
async def create_upload(
    body: UploadCreateIn, user: CurrentUser, db: DbDep, settings: SettingsDep, storage: StorageDep
) -> UploadCreateOut:
    if body.mime_type not in settings.allowed_mime_types:
        raise APIError(
            FORMATS_HINT,
            code="unsupported_media_type",
            status_code=415,
        )
    if body.size_bytes > settings.upload_max_bytes:
        mb = settings.upload_max_bytes // (1024 * 1024)
        raise PayloadTooLarge(f"파일 크기는 최대 {mb}MB까지 업로드할 수 있습니다.")

    asset_id = uuid.uuid4()
    key = K.raw_audio(user.id, asset_id)
    db.add(
        AudioAsset(
            id=asset_id,
            user_id=user.id,
            storage_key=key,
            original_filename=body.filename,
            mime_type=body.mime_type,
            size_bytes=body.size_bytes,
            status=AssetStatus.pending,
            # Unconfirmed uploads are purged by the same retention sweep.
            purge_after=datetime.now(UTC) + timedelta(days=settings.raw_retention_days),
        )
    )
    await db.commit()
    # Signing is local CPU work (no network); no thread offload needed.
    post = storage.presign_upload(key, body.mime_type, settings.upload_max_bytes)
    return UploadCreateOut(
        upload_id=asset_id,
        url=post.url,
        fields=post.fields,
        expires_in=post.expires_in,
        max_bytes=settings.upload_max_bytes,
    )
