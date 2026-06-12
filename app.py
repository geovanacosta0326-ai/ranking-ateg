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
@st.cache_data(ttl=600)
def buscar_dados():
    url = URL.create(
        "postgresql+psycopg2",
        username=os.getenv("REMOTE_DB_USER", "postgres"),
        password=os.getenv("REMOTE_DB_PASS"),
        host=os.getenv("REMOTE_DB_HOST", "177.22.38.27"),
        port=os.getenv("REMOTE_DB_PORT", "6432"),
        database=os.getenv("REMOTE_DB_NAME", "painel_ateg"),
    )
    query = """
    -- Camada 1: calcula MIN/MAX por supervisor
    WITH base AS (
        SELECT
            tecnico_responsavel,
            ultimo_supervisor,
            propriedades_ativas,
            propriedades_inativas,
            total_de_visitas,
            total_visitas_validas,
            total_orientacoes_geral,
            total_orientacoes_concluidas,
            qtd_multiplos_projetos,
            pct_visitas_validas,
            pct_ori_concluidas,
            MIN(propriedades_ativas)      OVER w AS min_pa,
            MAX(propriedades_ativas)      OVER w AS max_pa,
            MIN(total_de_visitas)         OVER w AS min_tv,
            MAX(total_de_visitas)         OVER w AS max_tv,
            MIN(total_orientacoes_geral)  OVER w AS min_og,
            MAX(total_orientacoes_geral)  OVER w AS max_og,
            MIN(pct_visitas_validas)      OVER w AS min_vv,
            MAX(pct_visitas_validas)      OVER w AS max_vv,
            MIN(pct_ori_concluidas)       OVER w AS min_oc,
            MAX(pct_ori_concluidas)       OVER w AS max_oc,
            MIN(propriedades_inativas)    OVER w AS min_pi,
            MAX(propriedades_inativas)    OVER w AS max_pi,
            MIN(qtd_multiplos_projetos)   OVER w AS min_mp,
            MAX(qtd_multiplos_projetos)   OVER w AS max_mp
        FROM ranking_tecnicos
        WINDOW w AS (PARTITION BY ultimo_supervisor)
    ),
    -- Camada 2: aplica CASE usando os MIN/MAX já calculados
    scores AS (
        SELECT
            tecnico_responsavel,
            ultimo_supervisor,
            propriedades_ativas,
            propriedades_inativas,
            total_de_visitas,
            total_visitas_validas,
            total_orientacoes_geral,
            total_orientacoes_concluidas,
            qtd_multiplos_projetos,
            pct_visitas_validas,
            pct_ori_concluidas,

            ROUND(CAST(CASE WHEN max_pa = min_pa THEN 1.0
                  ELSE (propriedades_ativas - min_pa)::NUMERIC / (max_pa - min_pa) END AS NUMERIC), 4) AS n_prop_ativas,

            ROUND(CAST(CASE WHEN max_tv = min_tv THEN 1.0
                  ELSE (total_de_visitas - min_tv)::NUMERIC / (max_tv - min_tv) END AS NUMERIC), 4) AS n_total_visitas,

            ROUND(CAST(CASE WHEN max_og = min_og THEN 1.0
                  ELSE (total_orientacoes_geral - min_og)::NUMERIC / (max_og - min_og) END AS NUMERIC), 4) AS n_ori_geral,

            ROUND(CAST(CASE WHEN max_vv = min_vv THEN 1.0
                  ELSE (pct_visitas_validas - min_vv)::NUMERIC / (max_vv - min_vv) END AS NUMERIC), 4) AS n_taxa_validade,

            ROUND(CAST(CASE WHEN max_oc = min_oc THEN 1.0
                  ELSE (pct_ori_concluidas - min_oc)::NUMERIC / (max_oc - min_oc) END AS NUMERIC), 4) AS n_taxa_ori_concluidas,

            ROUND(CAST(CASE WHEN max_pi = min_pi THEN 1.0
                  ELSE 1.0 - (propriedades_inativas - min_pi)::NUMERIC / (max_pi - min_pi) END AS NUMERIC), 4) AS n_prop_inativas,

            ROUND(CAST(CASE WHEN max_mp = 0 THEN 1.0
                  ELSE 1.0 - (qtd_multiplos_projetos - min_mp)::NUMERIC / (max_mp - min_mp) END AS NUMERIC), 4) AS n_multi_projetos
        FROM base
    )
    -- Camada 3: nota final e ranking
    SELECT
        tecnico_responsavel,
        ultimo_supervisor,
        propriedades_ativas,
        propriedades_inativas,
        total_de_visitas,
        total_visitas_validas,
        total_orientacoes_geral,
        total_orientacoes_concluidas,
        qtd_multiplos_projetos,
        pct_visitas_validas,
        pct_ori_concluidas,
        n_prop_ativas,
        n_total_visitas,
        n_ori_geral,
        n_taxa_validade,
        n_taxa_ori_concluidas,
        n_prop_inativas,
        n_multi_projetos,
        ROUND(CAST((n_prop_ativas + n_total_visitas + n_ori_geral + n_taxa_validade
             + n_taxa_ori_concluidas + n_prop_inativas + n_multi_projetos) / 7.0 AS NUMERIC), 4) AS nota_final,
        DENSE_RANK() OVER (
            PARTITION BY ultimo_supervisor
            ORDER BY (n_prop_ativas + n_total_visitas + n_ori_geral + n_taxa_validade
                    + n_taxa_ori_concluidas + n_prop_inativas + n_multi_projetos) DESC
        ) AS pos
    FROM scores
    ORDER BY ultimo_supervisor, pos
    """
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            return pd.read_sql(query, conn)
    except Exception as e:
        st.error(f"❌ Erro ao buscar dados: {e}")
        return pd.DataFrame()

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
st.markdown("""
<div class="page-header">
    <div>
        <h1>🏆 Ranking de Performance ATeG</h1>
        <p>Jan–Mai 2026 · 7 indicadores com peso igual (14,3% cada) · comparação dentro do grupo do supervisor</p>
    </div>
    <span class="badge">Nota 0 a 1</span>
</div>
""", unsafe_allow_html=True)

