from __future__ import annotations

import io
import os
import tempfile
import warnings
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError

from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()
OWNER_EMAIL = "42primex.eu@gmail.com"
MAX_PHOTO_BYTES = 5 * 1024 * 1024
# Kept outside uploads and public assets; served only by the authenticated route.
PHOTO_DIR = Path(__file__).resolve().parents[3] / "private-data" / "profile-photos"


def photo_owner(user: User = Depends(get_current_user)) -> User:
    if user.email.strip().lower() != OWNER_EMAIL:
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


def photo_path(user: User) -> Path:
    return PHOTO_DIR / f"{user.id}.jpg"


@router.get("")
def read_photo(user: User = Depends(photo_owner)) -> Response:
    try:
        content = photo_path(user).read_bytes()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No profile photo")
    return Response(content, media_type="image/jpeg", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


@router.put("", status_code=204)
def upload_photo(file: UploadFile, user: User = Depends(photo_owner)) -> Response:
    content = file.file.read(MAX_PHOTO_BYTES + 1)
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo must be at most 5 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Unsupported image")
                if source.width * source.height > 20_000_000:
                    raise ValueError("Image dimensions too large")
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((512, 512))
                output = io.BytesIO()
                # Re-encode pixels only: do not retain EXIF/location metadata.
                image.save(output, format="JPEG", quality=90)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(status_code=400, detail="Choose a valid JPG, PNG or WebP photo (up to 20 megapixels)")
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=PHOTO_DIR, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(output.getvalue())
        os.replace(temporary_path, photo_path(user))
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


@router.delete("", status_code=204)
def delete_photo(user: User = Depends(photo_owner)) -> Response:
    photo_path(user).unlink(missing_ok=True)
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})
