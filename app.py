import streamlit as st
import pandas as pd
import numpy as np
import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

# =====================================
# FUNÇÃO DE CONEXÃO COM BANCO (SEGURA)
# =====================================
@st.cache_data(ttl=600)
def buscar_dados(query):
    # Credenciais do .env
    DB_USER = os.getenv("DB_USER", "postgres")
    DB_PASS = os.getenv("DB_PASS")
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "api_sisateg")
    
    if not DB_PASS:
        st.error("❌ Erro: Variável DB_PASS não configurada!")
        return pd.DataFrame()
    
    url = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            return pd.read_sql(query, conn)
    except Exception as e:
        st.error(f"❌ Erro ao buscar dados: {e}")
        return pd.DataFrame()


# =====================================
# CONFIGURAÇÃO DA PÁGINA
# =====================================
st.set_page_config(page_title="Ranking de Performance ATeG", page_icon="🏆", layout="wide")

# =====================================
# CSS E ESTILOS
# =====================================
st.markdown("""
<style>
.header-box { background: linear-gradient(135deg, #0f172a, #2563eb); color: white; padding: 25px; border-radius: 15px; text-align: center; margin-bottom: 25px; }
.ranking-card { background: white; padding: 15px; margin-bottom: 12px; border-radius: 12px; box-shadow: 0px 2px 8px rgba(0,0,0,0.08); border-left: 6px solid #2563eb; }
.top1 { border-left: 8px solid gold; }
.top2 { border-left: 8px solid silver; }
.top3 { border-left: 8px solid #cd7f32; }
.nome-tecnico { font-size: 18px; font-weight: 600; }
.pontuacao { color: #2563eb; font-size: 22px; font-weight: bold; }
.barra-fundo { width: 100%; background: #e5e7eb; border-radius: 10px; height: 12px; margin-top: 10px; }
.info-texto { margin-top: 10px; color: #555; font-size: 13px; }
.metrics-table { font-size: 12px; }
</style>
""", unsafe_allow_html=True)

# Cabeçalho
st.markdown('<div class="header-box"><h1>🏆 Ranking de Performance ATeG</h1><p>Acompanhamento mensal baseado em produtividade e qualidade técnica</p></div>', unsafe_allow_html=True)

# =====================================
# CONSULTA SQL
# =====================================
query_sql = """
WITH PropriedadesPorTecnico AS (
    SELECT tecnico_responsavel, supervisor_atual, id_propriedade,
           COUNT(DISTINCT id_projeto) as qtd_proj_prop,
           MAX(CASE WHEN vinculo_status = 'ATIVA' THEN 1 ELSE 0 END) as is_ativa,
           MAX(CASE WHEN vinculo_status = 'INATIVA' THEN 1 ELSE 0 END) as is_inativa
    FROM public.acompanhamento_mensal_visitas
    WHERE dt_visita_v BETWEEN '2026-01-01' AND '2026-05-31'
    GROUP BY tecnico_responsavel, supervisor_atual, id_propriedade
),
Resumo AS (
    SELECT p.tecnico_responsavel, p.supervisor_atual,
           SUM(p.is_ativa) AS prop_ativas,
           SUM(p.is_inativa) AS prop_inativas,
           COUNT(*) AS total_visitas,
           SUM(CASE WHEN base.visita_valida = 'Valida' THEN 1 ELSE 0 END) AS visitas_validas,
           SUM(COALESCE(base.ori_total_geral, 0)) AS ori_geral,
           SUM(COALESCE(base.ori_concluida, 0)) AS ori_concluidas,
           SUM(CASE WHEN p.qtd_proj_prop > 1 THEN 1 ELSE 0 END) AS qtd_prop_multiplos_projetos
    FROM (
        SELECT tecnico_responsavel, id_propriedade, ori_total_geral, ori_concluida,
               'Valida' as visita_valida
        FROM public.acompanhamento_mensal_visitas 
        WHERE dt_visita_v BETWEEN '2026-01-01' AND '2026-05-31'
    ) base
    JOIN PropriedadesPorTecnico p USING(tecnico_responsavel, id_propriedade)
    GROUP BY p.tecnico_responsavel, p.supervisor_atual
)
SELECT *, 
    ((prop_ativas * 1.5) + (prop_inativas * -1.5) + (total_visitas * 2.0) + 
     (visitas_validas * 2.5) + (ori_geral * 3.0) + (ori_concluidas * 3.5) + 
     (qtd_prop_multiplos_projetos * -5.0)) AS nota_final,
    DENSE_RANK() OVER (PARTITION BY supervisor_atual ORDER BY 
     ((prop_ativas * 1.5) + (prop_inativas * -1.5) + (total_visitas * 2.0) + 
      (visitas_validas * 2.5) + (ori_geral * 3.0) + (ori_concluidas * 3.5) + 
      (qtd_prop_multiplos_projetos * -5.0)) DESC) as pos
FROM Resumo;
"""

# =====================================
# BUSCA DE DADOS
# =====================================
try:
    df = buscar_dados(query_sql)
    if df is None or df.empty:
        st.error("❌ Nenhum dado encontrado no período consultado.")
        st.stop()
except Exception as e:
    st.error(f"❌ Erro ao buscar dados: {str(e)}")
    st.stop()

# =====================================
# FILTRO E EXIBIÇÃO
# =====================================
supervisores = sorted([str(s) for s in df["supervisor_atual"].dropna().unique() if s is not None])

if not supervisores:
    st.error("❌ Nenhum supervisor encontrado nos dados.")
    st.stop()

sup = st.selectbox("Selecione o Supervisor", supervisores)

df_sup = df[df["supervisor_atual"] == sup].sort_values("pos")

