# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import os
import plotly.graph_objects as go
from sqlalchemy import create_engine, URL, text
from dotenv import load_dotenv

load_dotenv()

def safe_float(val, default=0.0):
    try:
        v = float(val)
        return default if pd.isna(v) else v
    except (TypeError, ValueError):
        return default

def score_bar(val, cor="#2563eb"):
    pct = round(safe_float(val) * 100, 1)
    return f'<div class="score-bar-wrap"><div class="score-bar-fill" style="width:{pct}%;background:{cor}"></div></div>'

def recalcular_scores(df_grupo):
    """
    Tabela fixa de critérios (não é mais min-max relativo ao grupo).
    Cada critério vira uma nota 5-10 conforme faixa fixa (arredondada
    para baixo), depois dividida por 10 para manter a escala 0-1 usada
    no resto do app. nota_final = média simples dos 7 critérios.
    """
    df_g = df_grupo.copy()

    def clamp(serie, lo=5, hi=10):
        return serie.clip(lower=lo, upper=hi)

    # Propriedades Ativas: 30=10, 29=9, 28=8, 27=7, 26=6, ≤25=5
    df_g["n_prop_ativas"] = clamp(
        (df_g["propriedades_ativas"].apply(safe_float).apply(lambda v: (v // 1) - 20))
    ) / 10.0

    # Total de Visitas: 30=10, 29=9, 28=8, 27=7, 26=6, ≤25=5
    df_g["n_total_visitas"] = clamp(
        (df_g["total_visitas_presenciais"].apply(safe_float).apply(lambda v: (v // 1) - 20))
    ) / 10.0

    # Propriedades Inativas (invertido): 0=10, 1=9, 2=8, 3=7, 4=6, ≥5=5
    df_g["n_prop_inativas"] = clamp(
        df_g["propriedades_inativas"].apply(safe_float).apply(lambda v: 10 - (v // 1))
    ) / 10.0

    # Visitas Válidas (%) e Orientações Concluídas (%): faixa por dezena, piso 5
    df_g["n_taxa_validade"] = clamp(
        df_g["pct_visitas_validas"].apply(safe_float).apply(lambda v: v // 10)
    ) / 10.0
    df_g["n_taxa_ori_concluidas"] = clamp(
        df_g["pct_ori_concluidas"].apply(safe_float).apply(lambda v: v // 10)
    ) / 10.0

    # Total de Orientações: faixas fixas com larguras diferentes
    def nota_orientacoes(v):
        v = safe_float(v)
        if v >= 220: return 10
        if v >= 200: return 9
        if v >= 180: return 8
        if v >= 170: return 7
        if v >= 165: return 6
        return 5
    df_g["n_ori_geral"] = df_g["total_orientacoes_geral"].apply(nota_orientacoes) / 10.0

    # Repetição de Projeto: binário — 0 repetições=10, 1 ou mais=5
    df_g["n_multi_projetos"] = df_g["qtd_multiplos_projetos"].apply(
        lambda v: 10 if safe_float(v) == 0 else 5
    ) / 10.0

    cols = ["n_prop_ativas","n_total_visitas","n_ori_geral",
            "n_taxa_validade","n_taxa_ori_concluidas","n_prop_inativas","n_multi_projetos"]

    def nota(row):
        media = sum(safe_float(row[c]) for c in cols) / 7.0
        return round(media, 4)

    df_g["nota_final"] = df_g.apply(nota, axis=1)
    df_g["pos"] = df_g["nota_final"].rank(method="dense", ascending=False).astype(int)
    return df_g

def get_engine():
    url = URL.create(
        "postgresql+psycopg2",
        username=os.getenv("REMOTE_DB_USER", "postgres"),
        password=os.getenv("REMOTE_DB_PASS"),
        host=os.getenv("REMOTE_DB_HOST", "177.22.38.27"),
        port=int(os.getenv("REMOTE_DB_PORT", "6432")),
        database=os.getenv("REMOTE_DB_NAME", "painel_ateg"),
    )
    return create_engine(url)

@st.cache_data(ttl=600)
def listar_tabelas():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            return pd.read_sql("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_type = 'BASE TABLE'
                  AND table_schema NOT IN ('pg_catalog','information_schema')
                ORDER BY table_schema, table_name
            """, conn)
    except Exception as e:
        return pd.DataFrame({"erro": [str(e)]})

@st.cache_data(ttl=600)
def buscar_dados(dt_inicio: str, dt_fim: str):
    engine = get_engine()
    query = f"""
WITH Parametros AS (
    SELECT
        '{dt_inicio}'::DATE AS dt_inicio,
        '{dt_fim}'::DATE    AS dt_fim
),

-- ══════════════════════════════════════════════════════════
-- 1. CAP DE 30 VISITAS POR TÉCNICO (primeiras 30 por data)
-- ══════════════════════════════════════════════════════════
VisitasComRank AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY tecnico_responsavel
               ORDER BY dt_visita ASC
           ) AS rn_visita
    FROM public.acompanhamento_mensal_visitas
    WHERE dt_visita BETWEEN (SELECT dt_inicio FROM Parametros)
                        AND (SELECT dt_fim    FROM Parametros)
),

-- Apenas as primeiras 30 visitas de cada técnico no período
VisitasCap AS (
    SELECT * FROM VisitasComRank WHERE rn_visita <= 30
),

-- ══════════════════════════════════════════════════════════
-- 2. HISTÓRICO GLOBAL (sem cap, para multi-projetos)
-- ══════════════════════════════════════════════════════════
HistoricoCompletoProjetos AS (
    SELECT tecnico_responsavel, id_propriedade,
           COUNT(DISTINCT id_projeto) AS total_projetos_por_propriedade
    FROM public.acompanhamento_mensal_visitas
    WHERE regexp_replace(
              translate(upper(coalesce(projeto::text, '')), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ', 'AAAAAEEEEIIIIOOOOOUUUUC'),
              '\\s+', ' ', 'g'
          ) NOT LIKE '%SERTAO EMPREENDEDOR%'
    GROUP BY tecnico_responsavel, id_propriedade
),

PropriedadesSobrepostasGlobal AS (
    SELECT tecnico_responsavel,
           COUNT(DISTINCT id_propriedade) AS total_propriedades_com_multiplos_projetos
    FROM HistoricoCompletoProjetos
    WHERE total_projetos_por_propriedade > 1
    GROUP BY tecnico_responsavel
),

-- ══════════════════════════════════════════════════════════
-- 2B. STATUS MAIS RECENTE DE CADA PROPRIEDADE (GLOBAL)
-- ══════════════════════════════════════════════════════════
UltimoStatusPropriedade AS (
    SELECT DISTINCT ON (tecnico_responsavel, id_propriedade)
           tecnico_responsavel,
           id_propriedade,
           vinculo_status
    FROM public.acompanhamento_mensal_visitas
    WHERE tecnico_responsavel IS NOT NULL
    ORDER BY tecnico_responsavel, id_propriedade, dt_visita DESC
),

PropriedadesAtivasInativas AS (
    SELECT tecnico_responsavel,
           COUNT(DISTINCT CASE WHEN vinculo_status = 'ATIVA' THEN id_propriedade END) AS prop_ativas,
           COUNT(DISTINCT CASE WHEN vinculo_status = 'INATIVA' THEN id_propriedade END) AS prop_inativas
    FROM UltimoStatusPropriedade
    GROUP BY tecnico_responsavel
),

-- ══════════════════════════════════════════════════════════
-- 2C. PROPRIEDADES INATIVAS DO PERÍODO (apenas deste projeto/período)
-- ══════════════════════════════════════════════════════════
PropriedadesInativasDoPeriodo AS (
    SELECT tecnico_responsavel,
           COUNT(DISTINCT CASE WHEN vinculo_status = 'INATIVA' THEN id_propriedade END) AS prop_inativas_periodo
    FROM VisitasComRank
    GROUP BY tecnico_responsavel
),

-- ══════════════════════════════════════════════════════════
-- 2D. PROPRIEDADES INATIVAS DO ANO (quando projeto NÃO selecionado)
-- ══════════════════════════════════════════════════════════
PropriedadesInativasDoAno AS (
    SELECT tecnico_responsavel,
           COUNT(DISTINCT CASE WHEN vinculo_status = 'INATIVA' THEN id_propriedade END) AS prop_inativas_ano
    FROM public.acompanhamento_mensal_visitas
    WHERE EXTRACT(YEAR FROM dt_visita) = EXTRACT(YEAR FROM (SELECT dt_inicio FROM Parametros))
    GROUP BY tecnico_responsavel
),

-- ══════════════════════════════════════════════════════════
-- 3. ÚLTIMO SUPERVISOR ATUAL / ANTERIOR / PROJETO / ATIVIDADE
--    (usando TODAS as visitas do período, SEM cap — precisa
--     refletir a visita mais recente de fato, não a 30ª mais antiga)
-- ══════════════════════════════════════════════════════════
UltimoSupervisorAtualPorTecnico AS (
    SELECT DISTINCT ON (tecnico_responsavel)
        tecnico_responsavel,
        supervisor_atual AS ultimo_supervisor
    FROM VisitasComRank
    ORDER BY tecnico_responsavel, dt_visita DESC
),

UltimoSupervisorAnteriorPorTecnico AS (
    SELECT DISTINCT ON (tecnico_responsavel)
        tecnico_responsavel,
        supervisor_anterior AS ultimo_supervisor_anterior
    FROM VisitasComRank
    WHERE supervisor_anterior IS NOT NULL
    ORDER BY tecnico_responsavel, dt_visita DESC
),

UltimoProjetoPorTecnico AS (
    SELECT DISTINCT ON (tecnico_responsavel)
        tecnico_responsavel,
        projeto AS ultimo_projeto
    FROM VisitasComRank
    WHERE projeto IS NOT NULL
    ORDER BY tecnico_responsavel, dt_visita DESC
),

UltimaAtividadePorTecnico AS (
    SELECT DISTINCT ON (tecnico_responsavel)
        tecnico_responsavel,
        atividade AS ultima_atividade
    FROM VisitasComRank
    WHERE atividade IS NOT NULL
    ORDER BY tecnico_responsavel, dt_visita DESC
),

-- ══════════════════════════════════════════════════════════
-- 4. RESUMO — usando VisitasCap (máx 30 visitas por técnico)
-- ══════════════════════════════════════════════════════════
ResumoTecnicos AS (
    SELECT
        vc.tecnico_responsavel,
        pai.prop_ativas AS propriedades_ativas,
        CASE 
            WHEN COALESCE(pip.prop_inativas_periodo, 0) > 0 THEN COALESCE(pip.prop_inativas_periodo, 0)
            ELSE COALESCE(pia.prop_inativas_ano, 0)
        END AS propriedades_inativas,
        COUNT(DISTINCT vc.id_propriedade)                                                 AS total_propriedades_distintas,
        COUNT(*)                                                                        AS total_de_visitas,
        COUNT(CASE WHEN vc.visita_presencial = 'SIM' THEN 1 END)                          AS total_visitas_presenciais,
        COUNT(CASE WHEN vc.visita_valida = 'Valida' AND vc.visita_presencial = 'SIM' THEN 1 END) AS total_visitas_validas,
        SUM(COALESCE(CASE WHEN usp.vinculo_status = 'ATIVA' THEN vc.ori_total_geral ELSE 0 END, 0))                                               AS total_orientacoes_geral,
        SUM(COALESCE(CASE WHEN usp.vinculo_status = 'ATIVA' THEN vc.ori_concluida ELSE 0 END, 0))                                               AS total_orientacoes_concluidas
    FROM VisitasCap vc
    LEFT JOIN PropriedadesAtivasInativas pai ON vc.tecnico_responsavel = pai.tecnico_responsavel
    LEFT JOIN PropriedadesInativasDoPeriodo pip ON vc.tecnico_responsavel = pip.tecnico_responsavel
    LEFT JOIN PropriedadesInativasDoAno pia ON vc.tecnico_responsavel = pia.tecnico_responsavel
    LEFT JOIN UltimoStatusPropriedade usp ON vc.id_propriedade = usp.id_propriedade AND vc.tecnico_responsavel = usp.tecnico_responsavel
    GROUP BY vc.tecnico_responsavel, pai.prop_ativas, pip.prop_inativas_periodo, pia.prop_inativas_ano
),

Taxas AS (
    SELECT
        r.tecnico_responsavel,
        r.propriedades_ativas,
        r.propriedades_inativas,
        r.total_de_visitas,
        r.total_visitas_presenciais,
        r.total_visitas_validas,
        r.total_orientacoes_geral,
        r.total_orientacoes_concluidas,
        CASE WHEN r.total_de_visitas > 0
             THEN r.total_visitas_validas::NUMERIC / r.total_de_visitas
             ELSE 0
        END AS taxa_validade,
        CASE WHEN r.total_orientacoes_geral > 0
             THEN r.total_orientacoes_concluidas::NUMERIC / r.total_orientacoes_geral
             ELSE 0
        END AS taxa_ori_concluidas,
        COALESCE(p.total_propriedades_com_multiplos_projetos, 0) AS qtd_multiplos_projetos
    FROM ResumoTecnicos r
    LEFT JOIN PropriedadesSobrepostasGlobal p ON r.tecnico_responsavel = p.tecnico_responsavel
    WHERE r.propriedades_ativas > 0
),

Normalizado AS (
    SELECT
        t.tecnico_responsavel,
        sa.ultimo_supervisor,
        san.ultimo_supervisor_anterior,
        pr.ultimo_projeto,
        at.ultima_atividade,

        t.propriedades_ativas,
        t.propriedades_inativas,
        t.total_de_visitas,
        t.total_visitas_presenciais,
        t.total_visitas_validas,
        t.total_orientacoes_geral,
        t.total_orientacoes_concluidas,
        t.qtd_multiplos_projetos,

        ROUND(t.taxa_validade * 100,        1) AS pct_visitas_validas,
        ROUND(t.taxa_ori_concluidas * 100,  1) AS pct_ori_concluidas,

        -- ══════════════════════════════════════════════════════
        -- TABELA FIXA DE CRITÉRIOS (não é mais min-max relativo).
        -- Cada critério vira nota 5–10 conforme faixa fixa (arredondado
        -- para baixo / "floor"), depois dividido por 10 para manter a
        -- escala 0–1 usada no resto do app (nota_final segue como média).
        -- ══════════════════════════════════════════════════════

        -- Propriedades Ativas: 30=10, 29=9, 28=8, 27=7, 26=6, ≤25=5
        LEAST(10, GREATEST(5, FLOOR(t.propriedades_ativas) - 20)) / 10.0 AS n_prop_ativas,

        -- Total de Visitas: 30=10, 29=9, 28=8, 27=7, 26=6, ≤25=5
        LEAST(10, GREATEST(5, FLOOR(t.total_visitas_presenciais) - 20)) / 10.0 AS n_total_visitas,

        -- Total de Orientações: faixas fixas com larguras diferentes
        (CASE
            WHEN t.total_orientacoes_geral >= 220 THEN 10
            WHEN t.total_orientacoes_geral >= 200 THEN 9
            WHEN t.total_orientacoes_geral >= 180 THEN 8
            WHEN t.total_orientacoes_geral >= 170 THEN 7
            WHEN t.total_orientacoes_geral >= 165 THEN 6
            ELSE 5
        END) / 10.0 AS n_ori_geral,

        -- Visitas Válidas (%): 100%=10, 90-99%=9, 80-89%=8, 70-79%=7 ... piso 5
        LEAST(10, GREATEST(5, FLOOR((t.taxa_validade * 100) / 10))) / 10.0 AS n_taxa_validade,

        -- Orientações Concluídas (%): mesma regra de faixa por dezena
        LEAST(10, GREATEST(5, FLOOR((t.taxa_ori_concluidas * 100) / 10))) / 10.0 AS n_taxa_ori_concluidas,

        -- Propriedades Inativas (invertido): 0=10, 1=9, 2=8, 3=7, 4=6, ≥5=5
        LEAST(10, GREATEST(5, 10 - FLOOR(t.propriedades_inativas))) / 10.0 AS n_prop_inativas,

        -- Repetição de Projeto: binário — 0 repetições=10, 1 ou mais=5
        (CASE WHEN t.qtd_multiplos_projetos = 0 THEN 10 ELSE 5 END) / 10.0 AS n_multi_projetos

    FROM Taxas t
    LEFT JOIN UltimoSupervisorAtualPorTecnico    sa  ON t.tecnico_responsavel = sa.tecnico_responsavel
    LEFT JOIN UltimoSupervisorAnteriorPorTecnico san ON t.tecnico_responsavel = san.tecnico_responsavel
    LEFT JOIN UltimoProjetoPorTecnico            pr  ON t.tecnico_responsavel = pr.tecnico_responsavel
    LEFT JOIN UltimaAtividadePorTecnico          at  ON t.tecnico_responsavel = at.tecnico_responsavel
)
SELECT
    tecnico_responsavel,
    ultimo_supervisor,
    ultimo_supervisor_anterior,
    ultimo_projeto,
    ultima_atividade,
    propriedades_ativas,
    propriedades_inativas,
    total_de_visitas,
    total_visitas_presenciais,
    total_visitas_validas,
    total_orientacoes_geral,
    total_orientacoes_concluidas,
    qtd_multiplos_projetos,
    pct_visitas_validas,
    pct_ori_concluidas,
    ROUND(CAST(n_prop_ativas         AS NUMERIC), 4) AS n_prop_ativas,
    ROUND(CAST(n_total_visitas       AS NUMERIC), 4) AS n_total_visitas,
    ROUND(CAST(n_ori_geral           AS NUMERIC), 4) AS n_ori_geral,
    ROUND(CAST(n_taxa_validade       AS NUMERIC), 4) AS n_taxa_validade,
    ROUND(CAST(n_taxa_ori_concluidas AS NUMERIC), 4) AS n_taxa_ori_concluidas,
    ROUND(CAST(n_prop_inativas       AS NUMERIC), 4) AS n_prop_inativas,
    ROUND(CAST(n_multi_projetos      AS NUMERIC), 4) AS n_multi_projetos,
    ROUND(CAST(
        (COALESCE(n_prop_ativas,0)+COALESCE(n_total_visitas,0)+COALESCE(n_ori_geral,0)+
         COALESCE(n_taxa_validade,0)+COALESCE(n_taxa_ori_concluidas,0)+
         COALESCE(n_prop_inativas,0)+COALESCE(n_multi_projetos,0)) / 7.0
    AS NUMERIC), 4) AS nota_final,

    DENSE_RANK() OVER (
        PARTITION BY ultimo_supervisor
        ORDER BY (COALESCE(n_prop_ativas,0)+COALESCE(n_total_visitas,0)+COALESCE(n_ori_geral,0)+
                  COALESCE(n_taxa_validade,0)+COALESCE(n_taxa_ori_concluidas,0)+
                  COALESCE(n_prop_inativas,0)+COALESCE(n_multi_projetos,0)) / 7.0 DESC
    ) AS pos,

    DENSE_RANK() OVER (
        PARTITION BY ultimo_projeto
        ORDER BY (COALESCE(n_prop_ativas,0)+COALESCE(n_total_visitas,0)+COALESCE(n_ori_geral,0)+
                  COALESCE(n_taxa_validade,0)+COALESCE(n_taxa_ori_concluidas,0)+
                  COALESCE(n_prop_inativas,0)+COALESCE(n_multi_projetos,0)) DESC
    ) AS pos_projeto,

    DENSE_RANK() OVER (
        PARTITION BY ultima_atividade
        ORDER BY (COALESCE(n_prop_ativas,0)+COALESCE(n_total_visitas,0)+COALESCE(n_ori_geral,0)+
                  COALESCE(n_taxa_validade,0)+COALESCE(n_taxa_ori_concluidas,0)+
                  COALESCE(n_prop_inativas,0)+COALESCE(n_multi_projetos,0)) DESC
    ) AS pos_atividade,

    DENSE_RANK() OVER (
        PARTITION BY ultimo_supervisor_anterior
        ORDER BY (COALESCE(n_prop_ativas,0)+COALESCE(n_total_visitas,0)+COALESCE(n_ori_geral,0)+
                  COALESCE(n_taxa_validade,0)+COALESCE(n_taxa_ori_concluidas,0)+
                  COALESCE(n_prop_inativas,0)+COALESCE(n_multi_projetos,0)) / 7.0 DESC
    ) AS pos_sup_anterior

FROM Normalizado
ORDER BY ultimo_supervisor, pos;
    """
    try:
        with engine.connect() as conn:
            return pd.read_sql(text(query), conn)
    except Exception as e:
        st.error(f"❌ Erro ao buscar dados: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=600)
def buscar_conflitos_propriedades():
    engine = get_engine()
    query = """
    WITH UltimoSupervisor AS (
        SELECT DISTINCT ON (tecnico_responsavel)
               tecnico_responsavel, supervisor_atual
        FROM public.acompanhamento_mensal_visitas
        ORDER BY tecnico_responsavel, dt_visita DESC
    ),
    ProjetosValidos AS (
        SELECT *
        FROM public.acompanhamento_mensal_visitas
        WHERE regexp_replace(
                  translate(upper(coalesce(projeto::text, '')), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ', 'AAAAAEEEEIIIIOOOOOUUUUC'),
                  '\\s+', ' ', 'g'
              ) NOT LIKE '%SERTAO EMPREENDEDOR%'
    )
    SELECT
        u.supervisor_atual,
        t.tecnico_responsavel,
        t.id_propriedade,
        t.imovel,
        t.cpf_produtor,
        string_agg(DISTINCT t.projeto::text, ', ') as projetos_vinculados,
        COUNT(DISTINCT t.projeto) as qtd_projetos
    FROM ProjetosValidos t
    JOIN UltimoSupervisor u ON t.tecnico_responsavel = u.tecnico_responsavel
    GROUP BY u.supervisor_atual,t.tecnico_responsavel,t.id_propriedade,t.imovel,t.cpf_produtor
    HAVING COUNT(DISTINCT t.projeto) > 1
    """
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn)


# =====================================
# CONFIG
# =====================================
st.set_page_config(page_title="Ranking ATeG", page_icon="🏆", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] { background: #ffffff; }
[data-testid="stAppViewContainer"] > .main > .block-container { max-width: 1200px; padding: 0 1.5rem 1.5rem; margin-top: 0 !important; padding-top: 0 !important; }
[data-testid="stAppViewContainer"] { padding-top: 0 !important; margin-top: 0 !important; }
.main { padding-top: 0 !important; margin-top: 0 !important; }
.main .block-container { padding-top: 0 !important; padding-left: 0 !important; padding-right: 0 !important; margin-top: 0 !important; }
section[data-testid="stMain"] > div { padding-top: 0 !important; }
header[data-testid="stHeader"] { display: none !important; height: 0 !important; }
div[data-testid="stDecoration"] { display: none !important; }
div[data-testid="stToolbar"] { display: none !important; }
div[data-testid="stStatusWidget"] { display: none !important; }
#MainMenu { display: none !important; }
footer { display: none !important; }
.stApp { margin-top: 0 !important; padding-top: 0 !important; }
.page-header { background: linear-gradient(135deg,#064e3b 0%,#059669 100%); color:white; padding:12px 16px; border-radius:0; margin-bottom:12px; margin-left:-1.5rem; margin-right:-1.5rem; margin-top:-0.5rem; display:flex; align-items:center; justify-content:space-between; }
.page-header h1 { margin:0; font-size:1.2rem; font-weight:700; }
.page-header p  { margin:2px 0 0; font-size:0.75rem; opacity:0.7; }
.badge { background:rgba(255,255,255,0.15); padding:2px 8px; border-radius:20px; font-size:0.65rem; }
.metric-strip { display:grid; grid-template-columns:repeat(5,1fr); gap:6px; margin-bottom:10px; }
.metric-card { background:white; border-radius:8px; padding:10px 12px; box-shadow:0 1px 3px rgba(0,0,0,0.06); border-top:3px solid #2563eb; }
.metric-card.green  { border-top-color:#10b981; }
.metric-card.red    { border-top-color:#ef4444; }
.metric-card.yellow { border-top-color:#f59e0b; }
.metric-card.purple { border-top-color:#8b5cf6; }
.metric-card .label { font-size:0.65rem; color:#374151; margin-bottom:2px; text-transform:uppercase; letter-spacing:0.5px; }
.metric-card .value { font-size:1.3rem; font-weight:700; color:#111827; line-height:1; }
.section-title { font-size:0.75rem; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; color:#374151; margin:6px 0 6px; }
.rank-row { background:white; border-radius:8px; padding:10px 12px; margin-bottom:4px; box-shadow:0 1px 3px rgba(0,0,0,0.05); display:flex; align-items:center; gap:10px; border-left:4px solid #e5e7eb; }
.rank-row.gold   { border-left-color:#f59e0b; background:linear-gradient(90deg,#fffbeb,white 60%); }
.rank-row.silver { border-left-color:#9ca3af; background:linear-gradient(90deg,#f9fafb,white 60%); }
.rank-row.bronze { border-left-color:#b45309; background:linear-gradient(90deg,#fef3c7,white 60%); }
.rank-pos   { font-size:0.95rem; width:35px; text-align:center; flex-shrink:0; }
.rank-name  { flex:1; font-size:0.85rem; font-weight:600; color:#111827; }
.rank-score { font-size:1rem; font-weight:700; color:#1d4ed8; flex-shrink:0; }
.rank-bar   { flex-shrink:0; width:70px; background:#e5e7eb; border-radius:6px; height:5px; overflow:hidden; }
.rank-bar-fill { height:100%; border-radius:6px; background:linear-gradient(90deg,#2563eb,#60a5fa); }
.detail-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:6px; margin:6px 0; }
.detail-cell { background:#f8fafc; border-radius:6px; padding:8px 10px; border-left:3px solid #e5e7eb; }
.detail-cell.pos { border-left-color:#10b981; }
.detail-cell.neg { border-left-color:#ef4444; }
.detail-cell.pen { border-left-color:#f59e0b; }
.detail-cell.tot { border-left-color:#2563eb; background:#eff6ff; }
.detail-cell .d-label { font-size:0.65rem; color:#374151; margin-bottom:1px; }
.detail-cell .d-qty   { font-size:0.95rem; font-weight:700; color:#111827; }
.detail-cell .d-pts   { font-size:0.65rem; color:#374151; }
.score-bar-wrap { margin-top:2px; background:#e5e7eb; border-radius:4px; height:4px; overflow:hidden; }
.score-bar-fill { height:100%; border-radius:4px; }
div[data-testid="stSelectbox"] label { font-size:0.7rem !important; font-weight:700 !important; text-transform:uppercase !important; letter-spacing:0.7px !important; color:#059669 !important; }
div[data-testid="stSelectbox"] > div > div { border: 1.5px solid #d1fae5 !important; border-radius: 8px !important; background: white !important; font-weight:600 !important; font-size:0.9rem !important; }
div[data-testid="stSelectbox"] > div > div:focus-within { border-color: #059669 !important; box-shadow: 0 0 0 3px rgba(5,150,105,0.15) !important; }
div[data-testid="stBaseButton-secondary"] button { background: #059669 !important; color: white !important; border: none !important; border-radius: 8px !important; font-weight:600 !important; }
.cap-aviso { background:#fffbeb; border:1px solid #f59e0b; border-radius:6px; padding:6px 10px; font-size:0.75rem; color:#92400e; margin-bottom:6px; }

/* ── Destaque nas abas ── */
button[data-baseweb="tab"] {
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    padding: 8px 18px !important;
    border-radius: 8px 8px 0 0 !important;
    color: #374151 !important;
    background: #f1f5f9 !important;
    border: 1px solid #e2e8f0 !important;
    border-bottom: none !important;
    margin-right: 4px !important;
    transition: all 0.2s ease !important;
}
button[data-baseweb="tab"]:hover {
    background: #e0f2fe !important;
    color: #0369a1 !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    background: linear-gradient(135deg, #064e3b 0%, #059669 100%) !important;
    color: white !important;
    border-color: #059669 !important;
    box-shadow: 0 2px 8px rgba(5,150,105,0.3) !important;
}
div[data-testid="stTabs"] > div:first-child {
    border-bottom: 2px solid #059669 !important;
    margin-bottom: 12px !important;
}
div[role="tabpanel"] {
    padding-top: 8px !important;
}
div[data-testid="stTextInput"] { margin-bottom: 8px !important; }
.stExpander { margin-bottom: 4px !important; }
hr { margin: 6px 0 !important; }

</style>
""", unsafe_allow_html=True)

import calendar
from datetime import date

st.markdown("""
<div class="page-header">
    <div>
        <h1>🏆 Ranking de Performance ATeG</h1>
        <p>7 indicadores com peso igual (14,3% cada) · máx. 30 visitas por técnico · comparação dentro do grupo</p>
    </div>
    <span class="badge">Nota 0 a 1</span>
</div>
""", unsafe_allow_html=True)

pagina = st.selectbox("📋 Página", ["Ranking Técnicos", "Ranking de Supervisores", "Repeticao Projetos"])

if pagina == "Gestão de Propriedades Multi-Projeto":
    df_conf = buscar_conflitos_propriedades()
    c1, c2 = st.columns(2)
    with c1:
        sup_lista = ["Todos"] + sorted(df_conf["supervisor_atual"].dropna().astype(str).unique().tolist())
        sup_sel = st.selectbox("Filtrar por Supervisor", sup_lista)
    with c2:
        if sup_sel != "Todos":
            tec_lista = ["Todos"] + sorted(df_conf[df_conf["supervisor_atual"] == sup_sel]["tecnico_responsavel"].dropna().astype(str).unique().tolist())
        else:
            tec_lista = ["Todos"] + sorted(df_conf["tecnico_responsavel"].dropna().astype(str).unique().tolist())
        tec_sel = st.selectbox("Filtrar por Técnico", tec_lista)
    if sup_sel != "Todos":
        df_conf = df_conf[df_conf["supervisor_atual"] == sup_sel]
    if tec_sel != "Todos":
        df_conf = df_conf[df_conf["tecnico_responsavel"] == tec_sel]
    st.markdown(f"""
    <div class="metric-strip">
        <div class="metric-card green">
            <div class="label">Propriedades em Conflito</div>
            <div class="value">{len(df_conf)}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.dataframe(df_conf, use_container_width=True, hide_index=True)
    st.stop()


# ── FILTROS DE PERÍODO ──────────────────────────────────────────────────────
MESES = {1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",5:"Maio",6:"Junho",
         7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"}

hoje = date.today()

# Mês/ano anterior (mês passado) — padrão para inicial e final
if hoje.month > 1:
    mes_anterior = hoje.month - 1
    ano_do_mes_anterior = hoje.year
else:
    mes_anterior = 12
    ano_do_mes_anterior = hoje.year - 1

# Lista de anos sempre inclui o ano atual e o ano do mês anterior (evita quebrar na virada do ano)
ANOS = sorted(set([2024, 2025, 2026, hoje.year, ano_do_mes_anterior]))
idx_ano_anterior = ANOS.index(ano_do_mes_anterior)

# Mês final só pode ir até o mês atual (não deixa escolher mês futuro),
# exceto no caso de virada de ano (janeiro), onde o mês anterior é dezembro do ano passado
_capped = [m for m in MESES.keys() if m <= hoje.month]
opcoes_mes_fim = _capped if mes_anterior in _capped else list(MESES.keys())

col_mi, col_ai, col_mf, col_af, col_btn = st.columns([2, 1.2, 2, 1.2, 1])
with col_mi:
    mes_ini = st.selectbox("📅 Mês inicial", options=list(MESES.keys()), format_func=lambda x: MESES[x], index=mes_anterior - 1)
with col_ai:
    ano_ini = st.selectbox("Ano inicial", options=ANOS, index=idx_ano_anterior)
with col_mf:
    mes_fim = st.selectbox("📅 Mês final", options=opcoes_mes_fim, format_func=lambda x: MESES[x], index=opcoes_mes_fim.index(mes_anterior))
with col_af:
    ano_fim = st.selectbox("Ano final", options=ANOS, index=idx_ano_anterior)
with col_btn:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if st.button("🔄 Atualizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

dt_inicio = f"{ano_ini}-{mes_ini:02d}-01"
dt_fim    = f"{ano_fim}-{mes_fim:02d}-{calendar.monthrange(ano_fim, mes_fim)[1]}"

# ── DADOS ───────────────────────────────────────────────────────────────────
df = buscar_dados(dt_inicio, dt_fim)
if df is None or df.empty:
    st.warning("Nenhum dado encontrado para o período selecionado.")
    st.stop()

cols_num = ["n_prop_ativas","n_total_visitas","n_ori_geral","n_taxa_validade",
            "n_taxa_ori_concluidas","n_prop_inativas","n_multi_projetos",
            "nota_final","total_visitas_presenciais","total_de_visitas"]
for c in cols_num:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

# ── AVISO CAP ───────────────────────────────────────────────────────────────
tecnicos_com_cap = (df["total_de_visitas"] == 30).sum()
if tecnicos_com_cap > 0:
    st.markdown(
        f'<div class="cap-aviso">⚠️ <strong>Cap de 30 visitas ativo:</strong> '
        f'{tecnicos_com_cap} técnico(s) atingiram o limite — apenas as primeiras 30 visitas '
        f'(por data) foram consideradas no cálculo.</div>',
        unsafe_allow_html=True
    )

# ── BUSCA/FILTRO DE TÉCNICO ────────────────────────────────────────────────────
st.markdown("---")
col_search, col_count = st.columns([3, 1])
with col_search:
    busca_tecnico = st.text_input(
        "🔍 Buscar Técnico",
        placeholder="Digite o nome ou parte do nome do técnico...",
        help="Digite para filtrar a lista de técnicos"
    )
with col_count:
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    st.metric("Técnicos", len(df) if not busca_tecnico.strip() else len(df[df["tecnico_responsavel"].str.contains(busca_tecnico, case=False, na=False)]))

if busca_tecnico.strip():
    df = df[df["tecnico_responsavel"].str.contains(busca_tecnico, case=False, na=False)]
    if df.empty:
        st.warning(f"❌ Nenhum técnico encontrado com '{busca_tecnico}'")
        st.stop()
    st.info(f"✅ {len(df)} técnico(s) encontrado(s) para '{busca_tecnico}'")
st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════
# PÁGINA: RANKING DE SUPERVISORES (mesmos parâmetros dos técnicos, agregados)
# ══════════════════════════════════════════════════════════════════════════
if pagina == "Ranking de Supervisores":
    st.markdown('<p class="section-title" style="margin-top:4px">🏆 Ranking de Supervisores — Performance da Equipe</p>', unsafe_allow_html=True)

    # ── FILTRO — mesmas opções da página de Técnicos ────────────────────────
    col_tipo_sup, col_val_sup, col_val2_sup = st.columns([1.5, 3, 3])

    with col_tipo_sup:
        modo_sup = st.selectbox("🔎 Filtrar por", [
            "Supervisor Atual",
            "Supervisor Anterior",
            "Projeto",
            "Atividade",
            "Projeto → Atividade",
        ], key="modo_sup_rank")

    df_proj_pool_sup = None
    proj_sel_sup2 = None

    with col_val_sup:
        if modo_sup == "Supervisor Atual":
            col_sup = "ultimo_supervisor"
            rotulo_sup, rotulo_sup_plural = "Supervisor Atual", "Supervisores Atuais"
            df_pool_sup = df.copy()
            st.caption("Considerando todos os técnicos do período selecionado.")

        elif modo_sup == "Supervisor Anterior":
            col_sup = "ultimo_supervisor_anterior"
            rotulo_sup, rotulo_sup_plural = "Supervisor Anterior", "Supervisores Anteriores"
            df_pool_sup = df.copy()
            st.caption("Considerando todos os técnicos do período selecionado.")

        elif modo_sup == "Projeto":
            col_sup = "ultimo_supervisor"
            projetos_sup = ["Todos"] + sorted(df["ultimo_projeto"].dropna().astype(str).unique())
            proj_sel_sup = st.selectbox("📁 Projeto", projetos_sup, key="proj_sup_rank")
            if proj_sel_sup == "Todos":
                df_pool_sup = df.copy()
                rotulo_sup, rotulo_sup_plural = "Supervisor", "Supervisores — Projeto: Todos"
            else:
                df_pool_sup = df[df["ultimo_projeto"] == proj_sel_sup].copy()
                rotulo_sup, rotulo_sup_plural = "Supervisor", f"Supervisores — Projeto: {proj_sel_sup}"

        elif modo_sup == "Atividade":
            col_sup = "ultimo_supervisor"
            atividades_sup = ["Todos"] + sorted(df["ultima_atividade"].dropna().astype(str).unique())
            atv_sel_sup = st.selectbox("🌱 Atividade", atividades_sup, key="atv_sup_rank")
            if atv_sel_sup == "Todos":
                df_pool_sup = df.copy()
                rotulo_sup, rotulo_sup_plural = "Supervisor", "Supervisores — Atividade: Todos"
            else:
                df_pool_sup = df[df["ultima_atividade"] == atv_sel_sup].copy()
                rotulo_sup, rotulo_sup_plural = "Supervisor", f"Supervisores — Atividade: {atv_sel_sup}"

        elif modo_sup == "Projeto → Atividade":
            col_sup = "ultimo_supervisor"
            projetos_sup2 = ["Todos"] + sorted(df["ultimo_projeto"].dropna().astype(str).unique())
            proj_sel_sup2 = st.selectbox("📁 Projeto", projetos_sup2, key="proj_sup_rank2")
            if proj_sel_sup2 == "Todos":
                df_proj_pool_sup = df.copy()
            else:
                df_proj_pool_sup = df[df["ultimo_projeto"] == proj_sel_sup2]
            df_pool_sup = df_proj_pool_sup.copy()
            rotulo_sup, rotulo_sup_plural = "Supervisor", f"Supervisores — {proj_sel_sup2}"

    with col_val2_sup:
        if modo_sup == "Projeto → Atividade":
            atividades_proj_sup = ["Todos"] + sorted(df_proj_pool_sup["ultima_atividade"].dropna().astype(str).unique())
            if len(atividades_proj_sup) > 1 or proj_sel_sup2 == "Todos":
                atv_sel_sup2 = st.selectbox("🌱 Atividade", atividades_proj_sup, key="atv_sup_rank2")
                if atv_sel_sup2 == "Todos":
                    df_pool_sup = df_proj_pool_sup.copy()
                    rotulo_sup_plural = f"Supervisores — {proj_sel_sup2} / Todos"
                else:
                    df_pool_sup = df_proj_pool_sup[df_proj_pool_sup["ultima_atividade"] == atv_sel_sup2].copy()
                    rotulo_sup_plural = f"Supervisores — {proj_sel_sup2} / {atv_sel_sup2}"
            else:
                st.warning("Nenhuma atividade encontrada para este projeto.")
                df_pool_sup = pd.DataFrame()
        else:
            st.empty()

    if df_pool_sup is None or df_pool_sup.empty:
        st.warning("Nenhum técnico encontrado para este filtro.")
        st.stop()

    df_base_sup = df_pool_sup[df_pool_sup[col_sup].notna() & (df_pool_sup[col_sup].astype(str).str.strip() != "")].copy()
    if df_base_sup.empty:
        st.warning(f"Nenhum {rotulo_sup.lower()} encontrado para este filtro.")
        st.stop()

    # ── Agrega os indicadores dos técnicos por supervisor (mesmos parâmetros) ──
    agg_sup = df_base_sup.groupby(col_sup).agg(
        qtd_tecnicos=("tecnico_responsavel", "nunique"),
        propriedades_ativas=("propriedades_ativas", "sum"),
        propriedades_inativas=("propriedades_inativas", "sum"),
        total_visitas_presenciais=("total_visitas_presenciais", "sum"),
        total_visitas_validas=("total_visitas_validas", "sum"),
        total_de_visitas=("total_de_visitas", "sum"),
        total_orientacoes_geral=("total_orientacoes_geral", "sum"),
        total_orientacoes_concluidas=("total_orientacoes_concluidas", "sum"),
        qtd_multiplos_projetos=("qtd_multiplos_projetos", "sum"),
    ).reset_index().rename(columns={col_sup: "supervisor"})

    agg_sup["pct_visitas_validas"] = agg_sup.apply(
        lambda r: round((r["total_visitas_validas"] / r["total_visitas_presenciais"]) * 100, 1)
        if r["total_visitas_presenciais"] > 0 else 0.0, axis=1)
    agg_sup["pct_ori_concluidas"] = agg_sup.apply(
        lambda r: round((r["total_orientacoes_concluidas"] / r["total_orientacoes_geral"]) * 100, 1)
        if r["total_orientacoes_geral"] > 0 else 0.0, axis=1)

    # ── Mesma tabela fixa de critérios (nota 5–10 por faixa) usada para os técnicos ──
    df_supv = recalcular_scores(agg_sup).sort_values("nota_final", ascending=False).reset_index(drop=True)

    # ── Melhor técnico de cada supervisor (quem puxa a equipe pra cima) ──
    idx_melhor = df_base_sup.groupby(col_sup)["nota_final"].idxmax()
    melhor_tec_map = df_base_sup.loc[idx_melhor].set_index(col_sup)[
        ["tecnico_responsavel", "nota_final"]
    ].to_dict("index")


    tab1_sup, tab_dist_sup, tab2_sup = st.tabs(["🏆 Ranking", "📊 Distribuição", "🔎 Detalhes por Supervisor"])
    with tab1_sup:
        # ── Métricas gerais ──
        st.markdown(f"""
        <div class="metric-strip">
            <div class="metric-card">
                <div class="label">👥 {rotulo_sup_plural}</div>
                <div class="value">{len(df_supv)}</div>
            </div>
            <div class="metric-card green">
                <div class="label">🏆 Melhor Equipe</div>
                <div class="value">{safe_float(df_supv['nota_final'].max())*100:.1f}%</div>
            </div>
            <div class="metric-card red">
                <div class="label">📉 Pior Equipe</div>
                <div class="value">{safe_float(df_supv['nota_final'].min())*100:.1f}%</div>
            </div>
            <div class="metric-card yellow">
                <div class="label">✅ Média Visitas Válidas</div>
                <div class="value">{safe_float(df_supv['pct_visitas_validas'].mean()):.1f}%</div>
            </div>
            <div class="metric-card purple">
                <div class="label">✔️ Média Orient. Concl.</div>
                <div class="value">{safe_float(df_supv['pct_ori_concluidas'].mean()):.1f}%</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col_rank_sup, col_chart_sup = st.columns([1, 1], gap="medium")

        with col_rank_sup:
            st.markdown(f'<p class="section-title">Classificação das Equipes — {rotulo_sup}</p>', unsafe_allow_html=True)
            for _, row in df_supv.iterrows():
                pos  = int(row["pos"])
                nota = safe_float(row["nota_final"])
                pct  = nota * 100
                medalha = "🥇" if pos==1 else "🥈" if pos==2 else "🥉" if pos==3 else f"#{pos}"
                classe  = "gold" if pos==1 else "silver" if pos==2 else "bronze" if pos==3 else ""
                sup_nome = row["supervisor"]
                melhor   = melhor_tec_map.get(sup_nome)
                melhor_str = (
                    f"🌟 Melhor técnico: {melhor['tecnico_responsavel']} ({safe_float(melhor['nota_final'])*100:.0f}%)"
                    if melhor else ""
                )
                st.markdown(f"""
                <div class="rank-row {classe}">
                    <span class="rank-pos">{medalha}</span>
                    <span class="rank-name">{sup_nome} <span style="font-size:0.72rem;color:#6b7280">({int(row['qtd_tecnicos'])} técnico(s))</span></span>
                    <div class="rank-bar"><div class="rank-bar-fill" style="width:{pct:.1f}%"></div></div>
                    <span class="rank-score">{pct:.1f}%</span>
                </div>
                <div style="font-size:0.74rem;color:#374151;margin:-4px 0 8px 54px">{melhor_str}</div>
                """, unsafe_allow_html=True)

        with col_chart_sup:
            st.markdown('<p class="section-title">Score por indicador</p>', unsafe_allow_html=True)
            indicadores_sup = {
                "n_prop_ativas":         "Prop. Ativas",
                "n_prop_inativas":       "Prop. Inativas",
                "n_total_visitas":       "Total Visitas",
                "n_taxa_validade":       "Visitas Válidas",
                "n_ori_geral":           "Total Orientacões",
                "n_taxa_ori_concluidas": "Orientacoes Concluídas",
                "n_multi_projetos":      "Repetição-Projeto",
            }
            # Coluna absoluta correspondente a cada indicador normalizado (usada como rótulo da célula)
            colunas_absolutas_sup = {
                "n_prop_ativas":         ("propriedades_ativas",        "{:.0f}"),
                "n_total_visitas":       ("total_visitas_presenciais",  "{:.0f}"),
                "n_ori_geral":           ("total_orientacoes_geral",    "{:.0f}"),
                "n_taxa_validade":       ("total_visitas_validas",      "{:.0f}"),
                "n_taxa_ori_concluidas": ("total_orientacoes_concluidas","{:.0f}"),
                "n_prop_inativas":       ("propriedades_inativas",      "{:.0f}"),
                "n_multi_projetos":      ("qtd_multiplos_projetos",     "{:.0f}"),
            }

            z_sup = [[safe_float(row[col]) for col in indicadores_sup.keys()] for _, row in df_supv.iterrows()]
            sup_names = df_supv["supervisor"].tolist()
            labels_sup = list(indicadores_sup.values())

            # Texto exibido na célula = valor absoluto; hover mostra valor absoluto + score normalizado
            abs_vals_sup = [
                [safe_float(row[colunas_absolutas_sup[col][0]]) for col in indicadores_sup.keys()]
                for _, row in df_supv.iterrows()
            ]
            text_abs_sup = [
                [
                    colunas_absolutas_sup[col][1].format(safe_float(row[colunas_absolutas_sup[col][0]]))
                    + f" ({safe_float(row[col]) * 10:.1f})"
                    for col in indicadores_sup.keys()
                ]
                for _, row in df_supv.iterrows()
            ]

            fig_sup = go.Figure(go.Heatmap(
                z=z_sup, x=labels_sup, y=sup_names,
                colorscale="RdYlGn", zmin=0, zmax=1, showscale=True,
                colorbar=dict(thickness=12, len=0.8, tickformat=".0%"),
                customdata=abs_vals_sup,
                hovertemplate="%{y}<br>%{x}: valor %{customdata} · score %{z:.4f}<extra></extra>",
            ))

            ann_sup = []
            for i, row_vals in enumerate(z_sup):
                for j, val in enumerate(row_vals):
                    txt_color = "#111827" if 0.25 <= val <= 0.75 else "white"
                    ann_sup.append(dict(
                        x=labels_sup[j], y=sup_names[i],
                        text=text_abs_sup[i][j],
                        showarrow=False,
                        font=dict(size=10, color=txt_color),
                        xref="x", yref="y",
                    ))

            fig_sup.update_layout(
                height=max(220, len(sup_names) * 50 + 80),
                margin=dict(l=0, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(size=11, color="#111827"),
                xaxis=dict(side="top", tickangle=-30, tickfont=dict(color="#111827")),
                yaxis=dict(autorange="reversed", tickfont=dict(color="#111827")),
                annotations=ann_sup,
            )
            st.plotly_chart(fig_sup, use_container_width=True)

    with tab_dist_sup:
        st.markdown('<p class="section-title" style="margin-top:8px">Distribuição</p>', unsafe_allow_html=True)
        col_a_sup, col_b_sup = st.columns(2, gap="medium")

        # ── Preparar dados e calcular altura sincronizada ──
        comp_sup = df_supv[["supervisor","propriedades_ativas","propriedades_inativas"]].sort_values("propriedades_ativas", ascending=True)
        ori_sup = df_supv[["supervisor","total_orientacoes_geral","total_orientacoes_concluidas","pct_ori_concluidas"]].sort_values("total_orientacoes_geral", ascending=True)
        
        # ── Altura fixa máxima: 28px por supervisor, mínimo 320, máximo 600 ──
        n_max_sup = max(len(comp_sup), len(ori_sup))
        chart_height = min(600, max(320, n_max_sup * 28 + 80))

        _cfg_sup = {"displayModeBar": False, "scrollZoom": False}

        with col_a_sup:
            fig2_sup = go.Figure(data=[
                go.Bar(name="Ativas",   x=comp_sup["propriedades_ativas"],   y=comp_sup["supervisor"],
                       orientation="h", marker_color="#10b981",
                       text=comp_sup["propriedades_ativas"], textposition="inside", insidetextanchor="end", textfont=dict(size=10,color="white")),
                go.Bar(name="Inativas", x=comp_sup["propriedades_inativas"], y=comp_sup["supervisor"],
                       orientation="h", marker_color="#fca5a5",
                       text=comp_sup["propriedades_inativas"], textposition="inside", insidetextanchor="end", textfont=dict(size=10,color="#7f1d1d")),
            ])
            fig2_sup.update_layout(barmode="group", height=chart_height,
                title_text="Propriedades — Ativas vs Inativas (equipe)", title_font_size=12,
                margin=dict(l=0,r=10,t=36,b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h",y=1.08,x=0,font_size=10), font=dict(size=11, color="#111827"),
                xaxis=dict(showgrid=True,gridcolor="#f0f0f0",zeroline=False),
                yaxis=dict(showgrid=False, automargin=True, tickfont=dict(size=9)),
                bargap=0.2, bargroupgap=0.05)
            st.plotly_chart(fig2_sup, use_container_width=True, config=_cfg_sup)

        with col_b_sup:
            fig3_sup = go.Figure(data=[
                go.Bar(name="Total", x=ori_sup["total_orientacoes_geral"], y=ori_sup["supervisor"],
                       orientation="h", marker=dict(color="#bfdbfe"),
                       hovertemplate="%{y}<br>Total: %{x}<extra></extra>"),
                go.Bar(name="Concluídas", x=ori_sup["total_orientacoes_concluidas"], y=ori_sup["supervisor"],
                       orientation="h", marker=dict(color="#2563eb"),
                       text=[f"{int(v)}  ({safe_float(p):.0f}%)" for v,p in zip(ori_sup["total_orientacoes_concluidas"], ori_sup["pct_ori_concluidas"])],
                       textposition="inside", insidetextanchor="end", textfont=dict(size=10,color="white"),
                       hovertemplate="%{y}<br>Concluídas: %{x}<extra></extra>"),
            ])
            fig3_sup.update_layout(barmode="overlay", height=chart_height,
                title_text="Orientações — Total vs Concluídas (equipe)", title_font_size=12,
                margin=dict(l=0,r=10,t=36,b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h",y=1.08,x=0,font_size=10), font=dict(size=11, color="#111827"),
                xaxis=dict(showgrid=True,gridcolor="#f0f0f0",zeroline=False),
                yaxis=dict(showgrid=False, automargin=True, tickfont=dict(size=9)), bargap=0.25)
            st.plotly_chart(fig3_sup, use_container_width=True, config=_cfg_sup)

    with tab2_sup:
        # ── Detalhes por supervisor (com ranking dos técnicos da equipe) ──
        st.markdown(f'<p class="section-title" style="margin-top:8px">Detalhes por {rotulo_sup}</p>', unsafe_allow_html=True)

        _lideres_sup = {}
        for _col in indicadores_sup:
            _max_val = df_supv[_col].max()
            _lideres_sup[_col] = set(df_supv.loc[df_supv[_col] == _max_val, "supervisor"].tolist())

        for _, row in df_supv.iterrows():
            pos  = int(row["pos"])
            nota = safe_float(row["nota_final"])
            medalha = "🥇" if pos==1 else "🥈" if pos==2 else "🥉" if pos==3 else f"#{pos}"
            sup_nome = row["supervisor"]

            lider_em  = [nome for col, nome in indicadores_sup.items() if sup_nome in _lideres_sup[col]]
            qtd_lider = len(lider_em)

            with st.expander(
                f"{medalha} {sup_nome}  ·  nota {nota*10:.2f}  ·  {int(row['qtd_tecnicos'])} técnico(s)  ·  líder em {qtd_lider}/7 indicadores"
            ):
                st.markdown(f"""
                <div class="detail-grid">
                    <div class="detail-cell pos">
                        <div class="d-label">🚜 Prop. Ativas (equipe)</div>
                        <div class="d-qty">{int(safe_float(row['propriedades_ativas']))}</div>
                        <div class="d-pts">nota: {safe_float(row['n_prop_ativas'])*10:.1f}</div>
                        {score_bar(row['n_prop_ativas'], '#10b981')}
                    </div>
                    <div class="detail-cell pos">
                        <div class="d-label">📅 Total Visitas (equipe)</div>
                        <div class="d-qty">{int(safe_float(row['total_visitas_presenciais']))}</div>
                        <div class="d-pts">nota: {safe_float(row['n_total_visitas'])*10:.1f}</div>
                        {score_bar(row['n_total_visitas'], '#10b981')}
                    </div>
                    <div class="detail-cell pos">
                        <div class="d-label">📋 Total Orientações (equipe)</div>
                        <div class="d-qty">{int(safe_float(row['total_orientacoes_geral']))}</div>
                        <div class="d-pts">nota: {safe_float(row['n_ori_geral'])*10:.1f}</div>
                        {score_bar(row['n_ori_geral'], '#10b981')}
                    </div>
                    <div class="detail-cell pos">
                        <div class="d-label">✅ Taxa Visitas Válidas</div>
                        <div class="d-qty">{safe_float(row['pct_visitas_validas']):.0f}%</div>
                        <div class="d-pts">nota: {safe_float(row['n_taxa_validade'])*10:.1f}</div>
                        {score_bar(row['n_taxa_validade'], '#2563eb')}
                    </div>
                    <div class="detail-cell pos">
                        <div class="d-label">✔️ Taxa Orient. Concluídas</div>
                        <div class="d-qty">{safe_float(row['pct_ori_concluidas']):.0f}%</div>
                        <div class="d-pts">nota: {safe_float(row['n_taxa_ori_concluidas'])*10:.1f}</div>
                        {score_bar(row['n_taxa_ori_concluidas'], '#2563eb')}
                    </div>
                    <div class="detail-cell neg">
                        <div class="d-label">🚫 Prop. Inativas (equipe)</div>
                        <div class="d-qty">{int(safe_float(row['propriedades_inativas']))}</div>
                        <div class="d-pts">nota: {safe_float(row['n_prop_inativas'])*10:.1f}</div>
                        {score_bar(row['n_prop_inativas'], '#ef4444')}
                    </div>
                    <div class="detail-cell pen">
                        <div class="d-label">⚠️ Repetição-Projeto (equipe)</div>
                        <div class="d-qty">{int(safe_float(row['qtd_multiplos_projetos']))}</div>
                        <div class="d-pts">nota: {safe_float(row['n_multi_projetos'])*10:.1f}</div>
                        {score_bar(row['n_multi_projetos'], '#f59e0b')}
                    </div>
                    <div class="detail-cell tot">
                        <div class="d-label">🏆 Nota Final da Equipe</div>
                        <div class="d-qty" style="color:#2563eb;font-size:1.2rem">{nota*10:.2f}</div>
                        <div class="d-pts">Posição #{pos} · líder em {qtd_lider}/7</div>
                        {score_bar(nota, '#2563eb')}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                st.markdown(
                    '<div style="font-size:0.78rem;font-weight:700;color:#374151;margin:12px 0 6px">'
                    '🧑‍🌾 Técnicos da equipe (ordenados por desempenho)</div>',
                    unsafe_allow_html=True
                )
                df_tecs_sup = df_base_sup[df_base_sup[col_sup] == sup_nome].sort_values("nota_final", ascending=False)
                tabela_tecs = df_tecs_sup[[
                    "tecnico_responsavel","nota_final","propriedades_ativas","propriedades_inativas",
                    "total_visitas_presenciais","pct_visitas_validas","total_orientacoes_geral","pct_ori_concluidas",
                ]].copy()
                tabela_tecs["nota_final"] = (pd.to_numeric(tabela_tecs["nota_final"], errors="coerce") * 100).round(1)
                tabela_tecs.columns = [
                    "Técnico","Nota Final (%)","Ativas","Inativas","Visitas","% Válidas","Orientações","% Concluídas",
                ]
                st.dataframe(tabela_tecs, use_container_width=True, hide_index=True)

        # ── Tabela comparativa entre supervisores + downloads ──
        st.markdown(f'<p class="section-title" style="margin-top:12px">Comparativo entre {rotulo_sup_plural}</p>', unsafe_allow_html=True)
        comp_sup = df_supv[[
            "pos","supervisor","nota_final","qtd_tecnicos",
            "propriedades_ativas","propriedades_inativas",
            "total_visitas_presenciais","pct_visitas_validas",
            "total_orientacoes_geral","total_orientacoes_concluidas","pct_ori_concluidas",
            "qtd_multiplos_projetos",
        ]].copy()
        comp_sup.columns = [
            "Pos","Supervisor","Nota Final","Qtd. Técnicos",
            "Ativas","Inativas",
            "Total Visitas","% Válidas",
            "Total Orient.","Orient. Concluídas","% Concluídas",
            "Repet.-Proj.",
        ]
        comp_sup["Pos"] = comp_sup["Pos"].astype(int)
        comp_sup["Nota Final"] = (pd.to_numeric(comp_sup["Nota Final"], errors="coerce") * 100).round(1)

        st.dataframe(comp_sup, use_container_width=True, hide_index=True,
            column_config={"Nota Final": st.column_config.NumberColumn(format="%.1f%%")})

        import io as _io
        import re as _re
        slug_sup = _re.sub(r"[^a-zA-Z0-9]+", "_", rotulo_sup_plural).strip("_").lower()
        csv_sup      = comp_sup.to_csv(index=False)
        xlsx_buf_sup = _io.BytesIO()
        comp_sup.to_excel(xlsx_buf_sup, index=False, engine="openpyxl")
        xlsx_buf_sup.seek(0)

        col_csv_sup, col_xlsx_sup = st.columns([1, 1])
        with col_csv_sup:
            st.download_button("📥 Baixar CSV", data=csv_sup,
                                file_name=f"ranking_{slug_sup}.csv",
                                mime="text/csv", use_container_width=True)
        with col_xlsx_sup:
            st.download_button("📊 Baixar Excel", data=xlsx_buf_sup,
                                file_name=f"ranking_{slug_sup}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True)

        st.stop()

# ── FILTRO SUPERVISOR / PROJETO / TÉCNICO ───────────────────────────────────
col_tipo, col_val, col_val2 = st.columns([1.5, 3, 3])
with col_tipo:
    modo = st.selectbox("🔎 Filtrar por", [
        "Supervisor Atual",
        "Supervisor Anterior",       # ← NOVO
        "Projeto",
        "Atividade",
        "Projeto → Atividade",
        "Técnico",
    ])

with col_val:
    if modo == "Supervisor Atual":
        opcoes = ["Todos"] + sorted(df["ultimo_supervisor"].dropna().astype(str).unique())
        sup = st.selectbox("👤 Supervisor Atual", opcoes)
        if sup == "Todos":
            df_sup = df.sort_values("pos")
        else:
            df_sup = df[df["ultimo_supervisor"] == sup].sort_values("pos")
        col_pos = "pos"

    elif modo == "Supervisor Anterior":
        opcoes_ant = sorted(df["ultimo_supervisor_anterior"].dropna().astype(str).unique())
        if not opcoes_ant:
            st.warning("Nenhum supervisor anterior encontrado no período.")
            st.stop()
        opcoes_ant = ["Todos"] + opcoes_ant
        sup = st.selectbox("👤 Supervisor Anterior", opcoes_ant)
        if sup == "Todos":
            df_sup = df[df["ultimo_supervisor_anterior"].notna()].sort_values("pos_sup_anterior")
        else:
            df_sup = df[df["ultimo_supervisor_anterior"] == sup].sort_values("pos_sup_anterior")
        col_pos = "pos_sup_anterior"

    elif modo == "Projeto":
        projetos = ["Todos"] + sorted(df["ultimo_projeto"].dropna().astype(str).unique())
        proj = st.selectbox("📁 Projeto", projetos)
        if proj == "Todos":
            df_sup = df.sort_values("pos_projeto")
        else:
            df_sup = df[df["ultimo_projeto"] == proj].sort_values("pos_projeto")
        col_pos = "pos_projeto"
        sup = proj

    elif modo == "Atividade":
        atividades = ["Todos"] + sorted(df["ultima_atividade"].dropna().astype(str).unique())
        atv = st.selectbox("🌱 Atividade", atividades)
        if atv == "Todos":
            df_sup = df.sort_values("pos_atividade")
        else:
            df_sup = df[df["ultima_atividade"] == atv].sort_values("pos_atividade")
        col_pos = "pos_atividade"
        sup = atv

    elif modo == "Projeto → Atividade":
        projetos = ["Todos"] + sorted(df["ultimo_projeto"].dropna().astype(str).unique())
        proj = st.selectbox("📁 Projeto", projetos)
        if proj == "Todos":
            df_proj = df.copy()
        else:
            df_proj = df[df["ultimo_projeto"] == proj]
        sup = proj
        col_pos = "pos_atividade"

    elif modo == "Técnico":
        tecnicos = ["Todos"] + sorted(df["tecnico_responsavel"].dropna().astype(str).unique())
        tec = st.selectbox("🧑‍🌾 Técnico", tecnicos)
        if tec == "Todos":
            df_sup = df.sort_values("pos")
        else:
            df_sup = df[df["tecnico_responsavel"] == tec].sort_values("pos")
        col_pos = "pos"
        sup = tec

with col_val2:
    if modo == "Projeto → Atividade":
        atividades_proj = ["Todos"] + sorted(df_proj["ultima_atividade"].dropna().astype(str).unique())
        if len(atividades_proj) > 1:
            atv = st.selectbox("🌱 Atividade", atividades_proj)
            if atv == "Todos":
                df_sup = df_proj.sort_values("pos_atividade")
                sup = f"{proj} / Todos"
            else:
                df_sup = df_proj[df_proj["ultima_atividade"] == atv].sort_values("pos_atividade")
                sup = f"{proj} / {atv}"
        else:
            st.warning("Nenhuma atividade encontrada para este projeto.")
            df_sup = pd.DataFrame()
    else:
        st.empty()

if col_pos != "pos":
    df_sup = df_sup.copy()
    df_sup["pos"] = df_sup[col_pos]

if df_sup.empty:
    st.warning("Nenhum técnico encontrado.")
    st.stop()

# ── RECALCULA SCORES NO GRUPO (função definida no topo do arquivo) ──────────
df_sup = recalcular_scores(df_sup).sort_values("nota_final", ascending=False).reset_index(drop=True)


tab1_tec, tab_dist_tec, tab2_tec = st.tabs(["🏆 Ranking", "📊 Distribuição", "🔎 Detalhes por Técnico"])
with tab1_tec:
    # ── MÉTRICAS ─────────────────────────────────────────────────────────────────
    media_validas = df_sup["pct_visitas_validas"].mean()
    media_ori     = df_sup["pct_ori_concluidas"].mean()
    st.markdown(f"""
    <div class="metric-strip">
        <div class="metric-card">
            <div class="label">👥 Técnicos</div>
            <div class="value">{len(df_sup)}</div>
        </div>
        <div class="metric-card green">
            <div class="label">🏆 Melhor Score</div>
            <div class="value">{safe_float(df_sup['nota_final'].max())*100:.1f}%</div>
        </div>
        <div class="metric-card red">
            <div class="label">📉 Pior Score</div>
            <div class="value">{safe_float(df_sup['nota_final'].min())*100:.1f}%</div>
        </div>
        <div class="metric-card yellow">
            <div class="label">✅ Média Visitas Válidas</div>
            <div class="value">{safe_float(media_validas):.1f}%</div>
        </div>
        <div class="metric-card purple">
            <div class="label">✔️ Média Orient. Concl.</div>
            <div class="value">{safe_float(media_ori):.1f}%</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── RANKING + HEATMAP ────────────────────────────────────────────────────────
    col_rank, col_chart = st.columns([1, 1], gap="medium")

    with col_rank:
        st.markdown('<p class="section-title">Classificação</p>', unsafe_allow_html=True)
        for _, row in df_sup.iterrows():
            pos  = int(row["pos"])
            nota = safe_float(row["nota_final"])
            pct  = nota * 100
            medalha = "🥇" if pos==1 else "🥈" if pos==2 else "🥉" if pos==3 else f"#{pos}"
            classe  = "gold" if pos==1 else "silver" if pos==2 else "bronze" if pos==3 else ""
            cap_tag = " ⏱️" if safe_float(row["total_de_visitas"]) == 30 else ""
            st.markdown(f"""
            <div class="rank-row {classe}">
                <span class="rank-pos">{medalha}</span>
                <span class="rank-name">{row['tecnico_responsavel']}{cap_tag}</span>
                <div class="rank-bar"><div class="rank-bar-fill" style="width:{pct:.1f}%"></div></div>
                <span class="rank-score">{pct:.1f}%</span>
            </div>
            """, unsafe_allow_html=True)

    with col_chart:
        st.markdown('<p class="section-title">Score por indicador</p>', unsafe_allow_html=True)
        indicadores = {
            "n_prop_ativas":         "Prop. Ativas",
            "n_prop_inativas":       "Prop. Inativas",
            "n_total_visitas":       "Total Visitas",
            "n_taxa_validade":       "Visitas Váliadas",
            "n_ori_geral":           "Total Orientacões",
            "n_taxa_ori_concluidas": "Orientacoes Concluídas",
            "n_multi_projetos":      "Repetição-Projeto",
        }
        # Coluna absoluta correspondente a cada indicador normalizado (usada como rótulo da célula)
        colunas_absolutas = {
            "n_prop_ativas":         ("propriedades_ativas",        "{:.0f}"),
            "n_total_visitas":       ("total_visitas_presenciais",  "{:.0f}"),
            "n_ori_geral":           ("total_orientacoes_geral",    "{:.0f}"),
            "n_taxa_validade":       ("total_visitas_validas",      "{:.0f}"),
            "n_taxa_ori_concluidas": ("total_orientacoes_concluidas","{:.0f}"),
            "n_prop_inativas":       ("propriedades_inativas",      "{:.0f}"),
            "n_multi_projetos":      ("qtd_multiplos_projetos",     "{:.0f}"),
        }

        chart_df  = df_sup.sort_values("nota_final", ascending=False).copy()
        z         = [[safe_float(row[col]) for col in indicadores.keys()] for _, row in chart_df.iterrows()]
        tecnicos  = chart_df["tecnico_responsavel"].tolist()
        labels    = list(indicadores.values())

        # Texto exibido na célula = valor absoluto; hover mostra valor absoluto + score normalizado
        abs_vals = [
            [safe_float(row[colunas_absolutas[col][0]]) for col in indicadores.keys()]
            for _, row in chart_df.iterrows()
        ]
        text_abs = [
            [
                colunas_absolutas[col][1].format(safe_float(row[colunas_absolutas[col][0]]))
                + f" ({safe_float(row[col]) * 10:.1f})"
                for col in indicadores.keys()
            ]
            for _, row in chart_df.iterrows()
        ]

        fig = go.Figure(go.Heatmap(
            z=z, x=labels, y=tecnicos,
            colorscale="RdYlGn", zmin=0, zmax=1, showscale=True,
            colorbar=dict(thickness=12, len=0.8, tickformat=".0%"),
            customdata=abs_vals,
            hovertemplate="%{y}<br>%{x}: valor %{customdata} · score %{z:.4f}<extra></extra>",
        ))

        # Anotações com cor dinâmica: branco em verde/vermelho escuro, preto no amarelo/laranja
        annotations = []
        for i, row_vals in enumerate(z):
            for j, val in enumerate(row_vals):
                # RdYlGn: ~0.3–0.7 são tons claros (amarelo/laranja) → texto escuro
                txt_color = "#111827" if 0.25 <= val <= 0.75 else "white"
                annotations.append(dict(
                    x=labels[j], y=tecnicos[i],
                    text=text_abs[i][j],
                    showarrow=False,
                    font=dict(size=10, color=txt_color),
                    xref="x", yref="y",
                ))

        fig.update_layout(
            height=max(220, len(tecnicos) * 50 + 80),
            margin=dict(l=0, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(size=11, color="#111827"),
            xaxis=dict(side="top", tickangle=-30, tickfont=dict(color="#111827")),
            yaxis=dict(autorange="reversed", tickfont=dict(color="#111827")),
            annotations=annotations,
        )
        st.plotly_chart(fig, use_container_width=True)

with tab_dist_tec:
    # ── GRÁFICOS SECUNDÁRIOS ─────────────────────────────────────────────────────
    st.markdown('<p class="section-title" style="margin-top:8px">Distribuição</p>', unsafe_allow_html=True)
    col_a, col_b = st.columns(2, gap="medium")

    # ── Preparar dados e calcular altura sincronizada ──
    comp = df_sup[["tecnico_responsavel","propriedades_ativas","propriedades_inativas"]].sort_values("propriedades_ativas", ascending=True)
    ori = df_sup[["tecnico_responsavel","total_orientacoes_geral","total_orientacoes_concluidas","pct_ori_concluidas"]].sort_values("total_orientacoes_geral", ascending=True)
    
    # ── Altura fixa máxima: 28px por técnico, mínimo 320, máximo 600 ──
    n_max = max(len(comp), len(ori))
    chart_height = min(600, max(320, n_max * 28 + 80))

    _cfg = {"displayModeBar": False, "scrollZoom": False}

    with col_a:
        fig2 = go.Figure(data=[
            go.Bar(name="Ativas",   x=comp["propriedades_ativas"],   y=comp["tecnico_responsavel"],
                   orientation="h", marker_color="#10b981",
                   text=comp["propriedades_ativas"], textposition="inside", insidetextanchor="end", textfont=dict(size=10,color="white")),
            go.Bar(name="Inativas", x=comp["propriedades_inativas"], y=comp["tecnico_responsavel"],
                   orientation="h", marker_color="#fca5a5",
                   text=comp["propriedades_inativas"], textposition="inside", insidetextanchor="end", textfont=dict(size=10,color="#7f1d1d")),
        ])
        fig2.update_layout(barmode="group", height=chart_height,
            title_text="Propriedades — Ativas vs Inativas", title_font_size=12,
            margin=dict(l=0,r=10,t=36,b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h",y=1.08,x=0,font_size=10), font=dict(size=11, color="#111827"),
            xaxis=dict(showgrid=True,gridcolor="#f0f0f0",zeroline=False),
            yaxis=dict(showgrid=False, automargin=True, tickfont=dict(size=9)),
            bargap=0.2, bargroupgap=0.05)
        st.plotly_chart(fig2, use_container_width=True, config=_cfg)

    with col_b:
        fig3 = go.Figure(data=[
            go.Bar(name="Total", x=ori["total_orientacoes_geral"], y=ori["tecnico_responsavel"],
                   orientation="h", marker=dict(color="#bfdbfe"),
                   hovertemplate="%{y}<br>Total: %{x}<extra></extra>"),
            go.Bar(name="Concluídas", x=ori["total_orientacoes_concluidas"], y=ori["tecnico_responsavel"],
                   orientation="h", marker=dict(color="#2563eb"),
                   text=[f"{int(v)}  ({p}%)" for v,p in zip(ori["total_orientacoes_concluidas"], ori["pct_ori_concluidas"])],
                   textposition="inside", insidetextanchor="end", textfont=dict(size=10,color="white"),
                   hovertemplate="%{y}<br>Concluídas: %{x}<extra></extra>"),
        ])
        fig3.update_layout(barmode="overlay", height=chart_height,
            title_text="Orientações — Total vs Concluídas", title_font_size=12,
            margin=dict(l=0,r=10,t=36,b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            legend=dict(orientation="h",y=1.08,x=0,font_size=10), font=dict(size=11, color="#111827"),
            xaxis=dict(showgrid=True,gridcolor="#f0f0f0",zeroline=False),
            yaxis=dict(showgrid=False, automargin=True, tickfont=dict(size=9)), bargap=0.25)
        st.plotly_chart(fig3, use_container_width=True, config=_cfg)

with tab2_tec:
    # ── DETALHES POR TÉCNICO ─────────────────────────────────────────────────────
    st.markdown('<p class="section-title" style="margin-top:8px">Detalhes por Técnico</p>', unsafe_allow_html=True)

    _ind_cols = {
        "n_prop_ativas":         "Prop. Ativas",
        "n_total_visitas":       "Total Visitas",
        "n_ori_geral":           "Orientações",
        "n_taxa_validade":       "Taxa Válidas",
        "n_taxa_ori_concluidas": "Taxa Concluídas",
        "n_prop_inativas":       "Prop. Inativas",
        "n_multi_projetos":      "Repetição-Projeto",
    }
    _lideres = {}
    for _col in _ind_cols:
        _max_val = df_sup[_col].max()
        _lideres[_col] = set(df_sup.loc[df_sup[_col] == _max_val, "tecnico_responsavel"].tolist())

    for _, row in df_sup.iterrows():
        pos  = int(row["pos"])
        nota = safe_float(row["nota_final"])
        medalha  = "🥇" if pos==1 else "🥈" if pos==2 else "🥉" if pos==3 else f"#{pos}"
        tec_nome = row["tecnico_responsavel"]
        cap_info = " ⏱️ cap 30" if safe_float(row["total_de_visitas"]) == 30 else ""
        sup_ant  = row.get("ultimo_supervisor_anterior", None)
        sup_ant_str = f" · Sup. anterior: {sup_ant}" if pd.notna(sup_ant) and str(sup_ant).strip() else ""

        lider_em     = [nome for col, nome in _ind_cols.items() if tec_nome in _lideres[col]]
        atras_em     = [nome for col, nome in _ind_cols.items() if tec_nome not in _lideres[col]]
        badges_lider = "".join([f'<span style="background:#d1fae5;color:#065f46;border-radius:12px;padding:2px 8px;font-size:0.72rem;margin:2px;display:inline-block">🏆 {n}</span>' for n in lider_em])
        badges_atras = "".join([f'<span style="background:#fee2e2;color:#7f1d1d;border-radius:12px;padding:2px 8px;font-size:0.72rem;margin:2px;display:inline-block">📉 {n}</span>' for n in atras_em])

        n_scores   = [safe_float(row[c]) * 10 for c in _ind_cols]
        explicacao = " + ".join([f"{v:.1f}" for v in n_scores])
        qtd_lider  = len(lider_em)
        penalidade_html = (
            "&nbsp;&nbsp;<span style=\"background:#fef3c7;color:#92400e;border-radius:8px;"
            "padding:1px 7px;font-size:0.7rem\">⚠️ repetição de projeto (nota 5 neste critério)</span>"
            if safe_float(row["qtd_multiplos_projetos"]) > 0 else ""
        )

        with st.expander(
            f"{medalha} {tec_nome}{cap_info}  ·  nota {nota*10:.2f}  "
            f"·  Válidas {safe_float(row['pct_visitas_validas']):.0f}%  "
            f"·  Orient. {safe_float(row['pct_ori_concluidas']):.0f}%{sup_ant_str}"
        ):
            painel_html = (
                '<div style="background:#f8fafc;border-radius:8px;padding:10px 14px;margin-bottom:12px;border:1px solid #e2e8f0">'
                '<div style="font-size:0.75rem;color:#64748b;margin-bottom:6px;font-weight:600">📊 COMO A NOTA '
                + f"{nota*10:.2f} FOI CALCULADA</div>"
                + '<div style="font-size:0.78rem;color:#374151;margin-bottom:8px">'
                + f"Média das 7 notas: ({explicacao}) ÷ 7 = <strong>{nota*10:.2f}</strong>"
                + penalidade_html
                + '</div>'
                + f'<div style="font-size:0.75rem;color:#64748b;margin-bottom:4px;font-weight:600">✅ MELHOR DO GRUPO NESTES INDICADORES ({qtd_lider}/7) — nota 10:</div>'
                + '<div style="margin-bottom:6px">'
                + (badges_lider if badges_lider else '<span style="color:#9ca3af;font-size:0.75rem">Nenhum</span>')
                + '</div>'
                + '<div style="font-size:0.75rem;color:#64748b;margin-bottom:4px;font-weight:600">⚠️ NÃO É O MELHOR DO GRUPO NESTES INDICADORES:</div>'
                + '<div>'
                + (badges_atras if badges_atras else '<span style="color:#10b981;font-size:0.75rem">🏆 Melhor do grupo em todos os indicadores!</span>')
                + '</div></div>'
            )
            st.markdown(painel_html, unsafe_allow_html=True)

            st.markdown(f"""
            <div class="detail-grid">
                <div class="detail-cell pos">
                    <div class="d-label">🚜 Prop. Ativas {"🏆" if tec_nome in _lideres["n_prop_ativas"] else ""}</div>
                    <div class="d-qty">{int(safe_float(row['propriedades_ativas']))}</div>
                    <div class="d-pts">nota: {safe_float(row['n_prop_ativas'])*10:.1f} · melhor: {df_sup['propriedades_ativas'].max():.0f}</div>
                    {score_bar(row['n_prop_ativas'], '#10b981')}
                </div>
                <div class="detail-cell pos">
                    <div class="d-label">📅 Total Visitas {"🏆" if tec_nome in _lideres["n_total_visitas"] else ""} {"⏱️" if safe_float(row['total_de_visitas'])==30 else ""}</div>
                    <div class="d-qty">{int(safe_float(row['total_visitas_presenciais']))} <span style="font-size:0.72rem;color:#6b7280">(de {int(safe_float(row['total_de_visitas']))} contadas)</span></div>
                    <div class="d-pts">nota: {safe_float(row['n_total_visitas'])*10:.1f} · melhor: {df_sup['total_visitas_presenciais'].max():.0f}</div>
                    {score_bar(row['n_total_visitas'], '#10b981')}
                </div>
                <div class="detail-cell pos">
                    <div class="d-label">📋 Total Orientações {"🏆" if tec_nome in _lideres["n_ori_geral"] else ""}</div>
                    <div class="d-qty">{int(safe_float(row['total_orientacoes_geral']))}</div>
                    <div class="d-pts">nota: {safe_float(row['n_ori_geral'])*10:.1f} · melhor: {df_sup['total_orientacoes_geral'].max():.0f}</div>
                    {score_bar(row['n_ori_geral'], '#10b981')}
                </div>
                <div class="detail-cell pos">
                    <div class="d-label">✅ Taxa Visitas Válidas {"🏆" if tec_nome in _lideres["n_taxa_validade"] else ""}</div>
                    <div class="d-qty">{safe_float(row['pct_visitas_validas']):.0f}%</div>
                    <div class="d-pts">nota: {safe_float(row['n_taxa_validade'])*10:.1f} · melhor: {df_sup['pct_visitas_validas'].max():.0f}%</div>
                    {score_bar(row['n_taxa_validade'], '#2563eb')}
                </div>
                <div class="detail-cell pos">
                    <div class="d-label">✔️ Taxa Orient. Concluídas {"🏆" if tec_nome in _lideres["n_taxa_ori_concluidas"] else ""}</div>
                    <div class="d-qty">{safe_float(row['pct_ori_concluidas']):.0f}%</div>
                    <div class="d-pts">nota: {safe_float(row['n_taxa_ori_concluidas'])*10:.1f} · melhor: {df_sup['pct_ori_concluidas'].max():.0f}%</div>
                    {score_bar(row['n_taxa_ori_concluidas'], '#2563eb')}
                </div>
                <div class="detail-cell neg">
                    <div class="d-label">🚫 Prop. Inativas {"🏆" if tec_nome in _lideres["n_prop_inativas"] else ""}</div>
                    <div class="d-qty">{int(safe_float(row['propriedades_inativas']))}</div>
                    <div class="d-pts">nota: {safe_float(row['n_prop_inativas'])*10:.1f} · menor: {df_sup['propriedades_inativas'].min():.0f}</div>
                    {score_bar(row['n_prop_inativas'], '#ef4444')}
                </div>
                <div class="detail-cell pen">
                    <div class="d-label">⚠️ Repetição-Projeto {"🏆" if tec_nome in _lideres["n_multi_projetos"] else ""}</div>
                    <div class="d-qty">{int(safe_float(row['qtd_multiplos_projetos']))}</div>
                    <div class="d-pts">nota: {safe_float(row['n_multi_projetos'])*10:.1f} · menor: {df_sup['qtd_multiplos_projetos'].min():.0f}</div>
                    {score_bar(row['n_multi_projetos'], '#f59e0b')}
                </div>
                <div class="detail-cell tot">
                    <div class="d-label">🏆 Nota Final — média dos 7</div>
                    <div class="d-qty" style="color:#2563eb;font-size:1.2rem">{nota*10:.2f}</div>
                    <div class="d-pts">Posição #{pos} · líder em {qtd_lider}/7 indicadores</div>
                    {score_bar(nota, '#2563eb')}
                </div>
            </div>
            """, unsafe_allow_html=True)

    # ── TABELA COMPARATIVA ───────────────────────────────────────────────────────
    st.markdown('<p class="section-title" style="margin-top:12px">Comparativo da Equipe</p>', unsafe_allow_html=True)

    comp_df = df_sup[[
        "pos","tecnico_responsavel","nota_final",
        "propriedades_ativas","n_prop_ativas",
        "propriedades_inativas","n_prop_inativas",
        "total_visitas_presenciais","n_total_visitas",
        "pct_visitas_validas","n_taxa_validade",
        "total_orientacoes_geral","total_orientacoes_concluidas","n_ori_geral",
        "pct_ori_concluidas","n_taxa_ori_concluidas",
        "qtd_multiplos_projetos","n_multi_projetos",
        "total_de_visitas",
    ]].copy()

    comp_df.columns = [
        "Pos","Técnico","Nota Final",
        "Ativas","Nota Ativas",
        "Inativas","Nota Inativas",
        "Total Visitas Presenciais","Nota Visitas",
        "% Válidas","Nota Taxa Válidas",
        "Total Orient.","Orient. Concluídas","Nota Orient.",
        "% Concluídas","Nota Taxa Concl.",
        "Repet.-Proj.","Nota Repet.-Proj.",
        "Visitas Contadas (máx 30)",
    ]

    comp_df["Pos"] = comp_df["Pos"].astype(int)
    comp_df["Nota Final"] = (pd.to_numeric(comp_df["Nota Final"], errors="coerce")*10).round(2)
    for c in ["Ativas","Inativas","Total Visitas Presenciais","Total Orient.","Orient. Concluídas","Repet.-Proj.","Visitas Contadas (máx 30)"]:
        comp_df[c] = pd.to_numeric(comp_df[c], errors="coerce").fillna(0).astype(int)
    for c in ["Nota Ativas","Nota Inativas","Nota Visitas","Nota Taxa Válidas",
              "Nota Orient.","Nota Taxa Concl.","Nota Repet.-Proj."]:
        comp_df[c] = (pd.to_numeric(comp_df[c], errors="coerce")*10).round(1)

    st.dataframe(comp_df, use_container_width=True, hide_index=True,
        column_config={"Nota Final": st.column_config.NumberColumn(format="%.2f")})

    import io
    csv      = comp_df.to_csv(index=False)
    xlsx_buf = io.BytesIO()
    comp_df.to_excel(xlsx_buf, index=False, engine="openpyxl")
    xlsx_buf.seek(0)

    col_csv, col_xlsx = st.columns([1, 1])
    with col_csv:
        st.download_button("📥 Baixar CSV",   data=csv,      file_name=f"ranking_{sup}.csv",  mime="text/csv",                use_container_width=True)
    with col_xlsx:
        st.download_button("📊 Baixar Excel", data=xlsx_buf, file_name=f"ranking_{sup}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)