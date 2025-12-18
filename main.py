from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import pandas as pd
import uuid
import os
import re
import unicodedata
from io import BytesIO
from typing import Any, Dict, List, Optional

app = FastAPI(title="Gerador de Relatórios", version="1.1.0")

# CORS (GitHub Pages)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # depois você pode trocar pelo teu domínio do pages
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ================== MAPAS DE COLUNAS (ajustáveis) ==================
COLMAP = {
    "fornecedor": [
        "fornecedor", "nm_fornecedor", "nome_fornecedor", "forn", "laboratorio",
        "fabricante", "industria", "empresa", "emitente", "razao_emitente"
    ],
    "filial": [
        "filial", "unidade", "loja", "cd", "centro_de_distribuicao", "deposito",
        "estabelecimento", "nm_filial", "nome_filial"
    ],
    "data": [
        "data", "dt", "data_emissao", "dt_emissao", "emissao", "data_nf", "dt_nf",
        "data_faturamento", "datahora", "data_hora", "dh_emissao"
    ],
    # CHIESI (exemplo)
    "uf": ["uf", "estado"],
    "cnpj_cli": ["cnpj_cli", "cnpj_cliente", "cnpj", "cpf_cnpj"],
    "razao_social": ["razao_social", "razao", "cliente", "nm_cliente", "nome_cliente"],
    "descricao": ["descricao", "descr", "produto", "ds_produto", "descricao_produto"],
    "qtd_cx": ["qtd_cx", "quantidade_caixas", "qtd", "qtde", "quantidade"],
    "vlr_caixa": ["vlr_caixa", "valor_caixa", "vlr", "valor", "valor_unitario"],
}

# ------------------ Helpers ------------------
def slug(s: str) -> str:
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "", s)
    return s

def find_upload_path(upload_id: str) -> str:
    for fname in os.listdir(UPLOAD_DIR):
        if fname.startswith(f"{upload_id}_"):
            return os.path.join(UPLOAD_DIR, fname)
    raise HTTPException(status_code=404, detail="upload_id não encontrado no servidor.")

def pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = list(df.columns)
    cols_set = set(cols)

    # 1) match exato
    for c in candidates:
        cc = slug(c)
        if cc in cols_set:
            return cc

    # 2) match por "contém" (ex.: fornecedor dentro de nome_fornecedor)
    for c in candidates:
        cc = slug(c)
        if not cc:
            continue
        for col in cols:
            if cc in col:
                return col

    return None

def read_planilha(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()

    if ext == ".csv":
        try:
            df = pd.read_csv(path, sep=";", dtype=str, low_memory=False)
            if df.shape[1] == 1:
                df = pd.read_csv(path, sep=",", dtype=str, low_memory=False)
        except Exception:
            df = pd.read_csv(path, dtype=str, low_memory=False)

        df.columns = [slug(c) for c in df.columns]
        df.attrs["sheet_name"] = None
        return df

    if ext in [".xlsx", ".xlsm"]:
        try:
            xls = pd.ExcelFile(path, engine="openpyxl")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro abrindo Excel: {str(e)}")

        # escolhe a melhor aba lendo só um "sample" (rápido)
        keywords = []
        for key in ["fornecedor", "filial", "data", "uf", "cnpj_cli", "razao_social", "descricao"]:
            keywords.extend([slug(x) for x in COLMAP.get(key, [])])
        keywords = [k for k in keywords if k]

        best_sheet = None
        best_score = -1

        for sheet in xls.sheet_names:
            try:
                sample = pd.read_excel(xls, sheet_name=sheet, nrows=50)
                sample.columns = [slug(c) for c in sample.columns]
                cols = list(sample.columns)

                matches = 0
                for k in keywords:
                    # exato ou contém
                    if k in cols or any(k in c for c in cols):
                        matches += 1

                # score: prioriza aba com mais "matches" e mais colunas
                score = matches * 1000 + len(cols)
                if score > best_score:
                    best_score = score
                    best_sheet = sheet
            except Exception:
                continue

        # fallback: primeira aba
        if not best_sheet:
            best_sheet = xls.sheet_names[0]

        try:
            df = pd.read_excel(xls, sheet_name=best_sheet)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro lendo aba '{best_sheet}': {str(e)}")

        df.columns = [slug(c) for c in df.columns]
        df.attrs["sheet_name"] = best_sheet
        return df

    if ext == ".xls":
        raise HTTPException(
            status_code=400,
            detail="Arquivo .xls (antigo) não suportado aqui. Salve como .xlsx/.xlsm e tente novamente."
        )

    raise HTTPException(status_code=400, detail=f"Extensão não suportada: {ext}")

def ensure_date_parts(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    if "__dt" in df.columns:
        return df
    dt = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
    df = df.copy()
    df["__dt"] = dt
    df["__ano"] = df["__dt"].dt.year
    df["__mes"] = df["__dt"].dt.month
    df["__dia"] = df["__dt"].dt.day
    return df

def unique_sorted(df: pd.DataFrame, col: str, limit: int = 400) -> List[str]:
    if col not in df.columns:
        return []
    vals = (
        df[col].dropna().astype(str)
        .map(lambda x: x.strip())
        .replace("", pd.NA).dropna()
        .unique().tolist()
    )
    vals = sorted(vals)
    return vals[:limit]

def first_or_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, list):
        return str(v[0]) if len(v) else None
    return str(v)

def list_or_empty(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip() != ""]
    s = str(v).strip()
    return [s] if s else []

# ------------------ Templates ------------------
def template_default(df: pd.DataFrame, _: Dict[str, Any]) -> pd.DataFrame:
    return df

def template_chiesi(df: pd.DataFrame, _: Dict[str, Any]) -> pd.DataFrame:
    # Ordem exigida: uf, cnpj_cli, razao social, descrição, qtd cx, vlr caixa
    uf = pick_col(df, COLMAP["uf"])
    cnpj = pick_col(df, COLMAP["cnpj_cli"])
    razao = pick_col(df, COLMAP["razao_social"])
    desc = pick_col(df, COLMAP["descricao"])
    qtd = pick_col(df, COLMAP["qtd_cx"])
    vlr = pick_col(df, COLMAP["vlr_caixa"])

    missing = [k for k, v in {
        "uf": uf,
        "cnpj_cli": cnpj,
        "razao_social": razao,
        "descricao": desc,
        "qtd_cx": qtd,
        "vlr_caixa": vlr,
    }.items() if v is None]

    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CHIESI: colunas não encontradas: {missing}. Ajuste COLMAP conforme o cabeçalho real."
        )

    out = df[[uf, cnpj, razao, desc, qtd, vlr]].copy()
    out.columns = ["uf", "cnpj_cli", "razao_social", "descricao", "qtd_cx", "vlr_caixa"]
    return out