st.subheader(f"Equipe: {sup}")

if df_sup.empty:
    st.warning("⚠️ Nenhum técnico encontrado para este supervisor.")
else:
    # Calcular max_score com segurança
    scores_validos = df_sup["nota_final"].dropna()
    max_score = scores_validos.max() if len(scores_validos) > 0 and scores_validos.max() > 0 else 1

    for _, row in df_sup.iterrows():
        pos = int(row["pos"])
        nota_final = row["nota_final"]
        
        # Validar nota_final
        if pd.isna(nota_final):
            continue
        
        medalha = "🥇" if pos == 1 else "🥈" if pos == 2 else "🥉" if pos == 3 else ""
        classe = "ranking-card" + (" top1" if pos == 1 else " top2" if pos == 2 else " top3" if pos == 3 else "")
        pct = min((nota_final / max_score) * 100, 100)
        
        st.markdown(f"""
        <div class="{classe}">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div><span style="font-size:24px;">{medalha}</span> <span class="nome-tecnico">#{pos} - {row['tecnico_responsavel']}</span></div>
                <div class="pontuacao">{nota_final:.1f} pts</div>
            </div>
            <div class="barra-fundo"><div style="width:{pct:.1f}%; background:#2563eb; height:12px; border-radius:10px;"></div></div>
        </div>
        """, unsafe_allow_html=True)
        
        # =====================================
        # TABELA DETALHADA DE MÉTRICAS
        # =====================================
        with st.expander(f"📊 Ver detalhes de {row['tecnico_responsavel']}"):
            
            # Calcular contribuição de cada métrica
            prop_ativas_pts = row['prop_ativas'] * 1.5
            prop_inativas_pts = row['prop_inativas'] * -1.5
            total_visitas_pts = row['total_visitas'] * 2.0
            visitas_validas_pts = row['visitas_validas'] * 2.5
            ori_geral_pts = row['ori_geral'] * 3.0
            ori_concluidas_pts = row['ori_concluidas'] * 3.5
            qtd_multiplos_pts = row['qtd_prop_multiplos_projetos'] * -5.0
            
            # Criar DataFrame com detalhes
            metricas_df = pd.DataFrame({
                'Métrica': [
                    '🚜 Propriedades Ativas',
                    '🚫 Propriedades Inativas',
                    '📅 Total de Visitas',
                    '✅ Visitas Válidas',
                    '📋 Total de Orientações',
                    '✔️ Orientações Concluídas',
                    '⚠️ Propriedades Multi-Projetos'
                ],
                'Quantidade': [
                    int(row['prop_ativas']),
                    int(row['prop_inativas']),
                    int(row['total_visitas']),
                    int(row['visitas_validas']),
                    int(row['ori_geral']),
                    int(row['ori_concluidas']),
                    int(row['qtd_prop_multiplos_projetos'])
                ],
                'Multiplicador': [1.5, -1.5, 2.0, 2.5, 3.0, 3.5, -5.0],
                'Pontos': [
                    f"{prop_ativas_pts:.1f}",
                    f"{prop_inativas_pts:.1f}",
                    f"{total_visitas_pts:.1f}",
                    f"{visitas_validas_pts:.1f}",
                    f"{ori_geral_pts:.1f}",
                    f"{ori_concluidas_pts:.1f}",
                    f"{qtd_multiplos_pts:.1f}"
                ]
            })
            
            st.dataframe(metricas_df, use_container_width=True, hide_index=True)
            
            # Resumo da pontuação
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📊 Pontuação Total", f"{nota_final:.1f} pts")
            with col2:
                st.metric("🎯 Posição", f"#{pos}")
            with col3:
                taxa_conclusao = (row['ori_concluidas'] / row['ori_geral'] * 100) if row['ori_geral'] > 0 else 0
                st.metric("📈 Taxa de Conclusão", f"{taxa_conclusao:.1f}%")
            with col4:
                taxa_validade = (row['visitas_validas'] / row['total_visitas'] * 100) if row['total_visitas'] > 0 else 0
                st.metric("✅ Taxa de Validação", f"{taxa_validade:.1f}%")
    
    # =====================================
    # TABELA COMPARATIVA DE TODA EQUIPE
    # =====================================
    st.divider()
    st.subheader("📋 Comparativo da Equipe")
    
    # Preparar dados para tabela comparativa
    comparativo_df = df_sup.copy()
    comparativo_df['Posição'] = comparativo_df['pos'].astype(int)
    comparativo_df['Técnico'] = comparativo_df['tecnico_responsavel']
    comparativo_df['Pontuação'] = comparativo_df['nota_final'].round(1)
    comparativo_df['Prop. Ativas'] = comparativo_df['prop_ativas'].astype(int)
    comparativo_df['Prop. Inativas'] = comparativo_df['prop_inativas'].astype(int)
    comparativo_df['Total Visitas'] = comparativo_df['total_visitas'].astype(int)
    comparativo_df['Visitas Válidas'] = comparativo_df['visitas_validas'].astype(int)
    comparativo_df['Orient. Total'] = comparativo_df['ori_geral'].astype(int)
    comparativo_df['Orient. Concluídas'] = comparativo_df['ori_concluidas'].astype(int)
    comparativo_df['Prop. Multi-Proj'] = comparativo_df['qtd_prop_multiplos_projetos'].astype(int)
    
    colunas_exibir = ['Posição', 'Técnico', 'Pontuação', 'Prop. Ativas', 'Prop. Inativas', 
                      'Total Visitas', 'Visitas Válidas', 'Orient. Total', 'Orient. Concluídas', 'Prop. Multi-Proj']
    
    st.dataframe(comparativo_df[colunas_exibir], use_container_width=True, hide_index=True)