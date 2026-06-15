import streamlit as st
import pandas as pd
import os
import plotly.graph_objects as go
from sqlalchemy import create_engine, URL
from dotenv import load_dotenv

load_dotenv()

# =====================================
# HELPER — trata NaN e None com segurança
# =====================================
def safe_float(val, default=0.0):
    try:
        v = float(val)
        return default if pd.isna(v) else v
    except (TypeError, ValueError):
        return default

# =====================================
# CONEXÃO
# =====================================
def get_engine():
    url = URL.create(
        "postgresql+psycopg2",
        username=os.getenv("REMOTE_DB_USER", "postgres"),
        password=os.getenv("REMOTE_DB_PASS"),
        host=os.getenv("REMOTE_DB_HOST", "177.22.38.27"),
        port=os.getenv("REMOTE_DB_PORT", "6432"),
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
        '{dt_fim}'::DATE AS dt_fim
),

-- HISTÓRICO GLOBAL: Busca toda a base de dados sem travar no período do mês
HistoricoCompletoProjetos AS (
    SELECT 
        tecnico_responsavel,
        id_propriedade,
        COUNT(DISTINCT id_projeto) AS total_projetos_por_propriedade
    FROM public.acompanhamento_mensal_visitas
    GROUP BY tecnico_responsavel, id_propriedade
),

-- Conta as propriedades que possuem duplicidade histórica por técnico
PropriedadesSobrepostasGlobal AS (
    SELECT 
        tecnico_responsavel,
        COUNT(DISTINCT id_propriedade) AS total_propriedades_com_multiplos_projetos
    FROM HistoricoCompletoProjetos
    WHERE total_projetos_por_propriedade > 1
    GROUP BY tecnico_responsavel
),

UltimoSupervisorPorTecnico AS (
    SELECT DISTINCT ON (tecnico_responsavel)
        tecnico_responsavel,
        supervisor_atual AS ultimo_supervisor
    FROM public.acompanhamento_mensal_visitas
    WHERE dt_visita BETWEEN (SELECT dt_inicio FROM Parametros) AND (SELECT dt_fim FROM Parametros)
    ORDER BY tecnico_responsavel, dt_visita DESC
),

UltimoProjetoPorTecnico AS (
    SELECT DISTINCT ON (tecnico_responsavel)
        tecnico_responsavel,
        projeto_consolidado AS ultimo_projeto
    FROM public.acompanhamento_mensal_visitas
    WHERE dt_visita BETWEEN (SELECT dt_inicio FROM Parametros) AND (SELECT dt_fim FROM Parametros)
      AND projeto_consolidado IS NOT NULL
    ORDER BY tecnico_responsavel, dt_visita DESC
),

UltimaAtividadePorTecnico AS (
    SELECT DISTINCT ON (tecnico_responsavel)
        tecnico_responsavel,
        atividade AS ultima_atividade
    FROM public.acompanhamento_mensal_visitas
    WHERE dt_visita BETWEEN (SELECT dt_inicio FROM Parametros) AND (SELECT dt_fim FROM Parametros)
      AND atividade IS NOT NULL
    ORDER BY tecnico_responsavel, dt_visita DESC
),

ResumoTecnicos AS (
    SELECT
        tecnico_responsavel,
        COUNT(DISTINCT CASE WHEN vinculo_status = 'ATIVA'   THEN id_propriedade END) AS propriedades_ativas,
        COUNT(DISTINCT CASE WHEN vinculo_status = 'INATIVA' THEN id_propriedade END) AS propriedades_inativas,
        COUNT(DISTINCT id_propriedade)                                                 AS total_propriedades_distintas,
        COUNT(*)                                                                       AS total_de_visitas,
        COUNT(CASE WHEN visita_presencial = 'SIM' THEN 1 END)                         AS total_visitas_presenciais,
        COUNT(CASE WHEN visita_valida = 'Valida' AND visita_presencial = 'SIM' THEN 1 END) AS total_visitas_validas,
        SUM(COALESCE(ori_total_geral, 0))                                              AS total_orientacoes_geral,
        SUM(COALESCE(ori_concluida, 0))                                                AS total_orientacoes_concluidas
    FROM public.acompanhamento_mensal_visitas
    WHERE dt_visita BETWEEN (SELECT dt_inicio FROM Parametros) AND (SELECT dt_fim FROM Parametros)
    GROUP BY tecnico_responsavel
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
        -- Substituído para ler os dados do histórico completo
        COALESCE(p.total_propriedades_com_multiplos_projetos, 0) AS qtd_multiplos_projetos
    FROM ResumoTecnicos r
    LEFT JOIN PropriedadesSobrepostasGlobal p ON r.tecnico_responsavel = p.tecnico_responsavel
    WHERE r.propriedades_ativas > 0
),

