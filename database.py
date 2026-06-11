import streamlit as st
import pandas as pd
import os
from sqlalchemy import create_engine
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

@st.cache_data(ttl=600)
def buscar_dados(query):
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