Desmatamento x focos de queimada no Pará

Pipeline de dados que integra o desmatamento (PRODES/INPE) e os focos de queimada (BDQueimadas/INPE) no Pará e compara os dois fenômenos ano a ano.

Fontes: PRODES, camada "Amazônia Legal" (arquivo yearly_deforestation_amazonia_legal_v20260717), e BDQueimadas, satélite AQUA_M-T.
Período da comparação: anos PRODES de 2009 a 2025.
Tecnologias: Python 3.13, pandas, geopandas/pyogrio, SQLAlchemy, PostgreSQL, matplotlib, uv.
Como funciona
CSVs (BDQueimadas)   ─┐
                      ├─►  raw  ─►  stg  ─►  dw  ─►  notebook de gráficos
Shapefile (PRODES)   ─┘
Camada	O que contém
raw	Cópia fiel dos arquivos, tudo como texto, sem filtro (raw.queimadas, raw.desmatamento).
stg	Dados limpos e tipados, só do Pará (stg.focos_queimada, stg.desmatamento).
dw	Dimensão de tempo e fatos por UF e ano (fato_queimadas_uf, fato_queimadas_uf_prodes, fato_desmatamento_uf) e a view vw_comparativo_para_ano.

As tabelas de município (dim_municipio e os fatos por município) já existem no esquema, mas ainda não são carregadas (veja "Próximos passos").

Estrutura do repositório
├── data/
│   ├── raw/
│   │   ├── queimadas_bdqueimadas/   # CSVs por ano + LEIAME.txt
│   │   └── desmatamento_prodes/     # shapefile (.shp/.shx/.dbf/.prj) + LEIAME.txt
│   └── processed/
├── figuras/                         # gráficos gerados pelo notebook
├── notebooks/
│   └── graficos_comparativo.ipynb
├── sql/
│   └── schema_desmatamento_queimadas.sql
├── src/
│   ├── cargas_queimadas.py          # CSVs -> raw -> stg -> dw
│   ├── inspecionar_prodes.py        # inspeção dos atributos do shapefile
│   └── cargas_desmatamento.py       # shapefile -> raw -> stg -> dw
├── pyproject.toml
└── README.md

Os dados não são versionados (.gitignore). Cada pasta de data/raw/ tem um LEIAME.txt com fonte, filtros usados e limitações.

Como reproduzir

1. Pré-requisitos: Python 3.13, uv e um PostgreSQL com um banco vazio.

2. Dependências

uv sync

3. Conexão: crie um arquivo .env na raiz (ele não vai para o GitHub):

DATABASE_URL=postgresql+psycopg2://USUARIO:SENHA@localhost:5432/NOME_DO_BANCO

Se a senha tiver caracteres especiais, codifique-os na URL (por exemplo, @ vira %40).

4. Dados

Queimadas: baixe em BDQueimadas com país Brasil, estado Pará, o mesmo satélite em todos os anos (aqui, AQUA_M-T) e início em 01/01/2008. Salve um CSV por ano em data/raw/queimadas_bdqueimadas/, com nomes como queimadas_2008.csv.
Desmatamento: baixe o shapefile do PRODES no TerraBrasilis e coloque os quatro arquivos juntos em data/raw/desmatamento_prodes/.

5. Execução (sempre da raiz do projeto, nesta ordem)

uv run python src/cargas_queimadas.py
uv run python src/inspecionar_prodes.py     # opcional: conferir classes e anos
uv run python src/cargas_desmatamento.py

Os scripts criam o esquema a partir de sql/schema_desmatamento_queimadas.sql e podem ser repetidos: cada execução refaz as tabelas. Ao final, o de desmatamento imprime a tabela comparativa do Pará.

6. Gráficos: abra notebooks/graficos_comparativo.ipynb (precisa de matplotlib e ipykernel) e execute as células. As imagens vão para figuras/.

