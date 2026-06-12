# 🏆 Ranking de Performance ATeG

## Visão Geral

OO Ranking de Performance ATeG é uma aplicação desenvolvida para monitorar, avaliar e classificar o desempenho dos técnicos de campo a partir dos dados registrados no sistema de acompanhamento de visitas.

A solução foi construída para fornecer indicadores objetivos de produtividade, qualidade dos atendimentos e consistência cadastral, permitindo comparações justas entre profissionais que atuam sob a mesma supervisão ou dentro de um mesmo projeto.

Além do ranking de desempenho, o sistema disponibiliza mecanismos de auditoria para identificação de propriedades vinculadas simultaneamente a múltiplos projetos, contribuindo para a melhoria da qualidade dos dados institucionais.

---

# Objetivo

O sistema possui os seguintes objetivos:

Avaliar o desempenho dos técnicos ATeG.
Apoiar gestores na tomada de decisão.
Identificar oportunidades de melhoria operacional.
Incentivar boas práticas de atendimento.
Detectar inconsistências cadastrais.
Monitorar conflitos de vinculação entre projetos.
Disponibilizar análises comparativas entre equipes e projetos.

---

# Arquitetura da Solução

A aplicação foi desenvolvida utilizando arquitetura baseada em banco de dados relacional, processamento analítico em Python e visualização web interativa.

PostgreSQL
      │
      ▼
Consultas SQL Analíticas
(Window Functions + CTEs)
      │
      ▼
Python + Pandas
(Processamento)
      │
      ▼
Streamlit
(Dashboard Web)
      │
      ▼
Usuário Final

# Fonte dos Dados

Os dados são obtidos da tabela:

```sql
public.acompanhamento_mensal_visitas
```
Esta tabela concentra os registros operacionais das visitas realizadas pelos técnicos, incluindo:

Propriedades atendidas;
Situação do vínculo;
Quantidade de visitas;
Orientações registradas;
Orientações concluídas;
Supervisor responsável;
Projeto vinculado;
Informações do produtor.

---

# Indicadores Utilizados

O ranking é composto por sete indicadores.


| Indicador                      | Objetivo  |
| ------------------------------ | --------- |
| Propriedades Ativas            | Maximizar |
| Total de Visitas               | Maximizar |
| Total de Orientações           | Maximizar |
| Taxa de Visitas Válidas        | Maximizar |
| Taxa de Orientações Concluídas | Maximizar |
| Propriedades Inativas          | Minimizar |
| Propriedades Multi-Projeto     | Minimizar |

Todos os indicadores possuem o mesmo peso na composição da nota final.

---

# Metodologia de Cálculo

## 1. Propriedades Ativas

Quantidade de propriedades distintas com status:

```sql
vinculo_status = 'ATIVA'
```

Fórmula:

```sql
COUNT(DISTINCT id_propriedade)
```

---

## 2. Propriedades Inativas

Quantidade de propriedades distintas com status:

```sql
vinculo_status = 'INATIVA'
```

Fórmula:

```sql
COUNT(DISTINCT id_propriedade)
```

---

## 3. Total de Visitas

Representa a quantidade total de visitas realizadas pelo técnico no período analisado.

Fórmula:

```sql
COUNT(*)
```

---

## 4. Taxa de Visitas Válidas

Mede a qualidade das visitas realizadas.

Fórmula:

```text
Taxa de Visitas Válidas =
Total de Visitas Válidas / Total de Visitas
```

Exemplo:

```text
90 visitas válidas
100 visitas totais

Taxa = 90%
```

---

## 5. Total de Orientações

Quantidade total de orientações registradas.

Fórmula:

```sql
SUM(ori_total_geral)
```

---

## 6. Taxa de Orientações Concluídas

Avalia a efetividade das orientações realizadas.

Fórmula:

```text
Taxa de Conclusão =
Orientações Concluídas / Total de Orientações
```