# =====================================
# DADOS
# =====================================
df = buscar_dados()
if df is None or df.empty:
    st.stop()

cols_num = [
    "n_prop_ativas","n_total_visitas","n_ori_geral",
    "n_taxa_validade","n_taxa_ori_concluidas","n_prop_inativas","n_multi_projetos",
    "nota_final",
]
for c in cols_num:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")

# =====================================
# FILTRO
# =====================================
supervisores = sorted(df["ultimo_supervisor"].dropna().astype(str).unique())
col_sel, col_btn = st.columns([5, 1])
with col_sel:
    sup = st.selectbox("👤 Supervisor", supervisores)
with col_btn:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    if st.button("🔄 Atualizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

df_sup = df[df["ultimo_supervisor"] == sup].sort_values("pos")
if df_sup.empty:
    st.warning("Nenhum técnico encontrado.")
    st.stop()

# =====================================
# MÉTRICAS
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

for _, row in df_sup.iterrows():
    pos  = int(row["pos"])
    nota = safe_float(row["nota_final"])
    medalha = "🥇" if pos==1 else "🥈" if pos==2 else "🥉" if pos==3 else f"#{pos}"

    with st.expander(
        f"{medalha} {row['tecnico_responsavel']}  ·  {nota*100:.1f}%  "
        f"·  Válidas {safe_float(row['pct_visitas_validas']):.0f}%  "
        f"·  Orient. {safe_float(row['pct_ori_concluidas']):.0f}%"
    ):
        st.markdown(f"""
        <div class="detail-grid">
            <div class="detail-cell pos">
                <div class="d-label">🚜 Prop. Ativas</div>
                <div class="d-qty">{int(safe_float(row['propriedades_ativas']))}</div>
                <div class="d-pts">score: {safe_float(row['n_prop_ativas']):.4f}</div>
                {score_bar(row['n_prop_ativas'], '#10b981')}
            </div>
            <div class="detail-cell pos">
                <div class="d-label">📅 Total Visitas</div>
                <div class="d-qty">{int(safe_float(row['total_de_visitas']))}</div>
                <div class="d-pts">score: {safe_float(row['n_total_visitas']):.4f}</div>
                {score_bar(row['n_total_visitas'], '#10b981')}
            </div>
            <div class="detail-cell pos">
                <div class="d-label">📋 Total Orientações</div>
                <div class="d-qty">{int(safe_float(row['total_orientacoes_geral']))}</div>
                <div class="d-pts">score: {safe_float(row['n_ori_geral']):.4f}</div>
                {score_bar(row['n_ori_geral'], '#10b981')}
            </div>
            <div class="detail-cell pos">
                <div class="d-label">✅ Taxa Visitas Válidas</div>
                <div class="d-qty">{safe_float(row['pct_visitas_validas']):.0f}%</div>
                <div class="d-pts">score: {safe_float(row['n_taxa_validade']):.4f}</div>
                {score_bar(row['n_taxa_validade'], '#2563eb')}
            </div>
            <div class="detail-cell pos">
                <div class="d-label">✔️ Taxa Orient. Concluídas</div>
                <div class="d-qty">{safe_float(row['pct_ori_concluidas']):.0f}%</div>
                <div class="d-pts">score: {safe_float(row['n_taxa_ori_concluidas']):.4f}</div>
                {score_bar(row['n_taxa_ori_concluidas'], '#2563eb')}
            </div>
            <div class="detail-cell neg">
                <div class="d-label">🚫 Prop. Inativas</div>
                <div class="d-qty">{int(safe_float(row['propriedades_inativas']))}</div>
                <div class="d-pts">score: {safe_float(row['n_prop_inativas']):.4f}</div>
                {score_bar(row['n_prop_inativas'], '#ef4444')}
            </div>
            <div class="detail-cell pen">
                <div class="d-label">⚠️ Multi-Projetos</div>
                <div class="d-qty">{int(safe_float(row['qtd_multiplos_projetos']))}</div>
                <div class="d-pts">score: {safe_float(row['n_multi_projetos']):.4f}</div>
                {score_bar(row['n_multi_projetos'], '#f59e0b')}
            </div>
            <div class="detail-cell tot">
                <div class="d-label">🏆 Nota Final — média dos 7</div>
                <div class="d-qty" style="color:#2563eb;font-size:1.2rem">{nota*100:.1f}%</div>
                <div class="d-pts">Posição #{pos} no grupo</div>
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
    "total_de_visitas","n_total_visitas",
    "pct_visitas_validas","n_taxa_validade",
    "total_orientacoes_geral","n_ori_geral",
    "pct_ori_concluidas","n_taxa_ori_concluidas",
    "qtd_multiplos_projetos","n_multi_projetos",
]].copy()

comp_df.columns = [
    "Pos","Técnico","Nota Final",
    "Ativas","Score Ativas",
    "Inativas","Score Inativas",
    "Total Visitas","Score Visitas",
    "% Válidas","Score Taxa Válidas",
    "Total Orient.","Score Orient.",
    "% Concluídas","Score Taxa Concl.",
    "Multi-Proj.","Score Multi-Proj.",
]

comp_df["Pos"]        = comp_df["Pos"].astype(int)
comp_df["Nota Final"] = (pd.to_numeric(comp_df["Nota Final"], errors="coerce")*100).round(1)
for c in ["Ativas","Inativas","Total Visitas","Total Orient.","Multi-Proj."]:
    comp_df[c] = pd.to_numeric(comp_df[c], errors="coerce").fillna(0).astype(int)
for c in ["Score Ativas","Score Inativas","Score Visitas","Score Taxa Válidas",
          "Score Orient.","Score Taxa Concl.","Score Multi-Proj."]:
    comp_df[c] = pd.to_numeric(comp_df[c], errors="coerce").round(4)

st.dataframe(comp_df, use_container_width=True, hide_index=True,
    column_config={"Nota Final": st.column_config.NumberColumn(format="%.1f%%")})

csv = comp_df.to_csv(index=False)
st.download_button("📥 Baixar CSV", data=csv, file_name=f"ranking_{sup}.csv", mime="text/csv")