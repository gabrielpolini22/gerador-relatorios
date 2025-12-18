from fastapi import FastAPI, UploadFile, File
import uuid
import os

app = FastAPI()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/upload")
async def upload_planilha(file: UploadFile = File(...)):
    upload_id = str(uuid.uuid4())

    filename = file.filename
    save_path = os.path.join(UPLOAD_DIR, f"{upload_id}_{filename}")

    with open(save_path, "wb") as f:
        f.write(await file.read())

    return {
        "upload_id": upload_id,
        "filename": filename
    }
