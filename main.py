from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import pandas as pd
import io
import uuid

app = FastAPI(title="Gerador de Relatórios", version="0.1.0")

# CORS liberado (pra funcionar com GitHub Pages)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Memória temporária (quando reiniciar o Render, limpa)
UPLOADS: Dict[str, Dict[str, Any]] = {}

# ---- MODELOS ----
class GerarFaturamentoRequest(BaseModel):
    upload_id: str
    fornecedor: str
    anos: List[int]
    dias: Optional[str] = ""  # Ex: "1-10" ou "5,12,20"


# ---- HELPERS ----
def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().upper().replace(" ", "_") for c in df.columns]
    return df

def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = set(df.columns)
    for c in candidates:
        if c in cols:
            return c
    return None

def _parse_dias(dias_str: str) -> Optional[List[int]]:
    s = (dias_str or "").strip()
    if not s:
        return None
    # aceita "1-10" ou "5,12,20"
    if "-" in s:
        a, b = s.split("-", 1)
        a = int(a.strip()); b = int(b.strip())
        if a > b:
            a, b = b, a
        return list(range(a, b + 1))
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return [int(p) for p in parts]


def _read_excel_bytes(excel_bytes: bytes) -> pd.DataFrame:
    # tenta ler a primeira aba
    bio = io.BytesIO(excel_bytes)

    # engine openpyxl lê .xlsx e geralmente lê .xlsm também
    try:
        df = pd.read_excel(bio, engine="openpyxl")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Não consegui ler o Excel: {e}")

    df = _normalize_cols(df)
    return df


# ---- ROTAS ----
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    # lê bytes
    content = await file.read()
    upload_id = str(uuid.uuid4())

    df = _read_excel_bytes(content)

    # tenta achar coluna de data (EMISSAO)
    col_data = _find_col(df, ["EMISSAO", "DATA", "DATA_EMISSAO", "DT_EMISSAO"])
    if not col_data:
        # não bloqueia, mas avisa depois
        col_data = None
    else:
        # converte data
        df[col_data] = pd.to_datetime(df[col_data], errors="coerce", dayfirst=True)

    UPLOADS[upload_id] = {
        "filename": file.filename,
        "df": df,
        "col_data": col_data,
    }

    return {"upload_id": upload_id, "filename": file.filename}


@app.get("/faturamento/options")
def faturamento_options(upload_id: str):
    if upload_id not in UPLOADS:
        raise HTTPException(status_code=404, detail="upload_id não encontrado. Faça upload primeiro.")

    df = UPLOADS[upload_id]["df"]
    col_data = UPLOADS[upload_id]["col_data"]

    if not col_data:
        raise HTTPException(
            status_code=400,
            detail="Não encontrei a coluna de data (ex: EMISSAO). Verifique o nome da coluna na planilha.",
        )

    # anos disponíveis
    anos = (
        df[col_data]
        .dropna()
        .dt.year
        .dropna()
        .astype(int)
        .unique()