Decisões de projeto
Camada raw em texto. A carga não quebra por vírgula decimal, formato de data ou codificação; a limpeza fica na stg.
Um único satélite. Todos os focos vêm do AQUA_M-T, para a série ser comparável entre os anos.
Ano PRODES. O PRODES considera o ano N como agosto de N-1 a julho de N. Os focos de agosto a dezembro foram atribuídos ao ano seguinte (ano_prodes). Por isso a comparação começa em 2009: o PRODES 2008 exigiria focos desde agosto de 2007.
2026 fora da comparação. Os focos de 2026 (até 13/10) ficam na stg, mas não entram na dw: o ano está incompleto e o PRODES só vai até 2025.
Valor -999 nas colunas numéricas dos focos (sem informação) vira nulo.
Limpeza do PRODES. Só o Pará (state = 'PA') e só main_class = 'DESMATAMENTO', que é a única classe do arquivo. Uma linha sem ano foi descartada. Não há uuid duplicado.
Duplicata nos focos. Uma linha duplicada (2018) foi removida.
Geometria não é carregada na etapa de soma de área: basta a coluna area_km.
Resultados (descritivos)

Área desmatada (PRODES) e focos de queimada (BDQueimadas) no Pará, por ano PRODES:

Ano	Área desmatada (km²)	Focos	Focos por km²
2009	3.542,3	46.029	13,0
2010	3.297,6	43.966	13,3
2011	2.508,1	55.088	22,0
2012	1.697,5	27.145	16,0
2013	2.099,9	36.702	17,5
2014	1.794,5	24.261	13,5
2015	2.302,8	35.952	15,6
2016	2.757,1	45.288	16,4
2017	2.572,6	29.972	11,7
2018	2.608,4	47.277	18,1
2019	4.463,5	22.339	5,0
2020	4.615,5	31.464	6,8
2021	5.079,3	37.542	7,4
2022	4.527,6	23.086	5,1
2023	2.881,1	42.125	14,6
2024	2.262,4	43.375	19,2
2025	1.951,6	52.941	27,1
Em 2009–2025, a correlação entre área desmatada e focos é fraca e levemente negativa (Pearson −0,27; Spearman −0,09).
Divididos em 2009–2017 e 2018–2025, os coeficientes de Pearson são +0,67 e −0,82. Essa divisão é exploratória: o corte foi escolhido depois de olhar os dados, e cada período tem só 8 ou 9 anos.
Os anos de maior desmatamento (2019 a 2022) tiveram poucos focos; 2024 e 2025 tiveram muitos focos com pouco desmatamento.

Os gráficos estão em figuras/: série por ano, dispersão e focos por km² desmatado.

Validação
A soma do desmatamento do Pará no arquivo (2008–2025) é de cerca de 56,6 mil km². O acumulado consultado no painel do TerraBrasilis é de 174.532 km² (34,69%); a soma de 2008–2025 equivale a cerca de 32% disso, o que é plausível. O acumulado cobre um período maior, então não substitui a conferência ano a ano.
Pendente: comparar as taxas anuais do painel oficial com a tabela acima.
Limitações
Foco de calor mede ocorrência de fogo, não área queimada nem desmatamento. Um mesmo incêndio pode gerar vários focos, e a contagem depende do satélite, do horário de passagem e das nuvens.
O PRODES registra apenas desmatamento acima de 6,25 hectares. Além disso, o ano atribuído a cada polígono é o do PRODES e não a data exata do desmatamento: há polígonos sob nuvem em anos anteriores (coluna def_cloud).
A comparação é feita para o estado inteiro. O fogo no estado inclui pasto, lavoura, manejo e floresta em pé, e não apenas queima associada a desmatamento novo.
Com 17 anos, os coeficientes de correlação descrevem estes dados; não demonstram relação de causa.
2017 tem um salto nos focos em relação a 2016 e 2018 que ainda não foi investigado.
Próximos passos
Conferir as taxas anuais do PRODES com o painel oficial.
Análise por município: cruzar os polígonos do PRODES com a malha municipal do IBGE (o PRODES não traz município) e comparar com os focos de cada município.
Testar a hipótese de seca usando DiaSemChuva, RiscoFogo e FRP.
Investigar o salto de focos em 2017.
Fontes
INPE, PRODES (TerraBrasilis): https://terrabrasilis.dpi.inpe.br/
INPE, Programa Queimadas (BDQueimadas): https://terrabrasilis.dpi.inpe.br/queimadas/bdqueimadas/