import os
import uuid
from io import BytesIO
from typing import List, Optional

import pandas as pd
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI()

# ✅ CORS (pra GitHub Pages conseguir chamar o Render)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # depois a gente restringe pro seu domínio do Pages
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

SHEET_FATURAMENTO = "FAT_DADOS"  # pelo seu print, é aqui que estão os dados

# ---------- MODELOS ----------
class GerarFaturamentoRequest(BaseModel):
    upload_id: str
    fornecedor: str               # ex: "CAMBER"
    laboratorio: str              # valor da coluna "Laboratório"
    anos: List[int]               # ex: [2024, 2025]
    dias: Optional[str] = ""      # "1-10" ou "5,12,20" ou vazio


# ---------- FUNÇÕES ----------
def _upload_path(upload_id: str) -> str:
    return os.path.join(UPLOAD_DIR, f"{upload_id}.xlsm")

def parse_dias(dias: str) -> Optional[List[int]]:
    dias = (dias or "").strip()
    if not dias:
        return None
    # formatos: "1-10" ou "5,12,20"
    if "-" in dias:
        a, b = dias.split("-", 1)
        a = int(a.strip())
        b = int(b.strip())
        return list(range(min(a, b), max(a, b) + 1))
    return [int(x.strip()) for x in dias.split(",") if x.strip().isdigit()]

def read_faturamento_df(filepath: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(filepath, sheet_name=SHEET_FATURAMENTO, engine="openpyxl")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro lendo a planilha/aba '{SHEET_FATURAMENTO}': {e}")

    # Normaliza nomes de colunas (evita erro por espaços)
    df.columns = [str(c).strip() for c in df.columns]

    # Confere colunas mínimas
    needed = ["EMISSAO", "ESTADO", "CNPJ_CLI", "RAZAO_SOCIAL", "DESCRICAO", "QTD_CX", "ANO", "DIA", "Laboratório"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise HTTPException(status_code=400, detail=f"Faltando colunas na FAT_DADOS: {missing}")

    return df

def fornecedor_layout(fornecedor: str):
    f = (fornecedor or "").strip().upper()

    # ✅ PADRÃO CAMBER (você disse: UF, CNPJ_CLI, RAZAO SOCIAL, DESCRIÇÃO, QTD CX, VLR CAIXA)
    # "VLR_CAIXA": vou usar Custo_CX se existir, senão VL_UNIT
    if f == "CAMBER":
        return [
            ("UF", "ESTADO"),
            ("CNPJ_CLI", "CNPJ_CLI"),
            ("RAZAO_SOCIAL", "RAZAO_SOCIAL"),
            ("DESCRICAO", "DESCRICAO"),
            ("QTD_CX", "QTD_CX"),
            ("VLR_CAIXA", "Custo_CX"),  # fallback abaixo se não existir
        ]

    # Default (pra não quebrar se escolher outro)
    return [
        ("EMISSAO", "EMISSAO"),
        ("CNPJ_CLI", "CNPJ_CLI"),
        ("RAZAO_SOCIAL", "RAZAO_SOCIAL"),
        ("ESTADO", "ESTADO"),
        ("DESCRICAO", "DESCRICAO"),
        ("QTD_CX", "QTD_CX"),
        ("VL_UNIT", "VL_UNIT"),
    ]


# ---------- ROTAS ----------
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".xlsx", ".xls", ".xlsm")):
        raise HTTPException(status_code=400, detail="Envie um arquivo Excel (.xlsx/.xls/.xlsm)")

    upload_id = str(uuid.uuid4())
    path = _upload_path(upload_id)

    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)

    return {"upload_id": upload_id, "filename": file.filename}

@app.get("/faturamento/options")
def faturamento_options(upload_id: str):
    path = _upload_path(upload_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="upload_id não encontrado")

    df = read_faturamento_df(path)

    labs = sorted([x for x in df["Laboratório"].dropna().astype(str).unique().tolist() if x.strip()])
    anos = sorted(df["ANO"].dropna().astype(int).unique().tolist())

    return {"laboratorios": labs, "anos": anos}

@app.post("/faturamento/gerar")
def faturamento_gerar(body: GerarFaturamentoRequest):
    path = _upload_path(body.upload_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="upload_id não encontrado")

    df = read_faturamento_df(path)

    # filtros
    anos = set([int(a) for a in body.anos])
    dias_list = parse_dias(body.dias)

    df_f = df[
        (df["Laboratório"].astype(str) == str(body.laboratorio)) &
        (df["ANO"].astype(int).isin(anos))
    ].copy()

    if dias_list:
        df_f = df_f[df_f["DIA"].astype(int).isin(dias_list)].copy()

    if df_f.empty:
        raise HTTPException(status_code=400, detail="Nenhum dado encontrado com esses filtros")

    # layout fornecedor
    layout = fornecedor_layout(body.fornecedor)

    # fallback VLR_CAIXA
    cols = df_f.columns.tolist()
    out = pd.DataFrame()

    for out_col, src_col in layout:
        if src_col == "Custo_CX" and "Custo_CX" not in cols:
            src_col = "VL_UNIT" if "VL_UNIT" in cols else src_col
        out[out_col] = df_f[src_col] if src_col in cols else ""

    # export xlsx
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        out.to_excel(writer, index=False, sheet_name="REL_FAT")

    bio.seek(0)
    filename = f"{body.fornecedor.upper()}_REL_FAT.xlsx"

    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