Normalizado AS (
    SELECT
        t.tecnico_responsavel,
        s.ultimo_supervisor,
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

        ROUND(t.taxa_validade * 100, 1) AS pct_visitas_validas,
        ROUND(t.taxa_ori_concluidas * 100, 1) AS pct_ori_concluidas,

        COALESCE(
            (t.propriedades_ativas - MIN(t.propriedades_ativas) OVER w)::NUMERIC
            / NULLIF(
                MAX(t.propriedades_ativas) OVER w -
                MIN(t.propriedades_ativas) OVER w,
                0
            ),
            1.0
        ) AS n_prop_ativas,

        COALESCE(
            (t.total_visitas_presenciais - MIN(t.total_visitas_presenciais) OVER w)::NUMERIC
            / NULLIF(
                MAX(t.total_visitas_presenciais) OVER w -
                MIN(t.total_visitas_presenciais) OVER w,
                0
            ),
            1.0
        ) AS n_total_visitas,

        COALESCE(
            (t.total_orientacoes_geral - MIN(t.total_orientacoes_geral) OVER w)::NUMERIC
            / NULLIF(
                MAX(t.total_orientacoes_geral) OVER w -
                MIN(t.total_orientacoes_geral) OVER w,
                0
            ),
            1.0
        ) AS n_ori_geral,

        COALESCE(
            (t.taxa_validade - MIN(t.taxa_validade) OVER w)
            / NULLIF(
                MAX(t.taxa_validade) OVER w -
                MIN(t.taxa_validade) OVER w,
                0
            ),
            1.0
        ) AS n_taxa_validade,

        COALESCE(
            (t.taxa_ori_concluidas - MIN(t.taxa_ori_concluidas) OVER w)
            / NULLIF(
                MAX(t.taxa_ori_concluidas) OVER w -
                MIN(t.taxa_ori_concluidas) OVER w,
                0
            ),
            1.0
        ) AS n_taxa_ori_concluidas,

        1.0 - COALESCE(
            (t.propriedades_inativas - MIN(t.propriedades_inativas) OVER w)::NUMERIC
            / NULLIF(
                MAX(t.propriedades_inativas) OVER w -
                MIN(t.propriedades_inativas) OVER w,
                0
            ),
            0.0
        ) AS n_prop_inativas,

        1.0 - COALESCE(
            (t.qtd_multiplos_projetos - MIN(t.qtd_multiplos_projetos) OVER w)::NUMERIC
            / NULLIF(
                MAX(t.qtd_multiplos_projetos) OVER w -
                MIN(t.qtd_multiplos_projetos) OVER w,
                0
            ),
            0.0
        ) AS n_multi_projetos

    FROM Taxas t
    LEFT JOIN UltimoSupervisorPorTecnico s
        ON t.tecnico_responsavel = s.tecnico_responsavel
    LEFT JOIN UltimoProjetoPorTecnico pr
        ON t.tecnico_responsavel = pr.tecnico_responsavel
    LEFT JOIN UltimaAtividadePorTecnico at
        ON t.tecnico_responsavel = at.tecnico_responsavel

    WINDOW w AS (
        -- Sem PARTITION: normalização global entre todos os técnicos,
        -- independente de supervisor/projeto/atividade.
        -- O ranking (pos, pos_projeto, pos_atividade) é que usa PARTITION.
        ORDER BY t.tecnico_responsavel
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    )
)
SELECT
    tecnico_responsavel,
    ultimo_supervisor,
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
    ROUND(
    CAST(
        CASE
            WHEN qtd_multiplos_projetos > 0 THEN
                (
                    (
                        COALESCE(n_prop_ativas,         0) +
                        COALESCE(n_total_visitas,       0) +
                        COALESCE(n_ori_geral,           0) +
                        COALESCE(n_taxa_validade,       0) +
                        COALESCE(n_taxa_ori_concluidas, 0) +
                        COALESCE(n_prop_inativas,       0) +
                        COALESCE(n_multi_projetos,      0)
                    ) / 7.0
                ) * 0.5
            ELSE
                (
                    COALESCE(n_prop_ativas,         0) +
                    COALESCE(n_total_visitas,       0) +
                    COALESCE(n_ori_geral,           0) +
                    COALESCE(n_taxa_validade,       0) +
                    COALESCE(n_taxa_ori_concluidas, 0) +
                    COALESCE(n_prop_inativas,       0) +
                    COALESCE(n_multi_projetos,      0)
                ) / 7.0
        END
    AS NUMERIC),
4) AS nota_final,

    DENSE_RANK() OVER (
    PARTITION BY ultimo_supervisor
    ORDER BY
    CASE
        WHEN qtd_multiplos_projetos > 0 THEN
            (
                (
                    COALESCE(n_prop_ativas,         0) +
                    COALESCE(n_total_visitas,       0) +
                    COALESCE(n_ori_geral,           0) +
                    COALESCE(n_taxa_validade,       0) +
                    COALESCE(n_taxa_ori_concluidas, 0) +
                    COALESCE(n_prop_inativas,       0) +
                    COALESCE(n_multi_projetos,      0)
                ) / 7.0
            ) * 0.5
        ELSE
            (
                COALESCE(n_prop_ativas,         0) +
                COALESCE(n_total_visitas,       0) +
                COALESCE(n_ori_geral,           0) +
                COALESCE(n_taxa_validade,       0) +
                COALESCE(n_taxa_ori_concluidas, 0) +
                COALESCE(n_prop_inativas,       0) +
                COALESCE(n_multi_projetos,      0)
            ) / 7.0
    END DESC
) AS pos,

    DENSE_RANK() OVER (
        PARTITION BY ultimo_projeto
        ORDER BY (
            COALESCE(n_prop_ativas,         0) +
            COALESCE(n_total_visitas,       0) +
            COALESCE(n_ori_geral,           0) +
            COALESCE(n_taxa_validade,       0) +
            COALESCE(n_taxa_ori_concluidas, 0) +
            COALESCE(n_prop_inativas,       0) +
            COALESCE(n_multi_projetos,      0)
        ) DESC
    ) AS pos_projeto,

    DENSE_RANK() OVER (
        PARTITION BY ultima_atividade
        ORDER BY (
            COALESCE(n_prop_ativas,         0) +
            COALESCE(n_total_visitas,       0) +
            COALESCE(n_ori_geral,           0) +
            COALESCE(n_taxa_validade,       0) +
            COALESCE(n_taxa_ori_concluidas, 0) +
            COALESCE(n_prop_inativas,       0) +
            COALESCE(n_multi_projetos,      0)
        ) DESC
    ) AS pos_atividade
