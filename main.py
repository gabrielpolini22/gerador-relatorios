from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import os
import uuid

import pandas as pd

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _path_for(upload_id: str) -> str:
    return os.path.join(UPLOAD_DIR, f"{upload_id}.xlsx")


def _load_df(upload_id: str) -> pd.DataFrame:
    path = _path_for(upload_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="upload_id não encontrado")

    # Lê a primeira aba por padrão (depois a gente melhora pra escolher a aba certa)
    try:
        df = pd.read_excel(path, engine="openpyxl")
        return df
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Falha ao ler planilha: {str(e)}")


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols_upper = {str(c).strip().upper(): c for c in df.columns}
    for cand in candidates:
        key = cand.strip().upper()
        if key in cols_upper:
            return cols_upper[key]
    return None


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    upload_id = str(uuid.uuid4())

    # salva sempre como .xlsx (mesmo que seja .xlsm)
    path = _path_for(upload_id)

    try:
        content = await file.read()
        with open(path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro salvando arquivo: {str(e)}")

    return {"upload_id": upload_id, "filename": file.filename}


@app.get("/faturamento/options")
def faturamento_options(upload_id: str):
    df = _load_df(upload_id)

    # tenta achar a coluna de data (na tua planilha parece ser EMISSAO)
    col_data = _find_col(df, ["EMISSAO", "EMISSÃO", "DATA", "DATA_EMISSAO", "DATA EMISSAO"])
    if not col_data:
        raise HTTPException(status_code=400, detail="Não encontrei a coluna de data (ex: EMISSAO).")

    # normaliza datas
    df[col_data] = pd.to_datetime(df[col_data], errors="coerce")
    df = df.dropna(subset=[col_data])

    anos = sorted(df[col_data].dt.year.dropna().unique().tolist())
    meses = sorted(df[col_data].dt.month.dropna().unique().tolist())

    # fornecedores por enquanto fixo (depois vamos detectar da planilha)
    fornecedores = ["CAMBER", "HYPERA", "TEUTO", "FARMA", "ZYDUS"]

    return {
        "fornecedores": fornecedores,
        "anos": anos,
        "meses": meses,
    }