TEMPLATES = {
    "DEFAULT": template_default,
    "CHIESI": template_chiesi,
}

# ------------------ Endpoints ------------------
@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/upload")
async def upload_planilha(file: UploadFile = File(...)):
    upload_id = str(uuid.uuid4())
    filename = file.filename or "arquivo"
    save_path = os.path.join(UPLOAD_DIR, f"{upload_id}_{filename}")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    with open(save_path, "wb") as f:
        f.write(content)

    return {"upload_id": upload_id, "filename": filename}

# DEBUG: mostra aba escolhida e colunas detectadas (não expõe dados)
@app.get("/debug/columns")
def debug_columns(upload_id: str):
    path = find_upload_path(upload_id)
    df = read_planilha(path)
    fornecedor_col = pick_col(df, COLMAP["fornecedor"])
    filial_col = pick_col(df, COLMAP["filial"])
    data_col = pick_col(df, COLMAP["data"])
    return {
        "sheet": df.attrs.get("sheet_name"),
        "columns": df.columns.tolist(),
        "detected": {
            "fornecedor": fornecedor_col,
            "filial": filial_col,
            "data": data_col,
        }
    }

@app.get("/faturamento/options")
def faturamento_options(upload_id: str):
    path = find_upload_path(upload_id)
    df = read_planilha(path)

    fornecedor_col = pick_col(df, COLMAP["fornecedor"])
    filial_col = pick_col(df, COLMAP["filial"])
    data_col = pick_col(df, COLMAP["data"])

    if data_col:
        df = ensure_date_parts(df, data_col)

    options = {
        "padrao": sorted(list(TEMPLATES.keys())),
        "fornecedor": unique_sorted(df, fornecedor_col) if fornecedor_col else [],
        "filial": unique_sorted(df, filial_col) if filial_col else [],
        "ano": sorted([str(int(x)) for x in df["__ano"].dropna().unique().tolist()]) if data_col else [],
        "mes": sorted([str(int(x)) for x in df["__mes"].dropna().unique().tolist()]) if data_col else [],
        "dia": sorted([str(int(x)) for x in df["__dia"].dropna().unique().tolist()]) if data_col else [],
    }
    return options

@app.post("/faturamento/gerar")
def faturamento_gerar(payload: Dict[str, Any] = Body(...)):
    upload_id = payload.get("upload_id")
    if not upload_id:
        raise HTTPException(status_code=400, detail="Campo upload_id é obrigatório.")

    path = find_upload_path(str(upload_id))
    df = read_planilha(path)

    fornecedor_col = pick_col(df, COLMAP["fornecedor"])
    filial_col = pick_col(df, COLMAP["filial"])
    data_col = pick_col(df, COLMAP["data"])

    if data_col:
        df = ensure_date_parts(df, data_col)

    padrao = (first_or_none(payload.get("padrao")) or "DEFAULT").upper()
    fornecedores = list_or_empty(payload.get("fornecedor"))
    filiais = list_or_empty(payload.get("filial"))
    anos = list_or_empty(payload.get("ano"))
    meses = list_or_empty(payload.get("mes"))
    dias = list_or_empty(payload.get("dia"))

    if fornecedor_col and fornecedores:
        df = df[df[fornecedor_col].astype(str).isin(fornecedores)]
    if filial_col and filiais:
        df = df[df[filial_col].astype(str).isin(filiais)]
    if data_col:
        if anos:
            df = df[df["__ano"].astype("Int64").astype(str).isin(anos)]
        if meses:
            df = df[df["__mes"].astype("Int64").astype(str).isin(meses)]
        if dias:
            df = df[df["__dia"].astype("Int64").astype(str).isin(dias)]

    if df.empty:
        raise HTTPException(status_code=400, detail="Nenhum dado após aplicar filtros.")

    if padrao not in TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Padrão inválido: {padrao}. Use: {list(TEMPLATES.keys())}")

    out_df = TEMPLATES[padrao](df, payload)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        out_df.to_excel(writer, index=False, sheet_name="Relatorio")

    output.seek(0)

    filename = f"relatorio_{padrao}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )
