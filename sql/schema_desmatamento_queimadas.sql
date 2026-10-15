-- =====================================================================
-- Projeto: Desmatamento x Focos de Queimadas no Pará
-- Banco: PostgreSQL
-- Fontes: PRODES (Amazônia Legal, v20260717) e BDQueimadas (INPE)
--
-- Colunas baseadas na inspeção real dos arquivos.
-- Fase 1 (MVP): comparação por UF e ano PRODES (ago-jul) no Pará.
-- Fase 2: comparação por município (exige cruzamento espacial do PRODES
--         com a malha municipal do IBGE, pois o PRODES não traz município).
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS raw;   -- dados como vieram (tudo texto)
CREATE SCHEMA IF NOT EXISTS stg;   -- dados limpos e tipados
CREATE SCHEMA IF NOT EXISTS dw;    -- modelo final para análise

-- ---------------------------------------------------------------------
-- 1) RAW: cópia fiel dos arquivos, tudo em TEXT.
--    A ordem das colunas segue o CSV do BDQueimadas.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.queimadas (
    data_hora       TEXT,   -- formato 'AAAA/MM/DD HH:MM:SS' (UTC)
    satelite        TEXT,
    pais            TEXT,
    estado          TEXT,   -- ex.: 'PARÁ' (maiúsculas, com acento)
    municipio       TEXT,
    bioma           TEXT,
    dia_sem_chuva   TEXT,   -- atenção: -999 significa "sem informação"
    precipitacao    TEXT,
    risco_fogo      TEXT,
    frp             TEXT,
    latitude        TEXT,
    longitude       TEXT,
    arquivo_origem  TEXT,
    carregado_em    TIMESTAMP DEFAULT now()
);

-- Atributos do shapefile PRODES (a coluna geometry NÃO é carregada aqui).
CREATE TABLE IF NOT EXISTS raw.desmatamento (
    fid             TEXT,
    state           TEXT,   -- sigla da UF (ex.: 'PA', 'MT')
    path_row        TEXT,
    main_class      TEXT,
    class_name      TEXT,
    sub_class       TEXT,
    def_cloud       TEXT,
    julian_day      TEXT,
    image_date      TEXT,
    year            TEXT,
    area_km         TEXT,
    scene_id        TEXT,
    source          TEXT,
    satellite       TEXT,
    sensor          TEXT,
    uuid            TEXT,
    arquivo_origem  TEXT,
    carregado_em    TIMESTAMP DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 2) STG: tipos corretos, nomes padronizados.
--    Regras: -999 em dia_sem_chuva vira NULL; filtrar estado = 'PARÁ'
--    (queimadas) e state = 'PA' (desmatamento) na carga para o DW.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stg.focos_queimada (
    id_foco        BIGSERIAL PRIMARY KEY,
    data_hora      TIMESTAMP NOT NULL,
    ano            SMALLINT NOT NULL,
    mes            SMALLINT NOT NULL CHECK (mes BETWEEN 1 AND 12),
    ano_prodes     SMALLINT,          -- ago/(N-1) a jul/N = ano PRODES N
    satelite       TEXT NOT NULL,
    estado         TEXT NOT NULL,
    municipio      TEXT,
    bioma          TEXT,
    dia_sem_chuva  SMALLINT,          -- NULL quando vier -999
    precipitacao   NUMERIC(8,2),
    risco_fogo     NUMERIC(5,2),
    frp            NUMERIC(10,2),
    latitude       NUMERIC(9,6),
    longitude      NUMERIC(9,6)
);

-- Para bancos criados antes desta coluna existir:
ALTER TABLE stg.focos_queimada ADD COLUMN IF NOT EXISTS ano_prodes SMALLINT;

CREATE TABLE IF NOT EXISTS stg.desmatamento (
    id_registro    BIGSERIAL PRIMARY KEY,
    fid            INTEGER,
    ano            SMALLINT NOT NULL,
    uf             CHAR(2)  NOT NULL,
    classe         TEXT,              -- main_class (conferir valores antes de somar)
    classe_nome    TEXT,              -- class_name
    data_imagem    DATE,
    area_km2       NUMERIC(14,4) NOT NULL CHECK (area_km2 >= 0),
    uuid           TEXT
);

-- ---------------------------------------------------------------------
-- 3) DW: dimensões + fatos.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dw.dim_tempo (
    ano  SMALLINT PRIMARY KEY
);

-- Fase 1: fatos por UF e ano
CREATE TABLE IF NOT EXISTS dw.fato_desmatamento_uf (
    ano       SMALLINT NOT NULL REFERENCES dw.dim_tempo (ano),
    uf        CHAR(2)  NOT NULL,
    area_km2  NUMERIC(14,4) NOT NULL,
    PRIMARY KEY (ano, uf)
);

CREATE TABLE IF NOT EXISTS dw.fato_queimadas_uf (
    ano        SMALLINT NOT NULL REFERENCES dw.dim_tempo (ano),
    uf         CHAR(2)  NOT NULL,
    qtd_focos  INTEGER  NOT NULL,
    frp_total  NUMERIC(14,2),
    PRIMARY KEY (ano, uf)
);

-- Focos por ano PRODES (ago/(N-1) a jul/N): é esta tabela que se compara com o desmatamento
CREATE TABLE IF NOT EXISTS dw.fato_queimadas_uf_prodes (
    ano_prodes SMALLINT NOT NULL REFERENCES dw.dim_tempo (ano),
    uf         CHAR(2)  NOT NULL,
    qtd_focos  INTEGER  NOT NULL,
    frp_total  NUMERIC(14,2),
    PRIMARY KEY (ano_prodes, uf)
);

-- Fase 2: fatos por município e ano
CREATE TABLE IF NOT EXISTS dw.dim_municipio (
    id_municipio  SERIAL PRIMARY KEY,
    cod_ibge      INTEGER UNIQUE,
    nome          TEXT NOT NULL,
    uf            CHAR(2) NOT NULL,
    UNIQUE (nome, uf)
);

CREATE TABLE IF NOT EXISTS dw.fato_desmatamento_municipio (
    ano           SMALLINT NOT NULL REFERENCES dw.dim_tempo (ano),
    id_municipio  INTEGER  NOT NULL REFERENCES dw.dim_municipio (id_municipio),
    area_km2      NUMERIC(14,4) NOT NULL,
    PRIMARY KEY (ano, id_municipio)
);

CREATE TABLE IF NOT EXISTS dw.fato_queimadas_municipio (
    ano           SMALLINT NOT NULL REFERENCES dw.dim_tempo (ano),
    id_municipio  INTEGER  NOT NULL REFERENCES dw.dim_municipio (id_municipio),
    qtd_focos     INTEGER  NOT NULL,
    frp_total     NUMERIC(14,2),
    PRIMARY KEY (ano, id_municipio)
);

-- ---------------------------------------------------------------------
-- 4) Views de análise.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW dw.vw_comparativo_para_ano AS
SELECT
    t.ano,
    COALESCE(d.area_km2, 0)  AS area_desmatada_km2,
    COALESCE(q.qtd_focos, 0) AS qtd_focos,
    q.frp_total
FROM dw.dim_tempo t
LEFT JOIN dw.fato_desmatamento_uf d ON d.ano = t.ano AND d.uf = 'PA'
LEFT JOIN dw.fato_queimadas_uf_prodes q ON q.ano_prodes = t.ano AND q.uf = 'PA'
WHERE t.ano >= 2009   -- o PRODES 2008 exigiria focos de ago/2007 em diante (não baixados)
ORDER BY t.ano;

CREATE OR REPLACE VIEW dw.vw_comparativo_municipio_ano AS
SELECT
    m.nome                   AS municipio,
    ano,
    COALESCE(d.area_km2, 0)  AS area_desmatada_km2,
    COALESCE(q.qtd_focos, 0) AS qtd_focos
FROM (
    SELECT ano, id_municipio FROM dw.fato_desmatamento_municipio
    UNION
    SELECT ano, id_municipio FROM dw.fato_queimadas_municipio
) k
JOIN dw.dim_municipio m USING (id_municipio)
LEFT JOIN dw.fato_desmatamento_municipio d USING (ano, id_municipio)
LEFT JOIN dw.fato_queimadas_municipio    q USING (ano, id_municipio);