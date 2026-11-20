"""Chuva mensal do CHIRPS por município e para o Pará.

Uso (na raiz do projeto):
    uv add rasterio
    uv run python src/chuva_chirps.py

O que faz:
  1. Para cada mês de ANO_INICIAL a ANO_FINAL, baixa o GeoTIFF mensal global do CHIRPS
     (Climate Hazards Center, UCSB), lê só a janela do Pará e apaga o arquivo baixado.
  2. Calcula a chuva média (mm no mês) de cada município e do estado, usando a malha municipal.
  3. Grava data/processed/chuva_chirps_mensal.csv (colunas: nivel, cod_ibge, ano, mes, chuva_mm, n_pixels).
Retoma de onde parou: meses que já estão no CSV não são baixados de novo.

ATENÇÃO: confira no navegador se o primeiro e o último mês existem na URL abaixo antes de rodar.
Se os meses mais recentes não existirem nessa versão, use o caminho da versão mais nova no
site do Climate Hazards Center e ajuste URLS.
"""
import time
import urllib.request
from pathlib import Path
from urllib.error import URLError

import numpy as np
import pandas as pd

URLS = [
    "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/tifs/chirps-v3.0.{ano}.{mes:02d}.tif",
    "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/tifs/chirps-v3.0.{ano}.{mes:02d}.tif",
]
ANO_INICIAL, ANO_FINAL = 2008, 2025
MALHA = Path("data/raw/malha_municipal_para/PA_Municipios_2025.shp")
SAIDA = Path("data/processed/chuva_chirps_mensal.csv")
PASTA_TEMP = Path("data/processed/_chirps_tmp")
MARGEM_GRAUS = 0.1


def medias_por_zona(dados: np.ndarray, zonas: np.ndarray, n_zonas: int, sem_dado: float = -9999.0):
    """Média de `dados` dentro de cada zona (1..n_zonas); zona 0 é fora da malha.

    Devolve (médias, contagens) com n_zonas + 1 posições (a posição 0 é ignorada).
    Pixels sem dado (-9999 ou NaN) ficam de fora."""
    valido = (zonas > 0) & np.isfinite(dados) & (dados != sem_dado)
    contagem = np.bincount(zonas[valido], minlength=n_zonas + 1)
    soma = np.bincount(zonas[valido], weights=dados[valido].astype("float64"), minlength=n_zonas + 1)
    medias = np.full(n_zonas + 1, np.nan)
    tem = contagem > 0
    medias[tem] = soma[tem] / contagem[tem]
    return medias, contagem


def baixar(ano: int, mes: int, destino: Path) -> Path:
    ultimo_erro = None
    for modelo in URLS:
        url = modelo.format(ano=ano, mes=mes)
        arquivo = destino / Path(url).name
        for tentativa in range(3):
            try:
                urllib.request.urlretrieve(url, arquivo)
                return arquivo
            except (URLError, OSError) as erro:
                ultimo_erro = erro
                time.sleep(2 * (tentativa + 1))
    raise RuntimeError(f"Não consegui baixar {ano}-{mes:02d}: {ultimo_erro}")


def preparar_zonas(src, malha):
    """Janela do Pará no raster e uma grade com o índice (1..n) do município de cada pixel."""
    from rasterio.features import rasterize
    from rasterio.windows import from_bounds, transform as transform_janela

    minx, miny, maxx, maxy = malha.total_bounds
    janela = from_bounds(minx - MARGEM_GRAUS, miny - MARGEM_GRAUS,
                         maxx + MARGEM_GRAUS, maxy + MARGEM_GRAUS, src.transform)
    janela = janela.round_offsets().round_lengths()
    transf = transform_janela(janela, src.transform)
    formas = ((geom, i + 1) for i, geom in enumerate(malha.geometry))
    zonas = rasterize(formas, out_shape=(int(janela.height), int(janela.width)),
                      transform=transf, fill=0, dtype="int32")
    return janela, zonas


def main() -> None:
    import geopandas as gpd
    import rasterio

    malha = gpd.read_file(MALHA)[["CD_MUN", "geometry"]]
    malha = malha.to_crs(4326).reset_index(drop=True)
    codigos = malha["CD_MUN"].astype(int).to_numpy()
    n = len(malha)

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    PASTA_TEMP.mkdir(parents=True, exist_ok=True)
    feitos = set()
    if SAIDA.exists():
        antigos = pd.read_csv(SAIDA, usecols=["ano", "mes"]).drop_duplicates()
        feitos = set(zip(antigos["ano"], antigos["mes"]))
    print(f"{len(feitos)} meses já gravados")

    janela = zonas = None
    for ano in range(ANO_INICIAL, ANO_FINAL + 1):
        for mes in range(1, 13):
            if (ano, mes) in feitos:
                continue
            arquivo = baixar(ano, mes, PASTA_TEMP)
            caminho = f"/vsigzip/{arquivo}" if arquivo.suffix == ".gz" else str(arquivo)
            with rasterio.open(caminho) as src:
                if zonas is None:
                    janela, zonas = preparar_zonas(src, malha)
                    print("janela do Pará:", int(janela.height), "x", int(janela.width), "pixels")
                dados = src.read(1, window=janela, masked=False).astype("float64")
                sem_dado = src.nodata if src.nodata is not None else -9999.0
            arquivo.unlink(missing_ok=True)

            medias, contagem = medias_por_zona(dados, zonas, n, sem_dado)
            linhas = [{"nivel": "municipio", "cod_ibge": int(codigos[i]), "ano": ano, "mes": mes,
                       "chuva_mm": medias[i + 1], "n_pixels": int(contagem[i + 1])} for i in range(n)]
            total = contagem[1:].sum()
            media_estado = np.nansum(medias[1:] * contagem[1:]) / total if total else np.nan
            linhas.append({"nivel": "estado", "cod_ibge": 0, "ano": ano, "mes": mes,
                           "chuva_mm": media_estado, "n_pixels": int(total)})
            pd.DataFrame(linhas).to_csv(SAIDA, mode="a", index=False, header=not SAIDA.exists())
            print(f"{ano}-{mes:02d}: estado {media_estado:.1f} mm")

    print("pronto:", SAIDA)


if __name__ == "__main__":
    main()
