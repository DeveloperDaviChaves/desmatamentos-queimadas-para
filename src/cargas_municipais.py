"""Análise por município: cruza PRODES e focos de queimada com a malha municipal do Pará.

Uso (na raiz do projeto, depois de cargas_queimadas.py e cargas_desmatamento.py):
    uv run python src/cargas_municipios.py

O que faz:
  1. Grava a dimensão dw.dim_municipio a partir da malha (código IBGE, nome, área).
  2. Atribui cada polígono do PRODES ao município que contém o seu ponto representativo
     (a área usada é a coluna area_km do PRODES) e grava dw.fato_desmatamento_municipio.
  3. Atribui cada foco de queimada ao município pelas coordenadas e grava
     dw.fato_queimadas_municipio (a coluna "ano" é o ano PRODES: ago/(N-1) a jul/N).
  4. Confere se a soma dos municípios fecha com os totais do estado.
Pode ser repetido: cada execução refaz as tabelas de município.
"""
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
from dotenv import load_dotenv
from pyogrio import read_dataframe
from sqlalchemy import create_engine, text

load_dotenv()

ARQUIVO_MALHA = Path("data/raw/malha_municipal_para/PA_Municipios_2025.shp")
ARQUIVO_PRODES = Path("data/raw/desmatamento_prodes/yearly_deforestation_amazonia_legal_v20260717.shp")
ARQUIVO_SCHEMA = Path("sql/schema_desmatamento_queimadas.sql")

UF_ALVO = "PA"
CLASSES_DESMATAMENTO = ["DESMATAMENTO"]
ANO_INICIAL_DESMAT = 2008   # mesmo recorte de dw.fato_desmatamento_uf
ANO_PRODES_INICIAL = 2009   # focos: PRODES 2008 exigiria focos desde ago/2007
ANO_FINAL = 2025
CRS_ALVO = 4674             # SIRGAS 2000, o mesmo do PRODES


def criar_schema(engine) -> None:
    sql = ARQUIVO_SCHEMA.read_text(encoding="utf-8")
    if not sql.strip():
        raise RuntimeError(f"{ARQUIVO_SCHEMA} está vazio: cole o conteúdo do schema nele")
    conn = engine.raw_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


def ler_malha() -> gpd.GeoDataFrame:
    malha = gpd.read_file(ARQUIVO_MALHA)[["CD_MUN", "NM_MUN", "SIGLA_UF", "AREA_KM2", "geometry"]]
    if malha.crs is None or malha.crs.to_epsg() != CRS_ALVO:
        malha = malha.to_crs(CRS_ALVO)
    malha["cod_ibge"] = malha["CD_MUN"].astype(int)
    print(f"malha: {len(malha)} municípios")
    return malha


def atribuir_municipio(pontos: gpd.GeoDataFrame, malha: gpd.GeoDataFrame) -> pd.Series:
    """Devolve o cod_ibge do município de cada ponto (NaN quando cai fora da malha)."""
    juncao = gpd.sjoin(pontos[["geometry"]], malha[["cod_ibge", "geometry"]],
                       how="left", predicate="within")
    juncao = juncao[~juncao.index.duplicated(keep="first")]
    return juncao["cod_ibge"]


def desmatamento_por_municipio(malha: gpd.GeoDataFrame) -> pd.DataFrame:
    d = read_dataframe(ARQUIVO_PRODES, where=f"state = '{UF_ALVO}'",
                   columns=["fid", "state", "main_class", "year", "area_km"])
    print(f"PRODES {UF_ALVO}: {len(d)} polígonos lidos")
    if d.empty:
        raise RuntimeError("Nenhum polígono do PRODES lido: confira o filtro state e as colunas pedidas")

    classes = [c.upper() for c in CLASSES_DESMATAMENTO]
    d = d[d["main_class"].astype("string").str.strip().str.upper().isin(classes)].copy()
    d["ano"] = pd.to_numeric(d["year"], errors="coerce")
    d["area_km2"] = pd.to_numeric(d["area_km"], errors="coerce")
    d = d.dropna(subset=["ano", "area_km2"])
    d = d[(d["ano"] >= ANO_INICIAL_DESMAT) & (d["ano"] <= ANO_FINAL)].copy()
    d["ano"] = d["ano"].astype("int16")

    if (~d.geometry.is_valid).any():
        d["geometry"] = d.geometry.make_valid()
    d["geometry"] = d.geometry.representative_point()
    d["cod_ibge"] = atribuir_municipio(d, malha)

    sem = d["cod_ibge"].isna()
    pct = 100 * d.loc[sem, "area_km2"].sum() / d["area_km2"].sum()
    print(f"polígonos sem município: {int(sem.sum())} ({pct:.2f}% da área)")

    return (d.dropna(subset=["cod_ibge"])
             .groupby(["ano", "cod_ibge"], as_index=False)["area_km2"].sum())