Exemplo:

```text
80 orientações concluídas
100 orientações registradas

Taxa = 80%
```

---

## 7. Propriedades Multi-Projeto

Identifica propriedades vinculadas simultaneamente a mais de um projeto.

Exemplo:

| ID Propriedade | Projeto       |
| -------------- | ------------- |
| 1001           | Bovinocultura |
| 1001           | Apicultura    |

Nesse caso a propriedade é considerada um conflito de projeto.

O indicador contabiliza a quantidade de propriedades em situação de múltiplos projetos.

---

# Normalização dos Indicadores

Como os indicadores possuem escalas diferentes, todos são transformados para uma escala comum entre 0 e 1.

A normalização é realizada dentro de cada grupo de supervisor.

---

## Indicadores Positivos

Quanto maior o valor, melhor o desempenho.

Aplicado em:

* Propriedades Ativas
* Total de Visitas
* Total de Orientações
* Taxa de Visitas Válidas
* Taxa de Orientações Concluídas

Fórmula:

```text
(valor - mínimo) / (máximo - mínimo)
```

Resultado:

| Situação              | Score |
| --------------------- | ----- |
| Melhor valor do grupo | 1,00  |
| Pior valor do grupo   | 0,00  |

---

## Indicadores Negativos

Quanto menor o valor, melhor o desempenho.

Aplicado em:

* Propriedades Inativas
* Multi-Projetos

Fórmula:

```text
1 - ((valor - mínimo) / (máximo - mínimo))
```

Resultado:

| Situação             | Score |
| -------------------- | ----- |
| Menor valor do grupo | 1,00  |
| Maior valor do grupo | 0,00  |

---

# Indicadores Normalizados

Após a normalização, são gerados os seguintes campos:

| Campo                 | Descrição                           |
| --------------------- | ----------------------------------- |
| n_prop_ativas         | Score de propriedades ativas        |
| n_total_visitas       | Score de visitas                    |
| n_ori_geral           | Score de orientações                |
| n_taxa_validade       | Score de visitas válidas            |
| n_taxa_ori_concluidas | Score de orientações concluídas     |
| n_prop_inativas       | Score de propriedades inativas      |
| n_multi_projetos      | Score de propriedades multi-projeto |

Todos os scores variam entre:

```text
0,00 → pior desempenho
1,00 → melhor desempenho
```

---

# Cálculo da Nota Final

Todos os sete indicadores possuem exatamente o mesmo peso.

Peso individual:

```text
1 ÷ 7 = 14,2857%
```

A nota final é calculada através da média simples dos indicadores normalizados.

Fórmula:

```text
Nota Final =
(
n_prop_ativas +
n_total_visitas +
n_ori_geral +
n_taxa_validade +
n_taxa_ori_concluidas +
n_prop_inativas +
n_multi_projetos
) / 7
```

A nota final também varia entre:

```text
0,00 e 1,00
```

ou

```text
0% e 100%
```

---

# Penalização por Conflito de Projetos

Caso o técnico possua pelo menos uma propriedade vinculada a mais de um projeto:

```text
qtd_multiplos_projetos > 0
```

é aplicada uma penalização de 50% sobre a nota final.

Fórmula:

```text
Nota Penalizada =
Nota Final × 0,5
```

Exemplo:

```text
Nota Original = 0,84

Nota Penalizada = 0,42
```

Essa regra foi criada para desestimular inconsistências cadastrais e sobreposição de projetos.

---

# Formação do Ranking

Após o cálculo da nota final:

1. Os técnicos são agrupados pelo supervisor.
2. As notas são ordenadas da maior para a menor.
3. É aplicada a função:

```sql
DENSE_RANK()
```

Exemplo:

| Técnico | Nota | Posição |
| ------- | ---- | ------- |
| João    | 0,95 | 1       |
| Maria   | 0,90 | 2       |
| Pedro   | 0,90 | 2       |
| Carlos  | 0,85 | 3       |

