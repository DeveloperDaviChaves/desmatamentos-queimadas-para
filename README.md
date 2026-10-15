# Desmatamento x focos de queimada no Pará

Pipeline de dados que integra o desmatamento (PRODES/INPE), os focos de queimada (BDQueimadas/INPE) e a malha municipal do Pará, e compara os fenômenos por ano e por município.

- **Fontes:** PRODES, camada "Amazônia Legal" (arquivo `yearly_deforestation_amazonia_legal_v20260717`); BDQueimadas, satélite AQUA_M-T; malha municipal do Pará de 2025 (144 municípios).
- **Período da comparação:** anos PRODES de 2009 a 2025.
- **Tecnologias:** Python 3.13, pandas, geopandas/pyogrio, SQLAlchemy, PostgreSQL, matplotlib, uv.

## Como funciona

```
CSVs (BDQueimadas)   ─┐
Shapefile (PRODES)   ─┼─►  raw  ─►  stg  ─►  dw  ─►  notebooks de gráficos
Malha municipal      ─┘          (cruzamento espacial por município)
```

| Camada | O que contém |
|---|---|
| `raw` | Cópia fiel dos arquivos, tudo como texto, sem filtro (`raw.queimadas`, `raw.desmatamento`). |
| `stg` | Dados limpos e tipados, só do Pará (`stg.focos_queimada`, `stg.desmatamento`). |
| `dw` | Dimensões (`dim_tempo`, `dim_municipio`), fatos por UF e ano (`fato_queimadas_uf`, `fato_queimadas_uf_prodes`, `fato_desmatamento_uf`), fatos por município e ano (`fato_desmatamento_municipio`, `fato_queimadas_municipio`) e as views `vw_comparativo_para_ano` e `vw_comparativo_municipio_ano`. |

## Estrutura do repositório

```
├── data/
│   ├── raw/
│   │   ├── queimadas_bdqueimadas/   # CSVs por ano + LEIAME.txt
│   │   ├── desmatamento_prodes/     # shapefile (.shp/.shx/.dbf/.prj) + LEIAME.txt
│   │   └── malha_municipal/         # malha dos municípios do Pará + LEIAME.txt
│   └── processed/
├── figuras/                         # gráficos gerados pelos notebooks
├── notebooks/
│   ├── graficos_comparativos.ipynb  # comparativo do estado por ano
│   └── analise_municipal.ipynb      # análise por município e mapas
├── sql/
│   └── schema_desmatamento_queimadas.sql
├── src/
│   ├── cargas_queimadas.py          # CSVs -> raw -> stg -> dw
│   ├── inspecionar_prodes.py        # inspeção dos atributos do shapefile
│   ├── cargas_desmatamento.py       # shapefile -> raw -> stg -> dw
│   ├── inspecionar_malha.py         # inspeção da malha municipal
│   └── cargas_municipais.py         # cruzamento com a malha -> dw (por município)
├── pyproject.toml
└── README.md
```

Os dados **não são versionados** (`.gitignore`). Cada pasta de `data/raw/` tem um `LEIAME.txt` com fonte, filtros usados e limitações.

## Como reproduzir

