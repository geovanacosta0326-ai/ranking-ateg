# 🏆 Ranking de Performance ATeG

## Visão Geral

O sistema de Ranking de Performance ATeG foi desenvolvido para avaliar e classificar os técnicos com base em indicadores operacionais e de qualidade dos atendimentos realizados.

A metodologia busca garantir uma comparação justa entre profissionais que atuam sob o mesmo supervisor ou projeto, utilizando indicadores normalizados e ponderados de forma equivalente.

---

# Objetivo

O objetivo principal do ranking é:

* Identificar os técnicos com melhor desempenho operacional.
* Apoiar a gestão na tomada de decisão.
* Incentivar a melhoria contínua dos resultados.
* Detectar inconsistências cadastrais e conflitos de projetos.
* Fornecer uma visão comparativa entre equipes, supervisores e projetos.

---

# Fonte dos Dados

Os dados são obtidos da tabela:

```sql
public.acompanhamento_mensal_visitas
```

Todas as métricas são calculadas com base nas visitas realizadas dentro do período selecionado pelo usuário.

---

# Indicadores Utilizados

O ranking é composto por sete indicadores.

| Indicador                      | Descrição                                                  | Objetivo  |
| ------------------------------ | ---------------------------------------------------------- | --------- |
| Propriedades Ativas            | Quantidade de propriedades ativas atendidas pelo técnico   | Maximizar |
| Total de Visitas               | Quantidade total de visitas realizadas                     | Maximizar |
| Total de Orientações           | Quantidade total de orientações registradas                | Maximizar |
| Taxa de Visitas Válidas        | Percentual de visitas consideradas válidas                 | Maximizar |
| Taxa de Orientações Concluídas | Percentual de orientações concluídas                       | Maximizar |
| Propriedades Inativas          | Quantidade de propriedades inativas                        | Minimizar |
| Propriedades Multi-Projeto     | Quantidade de propriedades vinculadas a múltiplos projetos | Minimizar |

---

# Cálculo dos Indicadores

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

## Exportação

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

* Python
* Streamlit
* PostgreSQL
* SQLAlchemy
* Pandas
* Plotly

---

# Responsável

Sistema desenvolvido para acompanhamento e gestão da performance dos técnicos ATeG, utilizando métricas operacionais, indicadores de qualidade e mecanismos de auditoria para garantir consistência dos resultados.
