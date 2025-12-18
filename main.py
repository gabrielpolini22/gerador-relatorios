from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ✅ CORS (por enquanto liberado pra testar)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # depois a gente restringe pro domínio do GitHub Pages
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/upload")
async def upload_planilha(file: UploadFile = File(...)):
    return {"filename": file.filename, "status": "Arquivo recebido com sucesso"}