**1. Pré-requisitos:** Python 3.13, [uv](https://docs.astral.sh/uv/) e um PostgreSQL com um banco vazio.

**2. Dependências**
```
uv sync
```

**3. Conexão:** crie um arquivo `.env` na raiz (ele não vai para o GitHub):
```
DATABASE_URL=postgresql+psycopg2://USUARIO:SENHA@localhost:5432/NOME_DO_BANCO
```
Se a senha tiver caracteres especiais, codifique-os na URL (por exemplo, `@` vira `%40`).

**4. Dados**
- **Queimadas:** baixe em [BDQueimadas](https://terrabrasilis.dpi.inpe.br/queimadas/bdqueimadas/#exportar-dados) com país Brasil, estado Pará, o mesmo satélite em todos os anos (aqui, AQUA_M-T) e início em 01/01/2008. Salve um CSV por ano em `data/raw/queimadas_bdqueimadas/`, com nomes como `queimadas_2008.csv`.
- **Desmatamento:** baixe o shapefile do PRODES no [TerraBrasilis](https://terrabrasilis.dpi.inpe.br/) e coloque os quatro arquivos juntos em `data/raw/desmatamento_prodes/`.
- **Malha municipal:** coloque o shapefile dos municípios do Pará (`PA_Municipios_2025`) em `data/raw/malha_municipal/`.

**5. Execução** (sempre da raiz do projeto, nesta ordem)
```
uv run python src/cargas_queimadas.py
uv run python src/inspecionar_prodes.py     # opcional: conferir classes e anos
uv run python src/cargas_desmatamento.py
uv run python src/inspecionar_malha.py      # opcional: conferir a malha
uv run python src/cargas_municipais.py
```
Os scripts criam o esquema a partir de `sql/schema_desmatamento_queimadas.sql` e podem ser repetidos: cada execução refaz as tabelas. Os de desmatamento e de municípios imprimem conferências de totais ao final.

**6. Gráficos:** execute os notebooks em `notebooks/` (precisam de `matplotlib` e `ipykernel`). As imagens vão para `figuras/`.

## Decisões de projeto

- **Camada `raw` em texto.** A carga não quebra por vírgula decimal, formato de data ou codificação; a limpeza fica na `stg`.
- **Um único satélite.** Todos os focos vêm do AQUA_M-T, para a série ser comparável entre os anos.
- **Ano PRODES.** O PRODES considera o ano N como agosto de N-1 a julho de N. Os focos de agosto a dezembro foram atribuídos ao ano seguinte (`ano_prodes`). Por isso a comparação começa em 2009: o PRODES 2008 exigiria focos desde agosto de 2007.
- **2026 fora da comparação.** Os focos de 2026 (até 13/10) ficam na `stg`, mas não entram na `dw`: o ano está incompleto e o PRODES só vai até 2025.
- **Valor `-999`** nas colunas numéricas dos focos (sem informação) vira nulo.
- **Limpeza do PRODES.** Só o Pará (`state = 'PA'`) e só `main_class = 'DESMATAMENTO'`, que é a única classe do arquivo. Uma linha sem ano foi descartada. Não há `uuid` duplicado.
- **Duplicata nos focos.** Uma linha duplicada (2018) foi removida.
- **Desmatamento por município.** Cada polígono do PRODES é atribuído ao município que contém o seu ponto representativo; a área somada é a oficial (`area_km`). Um polígono que atravessa a divisa conta inteiro para um só município.
- **Focos por município.** Cada foco é atribuído ao município pelas coordenadas (e não pelo nome do município do CSV), com o mesmo critério usado no desmatamento.

## Resultados: estado do Pará por ano PRODES

| Ano | Área desmatada (km²) | Focos | Focos por km² |
|---|---:|---:|---:|
| 2009 | 3.542,3 | 46.029 | 13,0 |
| 2010 | 3.297,6 | 43.966 | 13,3 |
| 2011 | 2.508,1 | 55.088 | 22,0 |
| 2012 | 1.697,5 | 27.145 | 16,0 |
| 2013 | 2.099,9 | 36.702 | 17,5 |
| 2014 | 1.794,5 | 24.261 | 13,5 |
| 2015 | 2.302,8 | 35.952 | 15,6 |
| 2016 | 2.757,1 | 45.288 | 16,4 |
| 2017 | 2.572,6 | 29.972 | 11,7 |
| 2018 | 2.608,4 | 47.277 | 18,1 |
| 2019 | 4.463,5 | 22.339 | 5,0 |
| 2020 | 4.615,5 | 31.464 | 6,8 |
| 2021 | 5.079,3 | 37.542 | 7,4 |
| 2022 | 4.527,6 | 23.086 | 5,1 |
| 2023 | 2.881,1 | 42.125 | 14,6 |
| 2024 | 2.262,4 | 43.375 | 19,2 |
| 2025 | 1.951,6 | 52.941 | 27,1 |

- Em 2009–2025, a correlação entre área desmatada e focos é fraca e levemente negativa (Pearson −0,27; Spearman −0,09).
- Divididos em 2009–2017 e 2018–2025, os coeficientes de Pearson são +0,67 e −0,82. **Essa divisão é exploratória:** o corte foi escolhido depois de olhar os dados, e cada período tem só 8 ou 9 anos.
- Os anos de maior desmatamento (2019 a 2022) tiveram poucos focos; 2024 e 2025 tiveram muitos focos com pouco desmatamento.

## Validação com o painel oficial

Comparação dos incrementos anuais de desmatamento do Pará: nossa tabela (`dw.fato_desmatamento_uf`) contra o painel do TerraBrasilis.

| Ano | Nossa tabela (km²) | Painel (km²) | Diferença |
|---|---:|---:|---:|
| 2008 | 5.607,7 | 5.612,64 | -4,94 (-0,09%) |
| 2009 | 3.542,3 | 3.542,33 | -0,03 (-0,00%) |
| 2010 | 3.297,6 | 3.303,26 | -5,66 (-0,17%) |
| 2011 | 2.508,1 | 2.508,07 | 0,03 (0,00%) |
| 2012 | 1.697,5 | 1.697,69 | -0,19 (-0,01%) |
| 2013 | 2.099,9 | 2.099,28 | 0,62 (0,03%) |
| 2014 | 1.794,5 | 1.795,44 | -0,94 (-0,05%) |
| 2015 | 2.302,8 | 2.302,98 | -0,18 (-0,01%) |
| 2016 | 2.757,1 | 2.759,72 | -2,62 (-0,09%) |
| 2017 | 2.572,6 | 2.571,80 | 0,80 (0,03%) |
| 2018 | 2.608,4 | 2.607,76 | 0,64 (0,02%) |
| 2019 | 4.463,5 | 4.462,46 | 1,04 (0,02%) |
| 2020 | 4.615,5 | 4.614,81 | 0,69 (0,01%) |
| 2021 | 5.079,3 | 5.081,06 | -1,76 (-0,03%) |
| 2022 | 4.527,6 | 4.527,88 | -0,28 (-0,01%) |
| 2023 | 2.881,1 | 2.881,44 | -0,34 (-0,01%) |
| 2024 | 2.262,4 | 2.262,46 | -0,06 (-0,00%) |
| 2025 | 1.951,6 | 1.953,08 | -1,48 (-0,08%) |

- As 18 diferenças ficam abaixo de 0,2% em módulo; a maior é a de 2010 (−5,66 km², −0,17%).
- Soma de 2008 a 2025: 56.569,5 km² contra 56.584,16 km² no painel (diferença de -14,66 km², -0,03%).
- O acumulado do painel é de 174.532 km² (34,69%); a soma de 2008–2025 equivale a cerca de 32% disso, o que é plausível, já que o acumulado cobre um período maior.
- Possíveis fontes das diferenças pequenas: versão do dado, arredondamento e a linha sem ano descartada na limpeza.

## Resultados: municípios

**Cruzamento.** 108 polígonos do PRODES (0,03% da área) e 60 focos (0,01%) ficaram sem município. A soma dos municípios fica no máximo 4,6 km² abaixo do total do estado em cada ano (desmatamento) e 1 a 7 focos abaixo (queimadas).

**Os 10 municípios que mais desmataram em 2009–2025:**

| Município | Desmatamento (km²) | % do território | Focos | Focos por km² desmatado |
|---|---:|---:|---:|---:|
| Altamira | 6.398,3 | 4,0% | 53.378 | 8,3 |
| São Félix do Xingu | 5.393,9 | 6,4% | 67.553 | 12,5 |
| Novo Progresso | 2.799,1 | 7,3% | 32.435 | 11,6 |
| Pacajá | 2.710,3 | 22,9% | 17.677 | 6,5 |
| Itaituba | 2.609,4 | 4,2% | 24.154 | 9,3 |
| Novo Repartimento | 2.432,5 | 15,8% | 13.587 | 5,6 |
| Portel | 2.204,7 | 8,7% | 17.536 | 8,0 |
| Uruará | 1.541,3 | 14,3% | 10.722 | 7,0 |
| Anapu | 1.495,6 | 12,6% | 8.196 | 5,5 |
| Senador José Porfírio | 1.339,2 | 9,3% | 6.475 | 4,8 |

- **Concentração:** 10 dos 144 municípios reúnem 57% do desmatamento do estado no período (cerca de 67% com os 15 maiores) e cerca de 39% dos focos.
- **Entre municípios:** a correlação de Spearman entre desmatamento e focos acumulados é de +0,88 (n = 143). Esse número mistura relação com tamanho do município, porque municípios grandes têm mais de tudo; ele não deve ser lido como prova de que o desmatamento causa fogo.
- **Dentro de cada município, ao longo dos anos:** entre os 15 maiores, a correlação de Spearman vai de +0,60 (Novo Repartimento) a −0,33 (Rurópolis); 11 são positivas ou próximas de zero e 4 são negativas. Com 17 anos por município, só valores acima de cerca de 0,5 se distinguem do acaso, e isso vale para poucos municípios.
- **Mapas:** o desmatamento acumulado se concentra no centro-sul do estado, enquanto os focos por 100 km² de território são mais altos no nordeste paraense, onde há muitos municípios pequenos e pouco desmatamento novo. Isso sugere fogo com outras origens, mas essa é uma hipótese que os dados não testam.

Os gráficos estão em `figuras/`.

## Limitações

- Foco de calor mede ocorrência de fogo, não área queimada nem desmatamento. Um mesmo incêndio pode gerar vários focos, e a contagem depende do satélite, do horário de passagem e das nuvens.
- O PRODES registra apenas desmatamento acima de 6,25 hectares. Além disso, o ano atribuído a cada polígono é o do PRODES e não a data exata do desmatamento: há polígonos sob nuvem em anos anteriores (coluna `def_cloud`).
- O fogo no estado inclui pasto, lavoura, manejo e floresta em pé, e não apenas queima associada a desmatamento novo.
- Com 17 anos, os coeficientes de correlação descrevem estes dados; não demonstram relação de causa.
- A malha municipal é a de 2025 e vale para todos os anos: municípios criados ou alterados na série ficam com os limites atuais.
- Na atribuição por município, um polígono do PRODES que atravessa a divisa conta inteiro para um só município.
- 2017 tem um salto nos focos em relação a 2016 e 2018 que ainda não foi investigado.

## Próximos passos

- Registrar o resultado da comparação entre municípios em proporção ao tamanho (percentual do território desmatado contra focos por 100 km²), que descarta o efeito do tamanho.
- Testar a hipótese de seca usando `DiaSemChuva`, `RiscoFogo` e `FRP`.
- Investigar o salto de focos em 2017.

## Fontes

- INPE, PRODES (TerraBrasilis): <https://terrabrasilis.dpi.inpe.br/>
- INPE, Programa Queimadas (BDQueimadas): <https://terrabrasilis.dpi.inpe.br/queimadas/bdqueimadas/>