def focos_por_municipio(engine, malha: gpd.GeoDataFrame) -> pd.DataFrame:
    f = pd.read_sql(
        text("SELECT ano_prodes, latitude, longitude, frp FROM stg.focos_queimada "
             "WHERE estado = 'PARÁ' AND ano_prodes BETWEEN :ini AND :fim"),
        engine, params={"ini": ANO_PRODES_INICIAL, "fim": ANO_FINAL})
    for col in ("latitude", "longitude", "frp"):
        f[col] = pd.to_numeric(f[col], errors="coerce")
    f = f.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    print(f"focos {UF_ALVO}: {len(f)} lidos")

    pontos = gpd.GeoDataFrame(f, geometry=gpd.points_from_xy(f["longitude"], f["latitude"]),
                              crs=CRS_ALVO)
    pontos["cod_ibge"] = atribuir_municipio(pontos, malha)

    sem = pontos["cod_ibge"].isna()
    print(f"focos sem município: {int(sem.sum())} ({100 * sem.mean():.2f}%)")

    return (pontos.dropna(subset=["cod_ibge"])
                  .groupby(["ano_prodes", "cod_ibge"], as_index=False)
                  .agg(qtd_focos=("frp", "size"), frp_total=("frp", lambda s: s.sum(min_count=1)))
                  .rename(columns={"ano_prodes": "ano"}))


def gravar(engine, malha, fato_d, fato_q) -> None:
    with engine.begin() as con:
        con.execute(text(
            "INSERT INTO dw.dim_tempo (ano) SELECT generate_series(:ini, :fim) ON CONFLICT DO NOTHING"),
            {"ini": ANO_INICIAL_DESMAT, "fim": ANO_FINAL})
        con.execute(text(
            "TRUNCATE dw.fato_desmatamento_municipio, dw.fato_queimadas_municipio, "
            "dw.dim_municipio RESTART IDENTITY"))

    dim = pd.DataFrame({"cod_ibge": malha["cod_ibge"], "nome": malha["NM_MUN"],
                        "uf": malha["SIGLA_UF"], "area_km2": malha["AREA_KM2"]})
    dim.to_sql("dim_municipio", engine, schema="dw", if_exists="append", index=False)

    ids = pd.read_sql(text("SELECT id_municipio, cod_ibge FROM dw.dim_municipio"), engine)
    mapa = dict(zip(ids["cod_ibge"], ids["id_municipio"]))

    fato_d = fato_d.assign(id_municipio=fato_d["cod_ibge"].astype(int).map(mapa))
    fato_d[["ano", "id_municipio", "area_km2"]].to_sql(
        "fato_desmatamento_municipio", engine, schema="dw", if_exists="append", index=False)

    fato_q = fato_q.assign(id_municipio=fato_q["cod_ibge"].astype(int).map(mapa))
    fato_q[["ano", "id_municipio", "qtd_focos", "frp_total"]].to_sql(
        "fato_queimadas_municipio", engine, schema="dw", if_exists="append", index=False)


def conferir(engine) -> None:
    pd.set_option("display.width", 200)
    with engine.connect() as con:
        for tabela in ("dw.dim_municipio", "dw.fato_desmatamento_municipio", "dw.fato_queimadas_municipio"):
            n = con.execute(text(f"SELECT COUNT(*) FROM {tabela}")).scalar()
            print(f"{tabela}: {n} linhas")

        print("\nDesmatamento: total do estado x soma dos municípios (km²)")
        print(pd.read_sql(text(
            "SELECT u.ano, ROUND(u.area_km2, 1) AS estado, ROUND(m.area_km2, 1) AS municipios, "
            "ROUND(u.area_km2 - m.area_km2, 1) AS diferenca "
            "FROM dw.fato_desmatamento_uf u "
            "JOIN (SELECT ano, SUM(area_km2) AS area_km2 FROM dw.fato_desmatamento_municipio GROUP BY ano) m "
            "USING (ano) WHERE u.uf = 'PA' ORDER BY u.ano"), con).to_string(index=False))

        print("\nFocos: total do estado x soma dos municípios (ano PRODES)")
        print(pd.read_sql(text(
            "SELECT u.ano_prodes AS ano, u.qtd_focos AS estado, m.qtd_focos AS municipios, "
            "u.qtd_focos - m.qtd_focos AS diferenca "
            "FROM dw.fato_queimadas_uf_prodes u "
            "JOIN (SELECT ano, SUM(qtd_focos) AS qtd_focos FROM dw.fato_queimadas_municipio GROUP BY ano) m "
            "ON m.ano = u.ano_prodes WHERE u.uf = 'PA' ORDER BY u.ano_prodes"), con).to_string(index=False))

        print("\n10 municípios com mais desmatamento (2009-2025)")
        print(pd.read_sql(text(
            "SELECT municipio, ROUND(SUM(area_desmatada_km2), 1) AS desmatamento_km2, "
            "SUM(qtd_focos) AS focos FROM dw.vw_comparativo_municipio_ano "
            "GROUP BY municipio ORDER BY 2 DESC LIMIT 10"), con).to_string(index=False))


def main() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    criar_schema(engine)
    malha = ler_malha()
    fato_d = desmatamento_por_municipio(malha)
    fato_q = focos_por_municipio(engine, malha)
    gravar(engine, malha, fato_d, fato_q)
    conferir(engine)


if __name__ == "__main__":
    main()