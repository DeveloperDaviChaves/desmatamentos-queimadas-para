"""Carga das queimadas (BDQueimadas) no PostgreSQL: CSVs -> raw -> stg -> dw.

Uso (PowerShell, na raiz do projeto, com o .venv ativo):
    $env:DATABASE_URL = "postgresql+psycopg2://USUARIO:SENHA@localhost:5432/NOME_DO_BANCO"
    python src/carga_queimadas.py

A senha fica na variável de ambiente, nunca no código nem no GitHub.
O script pode ser rodado várias vezes: cada execução refaz as tabelas de queimadas.
"""
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

PASTA_CSV = Path("data/raw/queimadas_bdqueimadas")
ARQUIVO_SCHEMA = Path("sql/schema_desmatamento_queimadas.sql")
ANO_FINAL_COMPLETO = 2025  # 2026 está incompleto: fica no stg, mas não vai para o dw
ANO_PRODES_INICIAL = 2009  # PRODES 2008 pediria focos desde ago/2007 (não baixados)
MES_INICIO_ANO_PRODES = 8  # o ano PRODES N vai de 1 de agosto de N-1 a 31 de julho de N
SENTINELA = -999           # valor do BDQueimadas para "sem informação"

MAPA_COLUNAS = {
    "DataHora": "data_hora", "Satelite": "satelite", "Pais": "pais",
    "Estado": "estado", "Municipio": "municipio", "Bioma": "bioma",
    "DiaSemChuva": "dia_sem_chuva", "Precipitacao": "precipitacao",
    "RiscoFogo": "risco_fogo", "FRP": "frp",
    "Latitude": "latitude", "Longitude": "longitude",
}
NUMERICAS = ["dia_sem_chuva", "precipitacao", "risco_fogo", "frp", "latitude", "longitude"]
COLUNAS_STG = [
    "data_hora", "ano", "mes", "ano_prodes", "satelite", "estado", "municipio", "bioma",
    "dia_sem_chuva", "precipitacao", "risco_fogo", "frp", "latitude", "longitude",
]


def ler_csv(caminho: Path) -> pd.DataFrame:
    """Lê um CSV como texto, detectando o separador e testando duas codificações."""
    for codificacao in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(caminho, sep=None, engine="python", dtype=str, encoding=codificacao)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Não consegui ler {caminho.name} com utf-8 nem latin-1")


def ler_csvs(pasta: Path) -> pd.DataFrame:
    """Junta todos os CSVs da pasta (tudo texto) e padroniza os nomes das colunas."""
    arquivos = sorted(pasta.glob("*.csv"))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum CSV em {pasta}")
    partes = []
    for arquivo in arquivos:
        df = ler_csv(arquivo)
        faltando = set(MAPA_COLUNAS) - set(df.columns)
        if faltando:
            raise ValueError(f"{arquivo.name}: faltam as colunas {sorted(faltando)}")
        df = df[list(MAPA_COLUNAS)].rename(columns=MAPA_COLUNAS)
        df["arquivo_origem"] = arquivo.name
        partes.append(df)
        print(f"lido: {arquivo.name} ({len(df)} linhas)")
    return pd.concat(partes, ignore_index=True)


def limpar(raw: pd.DataFrame) -> pd.DataFrame:
    """Camada stg: tipos corretos, só Pará, -999 vira nulo, sem duplicados."""
    df = raw.copy()
    for col in ("satelite", "estado", "municipio", "bioma"):
        df[col] = df[col].str.strip()
    df["estado"] = df["estado"].str.upper()
    df = df[df["estado"] == "PARÁ"].copy()

    df["data_hora"] = pd.to_datetime(df["data_hora"], format="%Y/%m/%d %H:%M:%S")
    df["ano"] = df["data_hora"].dt.year.astype("int16")
    df["mes"] = df["data_hora"].dt.month.astype("int16")
    # focos de agosto a dezembro já pertencem ao ano PRODES seguinte
    df["ano_prodes"] = (df["ano"] + (df["mes"] >= MES_INICIO_ANO_PRODES)).astype("int16")

    for col in NUMERICAS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].mask(df[col] == SENTINELA)
    df["dia_sem_chuva"] = df["dia_sem_chuva"].round().astype("Int16")

    df = df.drop_duplicates(subset=["data_hora", "latitude", "longitude", "satelite"])
    return df[COLUNAS_STG]


def criar_schema(engine) -> None:
    conn = engine.raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(ARQUIVO_SCHEMA.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def carregar(engine, raw: pd.DataFrame, stg: pd.DataFrame) -> None:
    with engine.begin() as con:
        con.execute(text("TRUNCATE raw.queimadas"))
        con.execute(text("TRUNCATE stg.focos_queimada RESTART IDENTITY"))
    raw.to_sql("queimadas", engine, schema="raw", if_exists="append",
               index=False, method="multi", chunksize=5000)
    stg.to_sql("focos_queimada", engine, schema="stg", if_exists="append",
               index=False, method="multi", chunksize=5000)


def montar_dw(engine) -> None:
    """Camada dw: focos por UF e ano (Pará), só anos completos."""
    with engine.begin() as con:
        con.execute(text(
            "INSERT INTO dw.dim_tempo (ano) "
            "SELECT DISTINCT ano FROM stg.focos_queimada WHERE ano <= :ano_final "
            "ON CONFLICT DO NOTHING"), {"ano_final": ANO_FINAL_COMPLETO})
        con.execute(text("TRUNCATE dw.fato_queimadas_uf"))
        con.execute(text("TRUNCATE dw.fato_queimadas_uf_prodes"))
        con.execute(text(
            "INSERT INTO dw.fato_queimadas_uf (ano, uf, qtd_focos, frp_total) "
            "SELECT ano, 'PA', COUNT(*), SUM(frp) FROM stg.focos_queimada "
            "WHERE estado = 'PARÁ' AND ano <= :ano_final GROUP BY ano"),
            {"ano_final": ANO_FINAL_COMPLETO})
        con.execute(text(
            "INSERT INTO dw.fato_queimadas_uf_prodes (ano_prodes, uf, qtd_focos, frp_total) "
            "SELECT ano_prodes, 'PA', COUNT(*), SUM(frp) FROM stg.focos_queimada "
            "WHERE estado = 'PARÁ' AND ano_prodes BETWEEN :ini AND :fim GROUP BY ano_prodes"),
            {"ini": ANO_PRODES_INICIAL, "fim": ANO_FINAL_COMPLETO})


def conferir(engine) -> None:
    with engine.connect() as con:
        for tabela in ("raw.queimadas", "stg.focos_queimada", "dw.fato_queimadas_uf", "dw.fato_queimadas_uf_prodes"):
            n = con.execute(text(f"SELECT COUNT(*) FROM {tabela}")).scalar()
            print(f"{tabela}: {n} linhas")


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    raw = ler_csvs(PASTA_CSV)
    stg = limpar(raw)
    print(f"raw: {len(raw)} linhas | stg (Pará, sem duplicados): {len(stg)} linhas")
    criar_schema(engine)
    carregar(engine, raw, stg)
    montar_dw(engine)
    conferir(engine)


if __name__ == "__main__":
    main()