FROM Normalizado
ORDER BY ultimo_supervisor, pos;
    """
    try:
        with engine.connect() as conn:
            return pd.read_sql(query, conn)
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
    )
    SELECT
        u.supervisor_atual,
        t.tecnico_responsavel,
        t.id_propriedade,
        t.imovel,
        t.cpf_produtor,
        string_agg(DISTINCT t.projeto_consolidado::text, ', ') as projetos_vinculados,
        COUNT(DISTINCT t.projeto_consolidado) as qtd_projetos
    FROM public.acompanhamento_mensal_visitas t
    JOIN UltimoSupervisor u ON t.tecnico_responsavel = u.tecnico_responsavel
    GROUP BY u.supervisor_atual,t.tecnico_responsavel,t.id_propriedade,t.imovel,t.cpf_produtor
    HAVING COUNT(DISTINCT t.projeto_consolidado) > 1
    """
    with engine.connect() as conn:
        return pd.read_sql(query, conn)

# =====================================
# CONFIG
# =====================================
st.set_page_config(page_title="Ranking ATeG", page_icon="🏆", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] { background: #f0f2f6; }
[data-testid="stAppViewContainer"] > .main > .block-container { max-width: 1200px; padding: 0 2rem 3rem; margin-top: 0 !important; padding-top: 0 !important; }
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
.page-header { background: linear-gradient(135deg,#064e3b 0%,#059669 100%); color:white; padding:20px 28px; border-radius:0; margin-bottom:20px; margin-left:-2rem; margin-right:-2rem; margin-top:-1rem; display:flex; align-items:center; justify-content:space-between; }
.page-header h1 { margin:0; font-size:1.4rem; font-weight:700; }
.page-header p  { margin:4px 0 0; font-size:0.8rem; opacity:0.7; }
.badge { background:rgba(255,255,255,0.15); padding:4px 10px; border-radius:20px; font-size:0.72rem; }
.metric-strip { display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-bottom:16px; }
.metric-card { background:white; border-radius:10px; padding:14px 16px; box-shadow:0 1px 4px rgba(0,0,0,0.06); border-top:3px solid #2563eb; }
.metric-card.green  { border-top-color:#10b981; }
.metric-card.red    { border-top-color:#ef4444; }
.metric-card.yellow { border-top-color:#f59e0b; }
.metric-card.purple { border-top-color:#8b5cf6; }
.metric-card .label { font-size:0.7rem; color:#374151; margin-bottom:4px; text-transform:uppercase; letter-spacing:0.5px; }
.metric-card .value { font-size:1.5rem; font-weight:700; color:#111827; line-height:1; }
.section-title { font-size:0.8rem; font-weight:700; text-transform:uppercase; letter-spacing:0.8px; color:#374151; margin:0 0 10px; }
.rank-row { background:white; border-radius:10px; padding:13px 16px; margin-bottom:8px; box-shadow:0 1px 4px rgba(0,0,0,0.05); display:flex; align-items:center; gap:14px; border-left:4px solid #e5e7eb; }
.rank-row.gold   { border-left-color:#f59e0b; background:linear-gradient(90deg,#fffbeb,white 60%); }
.rank-row.silver { border-left-color:#9ca3af; background:linear-gradient(90deg,#f9fafb,white 60%); }
.rank-row.bronze { border-left-color:#b45309; background:linear-gradient(90deg,#fef3c7,white 60%); }
.rank-pos   { font-size:1.1rem; width:40px; text-align:center; flex-shrink:0; }
.rank-name  { flex:1; font-size:0.92rem; font-weight:600; color:#111827; }
.rank-score { font-size:1.15rem; font-weight:700; color:#1d4ed8; flex-shrink:0; }
.rank-bar   { flex-shrink:0; width:80px; background:#e5e7eb; border-radius:6px; height:6px; overflow:hidden; }
.rank-bar-fill { height:100%; border-radius:6px; background:linear-gradient(90deg,#2563eb,#60a5fa); }
.detail-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:8px; margin:8px 0; }
.detail-cell { background:#f8fafc; border-radius:8px; padding:9px 12px; border-left:3px solid #e5e7eb; }
.detail-cell.pos { border-left-color:#10b981; }
.detail-cell.neg { border-left-color:#ef4444; }
.detail-cell.pen { border-left-color:#f59e0b; }
.detail-cell.tot { border-left-color:#2563eb; background:#eff6ff; }
.detail-cell .d-label { font-size:0.68rem; color:#374151; margin-bottom:2px; }
.detail-cell .d-qty   { font-size:1rem; font-weight:700; color:#111827; }
.detail-cell .d-pts   { font-size:0.7rem; color:#374151; }
.score-bar-wrap { margin-top:4px; background:#e5e7eb; border-radius:4px; height:5px; overflow:hidden; }
.score-bar-fill { height:100%; border-radius:4px; }
div[data-testid="stSelectbox"] label { font-size:0.75rem !important; font-weight:700 !important; text-transform:uppercase !important; letter-spacing:0.7px !important; color:#059669 !important; }
div[data-testid="stSelectbox"] > div > div { border: 1.5px solid #d1fae5 !important; border-radius: 10px !important; background: white !important; font-weight:600 !important; font-size:0.95rem !important; }
div[data-testid="stSelectbox"] > div > div:focus-within { border-color: #059669 !important; box-shadow: 0 0 0 3px rgba(5,150,105,0.15) !important; }
div[data-testid="stBaseButton-secondary"] button { background: #059669 !important; color: white !important; border: none !important; border-radius: 10px !important; font-weight:600 !important; }
</style>
""", unsafe_allow_html=True)

# =====================================
# HEADER
# =====================================
import calendar
from datetime import date

# =====================================
# HEADER
# =====================================
st.markdown("""
<div class="page-header">
    <div>
        <h1>🏆 Ranking de Performance ATeG</h1>
        <p>7 indicadores com peso igual (14,3% cada) · comparação dentro do grupo do supervisor</p>
    </div>
    <span class="badge">Nota 0 a 1</span>
</div>
""", unsafe_allow_html=True)


pagina = st.selectbox(
    "📋 Página",
    ["Ranking ATeG", "Gestão de Propriedades Multi-Projeto"]
)

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


# =====================================
# DIAGNÓSTICO — tabelas disponíveis
# =====================================
with st.expander("🔍 Ver tabelas disponíveis no banco (diagnóstico)", expanded=False):
    df_tabelas = listar_tabelas()
    st.dataframe(df_tabelas, use_container_width=True, hide_index=True)

# =====================================
# FILTROS DE PERÍODO + SUPERVISOR/TÉCNICO
# =====================================
MESES = {1:"Janeiro",2:"Fevereiro",3:"Março",4:"Abril",5:"Maio",6:"Junho",
         7:"Julho",8:"Agosto",9:"Setembro",10:"Outubro",11:"Novembro",12:"Dezembro"}

hoje = date.today()
col_mi, col_ai, col_mf, col_af, col_btn = st.columns([2, 1.2, 2, 1.2, 1])

with col_mi:
    mes_ini = st.selectbox("📅 Mês inicial", options=list(MESES.keys()),
                           format_func=lambda x: MESES[x], index=0)
with col_ai:
    ano_ini = st.selectbox("Ano inicial", options=[2024, 2025, 2026], index=2, label_visibility="visible")
with col_mf:
    mes_fim = st.selectbox("📅 Mês final", options=list(MESES.keys()),
                           format_func=lambda x: MESES[x], index=hoje.month - 1)
with col_af:
    ano_fim = st.selectbox("Ano final", options=[2024, 2025, 2026], index=2, label_visibility="visible")
with col_btn:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if st.button("🔄 Atualizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

dt_inicio = f"{ano_ini}-{mes_ini:02d}-01"
dt_fim    = f"{ano_fim}-{mes_fim:02d}-{calendar.monthrange(ano_fim, mes_fim)[1]}"

# =====================================
# DADOS
# =====================================
df = buscar_dados(dt_inicio, dt_fim)
if df is None or df.empty:
    st.warning("Nenhum dado encontrado para o período selecionado.")
    st.stop()

cols_num = [
    "n_prop_ativas","n_total_visitas","n_ori_geral",
    "n_taxa_validade","n_taxa_ori_concluidas","n_prop_inativas","n_multi_projetos",
    "nota_final","total_visitas_presenciais","total_de_visitas",
]
for c in cols_num:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

# =====================================
# FILTRO SUPERVISOR / PROJETO / TÉCNICO
# =====================================
col_tipo, col_val, col_val2 = st.columns([1.5, 3, 3])
with col_tipo:
    modo = st.selectbox("🔎 Filtrar por", ["Supervisor", "Projeto", "Atividade", "Projeto → Atividade", "Técnico"])
with col_val:
    if modo == "Supervisor":
        opcoes = sorted(df["ultimo_supervisor"].dropna().astype(str).unique())
        sup = st.selectbox("👤 Supervisor", opcoes)
        df_sup = df[df["ultimo_supervisor"] == sup].sort_values("pos")
        col_pos = "pos"
    elif modo == "Projeto":
        projetos = sorted(df["ultimo_projeto"].dropna().astype(str).unique())
        proj = st.selectbox("📁 Projeto", projetos)
        df_sup = df[df["ultimo_projeto"] == proj].sort_values("pos_projeto")
        col_pos = "pos_projeto"
        sup = proj
    elif modo == "Atividade":
        atividades = sorted(df["ultima_atividade"].dropna().astype(str).unique())
        atv = st.selectbox("🌱 Atividade", atividades)
        df_sup = df[df["ultima_atividade"] == atv].sort_values("pos_atividade")
        col_pos = "pos_atividade"
        sup = atv
    elif modo == "Projeto → Atividade":
        projetos = sorted(df["ultimo_projeto"].dropna().astype(str).unique())
        proj = st.selectbox("📁 Projeto", projetos)
        df_proj = df[df["ultimo_projeto"] == proj]
        sup = proj
        col_pos = "pos_atividade"
    elif modo == "Técnico":
        tecnicos = sorted(df["tecnico_responsavel"].dropna().astype(str).unique())
        tec = st.selectbox("🧑‍🌾 Técnico", tecnicos)
        df_sup = df[df["tecnico_responsavel"] == tec].sort_values("pos")
        col_pos = "pos"
        sup = tec

with col_val2:
    if modo == "Projeto → Atividade":
        atividades_proj = sorted(df_proj["ultima_atividade"].dropna().astype(str).unique())
        if atividades_proj:
            atv = st.selectbox("🌱 Atividade", atividades_proj)
            df_sup = df_proj[df_proj["ultima_atividade"] == atv].sort_values("pos_atividade")
            sup = f"{proj} / {atv}"
        else:
            st.warning("Nenhuma atividade encontrada para este projeto.")
            df_sup = pd.DataFrame()
    else:
        st.empty()

# Renomeia pos para uso uniforme no resto do código
if col_pos != "pos":
    df_sup = df_sup.copy()
    df_sup["pos"] = df_sup[col_pos]

if df_sup.empty:
    st.warning("Nenhum técnico encontrado.")
    st.stop()

# =====================================
# RECALCULA SCORES DENTRO DO GRUPO FILTRADO
# =====================================
def recalcular_scores(df_grupo):
    """Refaz normalização min-max usando apenas os técnicos do grupo filtrado."""
    df_g = df_grupo.copy()

    def minmax_pos(col):
        mn, mx = df_g[col].min(), df_g[col].max()
        if mx == mn:
            return pd.Series([1.0] * len(df_g), index=df_g.index)
        return (df_g[col] - mn) / (mx - mn)

    def minmax_neg(col):
        return 1.0 - minmax_pos(col)

    df_g["n_prop_ativas"]         = minmax_pos("propriedades_ativas")
    df_g["n_total_visitas"]       = minmax_pos("total_visitas_presenciais")
    df_g["n_ori_geral"]           = minmax_pos("total_orientacoes_geral")
    df_g["n_taxa_validade"]       = minmax_pos("pct_visitas_validas")
    df_g["n_taxa_ori_concluidas"] = minmax_pos("pct_ori_concluidas")
    df_g["n_prop_inativas"]       = minmax_neg("propriedades_inativas")
    df_g["n_multi_projetos"]      = minmax_neg("qtd_multiplos_projetos")

    cols = ["n_prop_ativas","n_total_visitas","n_ori_geral",
            "n_taxa_validade","n_taxa_ori_concluidas","n_prop_inativas","n_multi_projetos"]

    def nota(row):
        media = sum(safe_float(row[c]) for c in cols) / 7.0
        return round(media * 0.5, 4) if safe_float(row["qtd_multiplos_projetos"]) > 0 else round(media, 4)

    df_g["nota_final"] = df_g.apply(nota, axis=1)
    df_g["pos"] = df_g["nota_final"].rank(method="dense", ascending=False).astype(int)
    return df_g

df_sup = recalcular_scores(df_sup).sort_values("nota_final", ascending=False).reset_index(drop=True)

# =====================================
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

# =====================================
# RANKING + HEATMAP
# =====================================
col_rank, col_chart = st.columns([1, 1], gap="medium")

with col_rank:
    st.markdown('<p class="section-title">Classificação</p>', unsafe_allow_html=True)
    for _, row in df_sup.iterrows():
        pos  = int(row["pos"])
        nota = safe_float(row["nota_final"])
        pct  = nota * 100
        medalha = "🥇" if pos==1 else "🥈" if pos==2 else "🥉" if pos==3 else f"#{pos}"
        classe  = "gold" if pos==1 else "silver" if pos==2 else "bronze" if pos==3 else ""
        st.markdown(f"""
        <div class="rank-row {classe}">
            <span class="rank-pos">{medalha}</span>
            <span class="rank-name">{row['tecnico_responsavel']}</span>
            <div class="rank-bar"><div class="rank-bar-fill" style="width:{pct:.1f}%"></div></div>
            <span class="rank-score">{pct:.1f}%</span>
        </div>
        """, unsafe_allow_html=True)

with col_chart:
    st.markdown('<p class="section-title">Score por indicador</p>', unsafe_allow_html=True)
    indicadores = {
        "n_prop_ativas":         "Prop. ativas",
        "n_total_visitas":       "Total visitas",
        "n_ori_geral":           "Orientações",
        "n_taxa_validade":       "Taxa válidas",
        "n_taxa_ori_concluidas": "Taxa concluídas",
        "n_prop_inativas":       "Prop. inativas",
        "n_multi_projetos":      "Multi-projetos",
    }

    chart_df = df_sup.sort_values("nota_final", ascending=False).copy()
    z = [[safe_float(row[col]) for col in indicadores.keys()] for _, row in chart_df.iterrows()]
    tecnicos = chart_df["tecnico_responsavel"].tolist()
    labels   = list(indicadores.values())
    text_vals = [[f"{v:.2f}" for v in row] for row in z]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=labels,
        y=tecnicos,
        text=text_vals,
        texttemplate="%{text}",
        textfont=dict(size=10, color="white"),
        colorscale="RdYlGn",
        zmin=0, zmax=1,
        showscale=True,
        colorbar=dict(thickness=12, len=0.8, tickformat=".0%"),
        hovertemplate="%{y}<br>%{x}: %{z:.4f}<extra></extra>",
    ))
    fig.update_layout(
        height=max(220, len(tecnicos) * 50 + 80),
        margin=dict(l=0, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11, color="#111827"),
        xaxis=dict(side="top", tickangle=-30, tickfont=dict(color="#111827")),
        yaxis=dict(autorange="reversed", tickfont=dict(color="#111827")),
    )
    st.plotly_chart(fig, use_container_width=True)

# =====================================
# GRÁFICOS SECUNDÁRIOS
# =====================================
st.markdown('<p class="section-title" style="margin-top:8px">Distribuição</p>', unsafe_allow_html=True)
col_a, col_b = st.columns(2, gap="medium")

with col_a:
    comp = df_sup[["tecnico_responsavel","propriedades_ativas","propriedades_inativas"]].sort_values("propriedades_ativas", ascending=True)
    fig2 = go.Figure(data=[
        go.Bar(name="Ativas",   x=comp["propriedades_ativas"],   y=comp["tecnico_responsavel"],
               orientation="h", marker_color="#10b981",
               text=comp["propriedades_ativas"], textposition="inside", insidetextanchor="end", textfont=dict(size=10,color="white")),
        go.Bar(name="Inativas", x=comp["propriedades_inativas"], y=comp["tecnico_responsavel"],
               orientation="h", marker_color="#fca5a5",
               text=comp["propriedades_inativas"], textposition="inside", insidetextanchor="end", textfont=dict(size=10,color="#7f1d1d")),
    ])
    fig2.update_layout(barmode="group", height=max(260,len(comp)*36), title_text="Propriedades — Ativas vs Inativas", title_font_size=12,
        margin=dict(l=0,r=10,t=36,b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h",y=1.08,x=0,font_size=10), font=dict(size=11, color="#111827"),
        xaxis=dict(showgrid=True,gridcolor="#f0f0f0",zeroline=False), yaxis=dict(showgrid=False), bargap=0.25, bargroupgap=0.05)
    st.plotly_chart(fig2, use_container_width=True)

with col_b:
    ori = df_sup[["tecnico_responsavel","total_orientacoes_geral","total_orientacoes_concluidas","pct_ori_concluidas"]].sort_values("total_orientacoes_geral", ascending=True)
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
    fig3.update_layout(barmode="overlay", height=max(260,len(ori)*36), title_text="Orientações — Total vs Concluídas", title_font_size=12,
        margin=dict(l=0,r=10,t=36,b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h",y=1.08,x=0,font_size=10), font=dict(size=11, color="#111827"),
        xaxis=dict(showgrid=True,gridcolor="#f0f0f0",zeroline=False), yaxis=dict(showgrid=False), bargap=0.3)
    st.plotly_chart(fig3, use_container_width=True)

# =====================================
# DETALHES POR TÉCNICO
# =====================================
st.markdown('<p class="section-title" style="margin-top:8px">Detalhes por Técnico</p>', unsafe_allow_html=True)

def score_bar(val, cor="#2563eb"):
    pct = round(safe_float(val) * 100, 1)
    return f'<div class="score-bar-wrap"><div class="score-bar-fill" style="width:{pct}%;background:{cor}"></div></div>'

# Pré-calcula quem é líder em cada indicador no grupo
_ind_cols = {
    "n_prop_ativas":         "Prop. Ativas",
    "n_total_visitas":       "Total Visitas",
    "n_ori_geral":           "Orientações",
    "n_taxa_validade":       "Taxa Válidas",
    "n_taxa_ori_concluidas": "Taxa Concluídas",
    "n_prop_inativas":       "Prop. Inativas",
    "n_multi_projetos":      "Multi-Projetos",
}
_lideres = {}
for _col in _ind_cols:
    _max_val = df_sup[_col].max()
    _lideres[_col] = set(df_sup.loc[df_sup[_col] == _max_val, "tecnico_responsavel"].tolist())

for _, row in df_sup.iterrows():
    pos  = int(row["pos"])
    nota = safe_float(row["nota_final"])
    medalha = "🥇" if pos==1 else "🥈" if pos==2 else "🥉" if pos==3 else f"#{pos}"
    tec_nome = row["tecnico_responsavel"]

    # Monta badges de liderança
    lider_em   = [nome for col, nome in _ind_cols.items() if tec_nome in _lideres[col]]
    atras_em   = [nome for col, nome in _ind_cols.items() if tec_nome not in _lideres[col]]
    badges_lider = "".join([f'<span style="background:#d1fae5;color:#065f46;border-radius:12px;padding:2px 8px;font-size:0.72rem;margin:2px;display:inline-block">🏆 {n}</span>' for n in lider_em])
    badges_atras = "".join([f'<span style="background:#fee2e2;color:#7f1d1d;border-radius:12px;padding:2px 8px;font-size:0.72rem;margin:2px;display:inline-block">📉 {n}</span>' for n in atras_em])

    # Explicação da nota
    n_scores = [safe_float(row[c]) for c in _ind_cols]
    explicacao = " + ".join([f"{v:.2f}" for v in n_scores])
    qtd_lider = len(lider_em)
    penalidade_html = (
        "&nbsp;&nbsp;<span style=\"background:#fef3c7;color:#92400e;border-radius:8px;"
        "padding:1px 7px;font-size:0.7rem\">⚠️ penalidade 50% por multi-projeto</span>"
        if safe_float(row["qtd_multiplos_projetos"]) > 0 else ""
    )

    with st.expander(
        f"{medalha} {tec_nome}  ·  {nota*100:.1f}%  "
        f"·  Válidas {safe_float(row['pct_visitas_validas']):.0f}%  "
        f"·  Orient. {safe_float(row['pct_ori_concluidas']):.0f}%"
    ):
        # Painel de liderança — montado por concatenação para evitar escape do Streamlit
        painel_html = (
            '<div style="background:#f8fafc;border-radius:8px;padding:10px 14px;margin-bottom:12px;border:1px solid #e2e8f0">'
            '<div style="font-size:0.75rem;color:#64748b;margin-bottom:6px;font-weight:600">📊 COMO A NOTA '
            + f"{nota*100:.1f}% FOI CALCULADA</div>"
            + '<div style="font-size:0.78rem;color:#374151;margin-bottom:8px">'
            + f"Média dos 7 scores: ({explicacao}) ÷ 7 = <strong>{nota*100:.1f}%</strong>"
            + penalidade_html
            + '</div>'
            + f'<div style="font-size:0.75rem;color:#64748b;margin-bottom:4px;font-weight:600">✅ MELHOR DO GRUPO NESTES INDICADORES ({qtd_lider}/7) — score 1.00:</div>'
            + '<div style="margin-bottom:6px">'
            + (badges_lider if badges_lider else '<span style="color:#9ca3af;font-size:0.75rem">Nenhum</span>')
            + '</div>'
            + '<div style="font-size:0.75rem;color:#64748b;margin-bottom:4px;font-weight:600">⚠️ NÃO É O MELHOR DO GRUPO NESTES INDICADORES — score menor que 1.00:</div>'
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
                <div class="d-pts">score: {safe_float(row['n_prop_ativas']):.4f} &nbsp;·&nbsp; melhor do grupo: {df_sup['propriedades_ativas'].max():.0f}</div>
                {score_bar(row['n_prop_ativas'], '#10b981')}
            </div>
            <div class="detail-cell pos">
                <div class="d-label">📅 Total Visitas {"🏆" if tec_nome in _lideres["n_total_visitas"] else ""}</div>
                <div class="d-qty">{int(safe_float(row['total_visitas_presenciais']))}</div>
                <div class="d-pts">score: {safe_float(row['n_total_visitas']):.4f} &nbsp;·&nbsp; melhor do grupo: {df_sup['total_visitas_presenciais'].max():.0f}</div>
                {score_bar(row['n_total_visitas'], '#10b981')}
            </div>
            <div class="detail-cell pos">
                <div class="d-label">📋 Total Orientações {"🏆" if tec_nome in _lideres["n_ori_geral"] else ""}</div>
                <div class="d-qty">{int(safe_float(row['total_orientacoes_geral']))}</div>
                <div class="d-pts">score: {safe_float(row['n_ori_geral']):.4f} &nbsp;·&nbsp; melhor do grupo: {df_sup['total_orientacoes_geral'].max():.0f}</div>
                {score_bar(row['n_ori_geral'], '#10b981')}
            </div>
            <div class="detail-cell pos">
                <div class="d-label">✅ Taxa Visitas Válidas {"🏆" if tec_nome in _lideres["n_taxa_validade"] else ""}</div>
                <div class="d-qty">{safe_float(row['pct_visitas_validas']):.0f}%</div>
                <div class="d-pts">score: {safe_float(row['n_taxa_validade']):.4f} &nbsp;·&nbsp; melhor do grupo: {df_sup['pct_visitas_validas'].max():.0f}%</div>
                {score_bar(row['n_taxa_validade'], '#2563eb')}
            </div>
            <div class="detail-cell pos">
                <div class="d-label">✔️ Taxa Orient. Concluídas {"🏆" if tec_nome in _lideres["n_taxa_ori_concluidas"] else ""}</div>
                <div class="d-qty">{safe_float(row['pct_ori_concluidas']):.0f}%</div>
                <div class="d-pts">score: {safe_float(row['n_taxa_ori_concluidas']):.4f} &nbsp;·&nbsp; melhor do grupo: {df_sup['pct_ori_concluidas'].max():.0f}%</div>
                {score_bar(row['n_taxa_ori_concluidas'], '#2563eb')}
            </div>
            <div class="detail-cell neg">
                <div class="d-label">🚫 Prop. Inativas {"🏆" if tec_nome in _lideres["n_prop_inativas"] else ""}</div>
                <div class="d-qty">{int(safe_float(row['propriedades_inativas']))}</div>
                <div class="d-pts">score: {safe_float(row['n_prop_inativas']):.4f} &nbsp;·&nbsp; menor do grupo: {df_sup['propriedades_inativas'].min():.0f}</div>
                {score_bar(row['n_prop_inativas'], '#ef4444')}
            </div>
            <div class="detail-cell pen">
                <div class="d-label">⚠️ Multi-Projetos {"🏆" if tec_nome in _lideres["n_multi_projetos"] else ""}</div>
                <div class="d-qty">{int(safe_float(row['qtd_multiplos_projetos']))}</div>
                <div class="d-pts">score: {safe_float(row['n_multi_projetos']):.4f} &nbsp;·&nbsp; menor do grupo: {df_sup['qtd_multiplos_projetos'].min():.0f}</div>
                {score_bar(row['n_multi_projetos'], '#f59e0b')}
            </div>
            <div class="detail-cell tot">
                <div class="d-label">🏆 Nota Final — média dos 7</div>
                <div class="d-qty" style="color:#2563eb;font-size:1.2rem">{nota*100:.1f}%</div>
                <div class="d-pts">Posição #{pos} no grupo · líder em {qtd_lider} de 7 indicadores</div>
                {score_bar(nota, '#2563eb')}
            </div>
        </div>
        """, unsafe_allow_html=True)

# =====================================
# TABELA COMPARATIVA
# =====================================
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
]].copy()

comp_df.columns = [
    "Pos","Técnico","Nota Final",
    "Ativas","Score Ativas",
    "Inativas","Score Inativas",
    "Total Visitas","Score Visitas",
    "% Válidas","Score Taxa Válidas",
    "Total Orient.","Orient. Concluídas","Score Orient.",
    "% Concluídas","Score Taxa Concl.",
    "Multi-Proj.","Score Multi-Proj.",
]

comp_df["Pos"]        = comp_df["Pos"].astype(int)
comp_df["Nota Final"] = (pd.to_numeric(comp_df["Nota Final"], errors="coerce")*100).round(1)
for c in ["Ativas","Inativas","Total Visitas","Total Orient.","Orient. Concluídas","Multi-Proj."]:
    comp_df[c] = pd.to_numeric(comp_df[c], errors="coerce").fillna(0).astype(int)
for c in ["Score Ativas","Score Inativas","Score Visitas","Score Taxa Válidas",
          "Score Orient.","Score Taxa Concl.","Score Multi-Proj."]:
    comp_df[c] = pd.to_numeric(comp_df[c], errors="coerce").round(4)

st.dataframe(comp_df, use_container_width=True, hide_index=True,
    column_config={"Nota Final": st.column_config.NumberColumn(format="%.1f%%")})

csv = comp_df.to_csv(index=False)

import io
xlsx_buf = io.BytesIO()
comp_df.to_excel(xlsx_buf, index=False, engine="openpyxl")
xlsx_buf.seek(0)

col_csv, col_xlsx = st.columns([1, 1])
with col_csv:
    st.download_button("📥 Baixar CSV", data=csv, file_name=f"ranking_{sup}.csv", mime="text/csv", use_container_width=True)
with col_xlsx:
    st.download_button("📊 Baixar Excel", data=xlsx_buf, file_name=f"ranking_{sup}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)