"""Carga do desmatamento (PRODES) no PostgreSQL: shapefile -> raw -> stg -> dw.

Uso (na raiz do projeto, depois de rodar src/inspecionar_prodes.py):
    uv run python src/cargas_desmatamento.py

Lê só a tabela de atributos do shapefile (a geometria não é necessária para somar área).
Pode ser rodado várias vezes: cada execução refaz as tabelas de desmatamento.
"""
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from pyogrio import read_dataframe
from sqlalchemy import create_engine, text

load_dotenv()

ARQUIVO_SHP = Path("data/raw/desmatamento_prodes/yearly_deforestation_amazonia_legal_v20260717.shp")
UF_ALVO = "PA"
CLASSES_DESMATAMENTO = ["DESMATAMENTO"]  # valores de main_class que entram na soma (confirmar na inspeção)
ANO_INICIAL = 2008
ANO_FINAL = 2025  # mesmo recorte das queimadas

COLUNAS_RAW = [
    "fid", "state", "path_row", "main_class", "class_name", "sub_class", "def_cloud",
    "julian_day", "image_date", "year", "area_km", "scene_id", "source",
    "satellite", "sensor", "uuid",
]


def ler_atributos() -> pd.DataFrame:
    df = read_dataframe(ARQUIVO_SHP, read_geometry=False)
    faltando = set(COLUNAS_RAW) - set(df.columns)
    if faltando:
        raise ValueError(f"Faltam colunas no shapefile: {sorted(faltando)}")
    return df[COLUNAS_RAW]


def para_raw(df: pd.DataFrame) -> pd.DataFrame:
    """Camada raw: tudo como texto, sem filtro."""
    raw = df.astype("string")
    raw["arquivo_origem"] = ARQUIVO_SHP.name
    return raw


def limpar(df: pd.DataFrame) -> pd.DataFrame:
    """Camada stg: só o UF alvo, só as classes de desmatamento, tipos corretos."""
    d = df.copy()
    d["state"] = d["state"].astype("string").str.strip().str.upper()
    d = d[d["state"] == UF_ALVO].copy()

    d["area_num"] = pd.to_numeric(d["area_km"], errors="coerce")
    print(f"\n{UF_ALVO} por main_class (polígonos e área km²):")
    print(d.groupby("main_class")["area_num"].agg(["count", "sum"]).round(1))

    classes = [c.upper() for c in CLASSES_DESMATAMENTO]
    d = d[d["main_class"].astype("string").str.strip().str.upper().isin(classes)].copy()

    d["ano"] = pd.to_numeric(d["year"], errors="coerce")
    n_antes = len(d)
    d = d.dropna(subset=["ano", "area_num"])
    d = d[d["area_num"] >= 0]
    if len(d) < n_antes:
        print(f"descartadas {n_antes - len(d)} linhas sem ano/área válidos")

    n_antes = len(d)
    d = d[~(d["uuid"].notna() & d.duplicated(subset=["uuid"]))]
    if len(d) < n_antes:
        print(f"descartados {n_antes - len(d)} uuid duplicados")

    stg = pd.DataFrame({
        "fid": pd.to_numeric(d["fid"], errors="coerce").astype("Int32"),
        "ano": d["ano"].astype("int16"),
        "uf": d["state"],
        "classe": d["main_class"],
        "classe_nome": d["class_name"],
        "data_imagem": pd.to_datetime(d["image_date"], errors="coerce"),
        "area_km2": d["area_num"],
        "uuid": d["uuid"],
    })
    print("data_imagem sem data válida:", int(stg["data_imagem"].isna().sum()))
    return stg


def carregar(engine, raw: pd.DataFrame, stg: pd.DataFrame) -> None:
    with engine.begin() as con:
        con.execute(text("TRUNCATE raw.desmatamento"))
        con.execute(text("TRUNCATE stg.desmatamento RESTART IDENTITY"))
    raw.to_sql("desmatamento", engine, schema="raw", if_exists="append",
               index=False, method="multi", chunksize=5000)
    stg.to_sql("desmatamento", engine, schema="stg", if_exists="append",
               index=False, method="multi", chunksize=5000)


def montar_dw(engine) -> None:
    """Camada dw: área desmatada (km²) por UF e ano."""
    params = {"ini": ANO_INICIAL, "fim": ANO_FINAL}
    with engine.begin() as con:
        con.execute(text(
            "INSERT INTO dw.dim_tempo (ano) SELECT DISTINCT ano FROM stg.desmatamento "
            "WHERE ano BETWEEN :ini AND :fim ON CONFLICT DO NOTHING"), params)
        con.execute(text("TRUNCATE dw.fato_desmatamento_uf"))
        con.execute(text(
            "INSERT INTO dw.fato_desmatamento_uf (ano, uf, area_km2) "
            "SELECT ano, uf, SUM(area_km2) FROM stg.desmatamento "
            "WHERE ano BETWEEN :ini AND :fim GROUP BY ano, uf"), params)


def conferir(engine) -> None:
    with engine.connect() as con:
        for tabela in ("raw.desmatamento", "stg.desmatamento", "dw.fato_desmatamento_uf"):
            n = con.execute(text(f"SELECT COUNT(*) FROM {tabela}")).scalar()
            print(f"{tabela}: {n} linhas")
        print("\nComparativo do Pará por ano (dw.vw_comparativo_para_ano):")
        linhas = con.execute(text(
            "SELECT ano, ROUND(area_desmatada_km2, 1), qtd_focos FROM dw.vw_comparativo_para_ano")).all()
        print(pd.DataFrame(linhas, columns=["ano", "area_desmatada_km2", "qtd_focos"]).to_string(index=False))


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    df = ler_atributos()
    print(f"shapefile: {len(df)} polígonos (todos os estados)")
    stg = limpar(df)
    print(f"stg ({UF_ALVO}, classes {CLASSES_DESMATAMENTO}): {len(stg)} linhas")
    carregar(engine, para_raw(df), stg)
    montar_dw(engine)
    conferir(engine)


if __name__ == "__main__":
    main()