Empates recebem a mesma posição.

---

# Funcionalidades do Sistema

## Ranking por Supervisor

Permite visualizar o desempenho dos técnicos dentro da equipe de um supervisor.

---

## Ranking por Projeto

Permite comparar técnicos vinculados ao mesmo projeto.

---

## Consulta Individual

Exibe todos os indicadores utilizados na composição da nota do técnico.

---

## Heatmap de Indicadores

Apresenta visualmente os scores normalizados dos técnicos.

---

## Gestão de Propriedades Multi-Projeto

Tela específica para identificar propriedades vinculadas simultaneamente a mais de um projeto.

Informações exibidas:

* Supervisor
* Técnico
* ID da propriedade
* Nome do imóvel
* CPF do produtor
* Projetos vinculados

---

## Exportação de ddaos

O sistema permite exportar os resultados em formato CSV para análises externas.

---

# Interpretação da Nota

| Faixa         | Classificação      |
| ------------- | ------------------ |
| 90% a 100%    | Excelente          |
| 80% a 89%     | Muito Bom          |
| 70% a 79%     | Bom                |
| 60% a 69%     | Regular            |
| Abaixo de 60% | Necessita Melhoria |

---

# Tecnologias Utilizadas

| Tecnologia    | Finalidade                                 |
| ------------- | ------------------------------------------ |
| Python        | Processamento de dados e regras de negócio |
| Streamlit     | Interface web                              |
| PostgreSQL    | Banco de dados                             |
| Pandas        | Manipulação de dados                       |
| SQLAlchemy    | Conexão com PostgreSQL                     |
| Plotly        | Gráficos interativos                       |
| python-dotenv | Gerenciamento de credenciais               |
| Git           | Versionamento                              |
| GitHub        | Repositório do projeto                     |
| VS Code       | Ambiente de desenvolvimento                |

---

# Técnicas Aplicadas

Business Intelligence (BI)
Data Analytics
Data Visualization
Ranking e Scoring
Normalização Min-Max
Window Functions SQL
Common Table Expressions (CTEs)
Análise Comparativa de Performance
Auditoria de Consistência de Dados
Tratamento de Dados
Indicadores de Desempenho (KPIs)

---

# Framework Web

Streamlit

Utilizado para criação da interface web interativa.

---

# Principais funcionalidades implementadas:

Filtros dinâmicos.
Rankings interativos.
Exportação para CSV.
Heatmaps.
Gráficos de desempenho.
Painel de gestão de conflitos de projetos.
Banco de Dados
PostgreSQL

---

# Responsável pelo armazenamento e processamento dos dados utilizados pelo ranking.

Bibliotecas Python
Pandas

Utilizado para:

Manipulação de dados.
Conversão de tipos.
Tratamento de valores nulos.
Exportação de relatórios.
SQLAlchemy

Responsável pela conexão entre a aplicação Python e o banco PostgreSQL.

Permite:

Gerenciamento de conexões.
Execução de consultas SQL.
Controle de transações.
Plotly

Biblioteca utilizada para geração dos gráficos interativos.

---

# Recursos utilizados:

Heatmaps.
Gráficos de barras.
Indicadores visuais.
Comparativos de desempenho.
python-dotenv

Utilizada para gerenciamento seguro das credenciais de acesso ao banco de dados através de variáveis de ambiente.

---

# Ambiente de Desenvolvimento
Ferramentas Utilizadas
Visual Studio Code (VS Code)
Python 3.x
PostgreSQL
Git
GitHub
Principais Técnicas Aplicadas

---

# Segurança

As credenciais de acesso ao banco são armazenadas em arquivo .env, evitando exposição de usuários e senhas diretamente no código-fonte.

A conexão com o banco é realizada utilizando parâmetros configuráveis por ambiente, facilitando implantação em servidores de homologação e produção.