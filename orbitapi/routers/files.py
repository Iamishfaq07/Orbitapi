import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from .. import config, db
from ..security import current_user

router = APIRouter(prefix="/api/v2/files", tags=["files"])


@router.post("")
async def upload(file: UploadFile = File(...), private: bool = True, user=Depends(current_user)):
    """Upload a file to your organisation workspace."""
    data = await file.read()
    dest = os.path.join(config.UPLOAD_DIR, file.filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(data)
    fid = db.execute(
        "INSERT INTO files (owner_id, org_id, filename, stored_path, content_type, size, is_private)"
        " VALUES (?,?,?,?,?,?,?)",
        (user.get("user_id"), user.get("org_id"), file.filename, dest, file.content_type, len(data), int(private)),
    )
    return db.one("SELECT * FROM files WHERE id = ?", (fid,))


@router.get("")
def list_files(user=Depends(current_user)):
    return db.query("SELECT id, filename, size, is_private, owner_id FROM files WHERE org_id = ?",
                    (user.get("org_id"),))


@router.get("/download")
def download_by_name(name: str, user=Depends(current_user)):
    """Download a workspace file by name."""
    path = os.path.join(config.UPLOAD_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"No such file: {path}")
    return FileResponse(path)


@router.get("/{file_id}")
def file_meta(file_id: int, user=Depends(current_user)):
    f = db.one("SELECT * FROM files WHERE id = ?", (file_id,))
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    return f


@router.get("/{file_id}/content")
def file_content(file_id: int, user=Depends(current_user)):
    f = db.one("SELECT * FROM files WHERE id = ?", (file_id,))
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    if f["is_private"] and f["owner_id"] != user.get("user_id") and f["org_id"] != user.get("org_id"):
        raise HTTPException(status_code=403, detail="Private file")
    with open(f["stored_path"], "rb") as fh:
        data = fh.read()
    return Response(content=data, media_type=f["content_type"] or "application/octet-stream")


@router.delete("/{file_id}")
def delete_file(file_id: int, user=Depends(current_user)):
    f = db.one("SELECT * FROM files WHERE id = ?", (file_id,))
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    if f["org_id"] != user.get("org_id"):
        raise HTTPException(status_code=403, detail="Not your organisation")
    try:
        os.remove(f["stored_path"])
    except OSError:
        pass
    db.execute("DELETE FROM files WHERE id = ?", (file_id,))
    return {"message": "Deleted"}
