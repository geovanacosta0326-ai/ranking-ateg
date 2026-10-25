# 🏆 Ranking de Performance ATeG

## Visão Geral

O Ranking de Performance ATeG é uma aplicação desenvolvida para monitorar, avaliar e classificar o desempenho dos técnicos de campo a partir dos dados registrados no sistema de acompanhamento de visitas.

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
public.vw_visitas
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

A nota final é a média simples de **7 critérios objetivos**, mais a **avaliação do supervisor** (8º critério) quando ela existe. Todos têm o mesmo peso.

| Indicador                      | Objetivo  |
| ------------------------------ | --------- |
| Propriedades Ativas            | Maximizar |
| Total de Visitas               | Maximizar |
| Total de Orientações           | Maximizar |
| Taxa de Visitas Válidas        | Maximizar |
| Taxa de Orientações Concluídas | Maximizar |
| Propriedades Inativas          | Minimizar |
| Repetição de Projeto           | Minimizar |
| Avaliação do supervisor        | Maximizar |

---

# Notas de 0 a 10 por indicador

Cada indicador vira uma nota de 0 a 10 por faixas fixas (e não mais comparando com os outros técnicos do grupo). Assim a nota de um técnico não muda por causa do desempenho dos colegas.

| Indicador | Regra |
| --- | --- |
| Propriedades Ativas | 30 ou mais = 10, 29 = 9, 28 = 8 ... 25 = 5. Abaixo de 25 cai 0,2 ponto por propriedade, até 0 |
| Total de Visitas (máx. 30 por mês) | Mesma regra de Propriedades Ativas |
| Propriedades Inativas | 10 menos o número de inativas visitadas no período (mínimo 0) |
| Taxa de Visitas Válidas | % ÷ 10 (100% = 10, 87% = 8,7) |
| Taxa de Orientações Concluídas | % ÷ 10 |
| Total de Orientações | 220 ou mais = 10, 200 = 9, 180 = 8, 170 = 7, 165 = 6. Abaixo disso proporcional até 164 = 5 |
| Repetição de Projeto | 10 se não houver propriedade em mais de um projeto, 5 se houver |
| Avaliação do supervisor | A própria nota (0 a 10) lançada no Sistema de Avaliação |

Observações:
- Propriedades inativas contam só as visitadas **no período** escolhido.
- O limite é de 30 visitas por técnico por mês.

---

# Cálculo da Nota Final

```text
Nota Final = soma das notas dos critérios ÷ quantidade de critérios
```

- Com avaliação do supervisor: 8 critérios (÷ 8).
- Sem avaliação lançada: 7 critérios objetivos (÷ 7). A avaliação **não** entra como zero. O técnico aparece com o aviso "⚠️ sem avaliação" até o supervisor lançar.

Exemplo (sem avaliação): 10 + 10 + 10 + 10 + 8 + 0 + 10 = 58, e 58 ÷ 7 = 8,29.

---

# Quem aparece no ranking

- Só técnicos com **visitas no mês**. Técnico avaliado, mas sem visitas, aparece na aba "Avaliados sem visitas".
- Técnicos que saíram (vínculo desativado) não aparecem.
- Quem tem menos de 15 visitas no mês recebe o selo "🔸 poucas visitas".

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