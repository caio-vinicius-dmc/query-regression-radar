# query-regression-radar

Descobre qual consulta ficou mais lenta depois de uma mudança no sistema,
comparando duas "fotografias" do banco de dados.

## Do que se trata, em linguagem simples

Imagine que na terça-feira o sistema estava rápido e na quarta ficou
lento. Alguém subiu uma alteração no meio disso. A pergunta é: **qual das
quarenta consultas do sistema piorou?**

Sem ferramenta, a resposta costuma ser chute. Alguém olha o código, acha
um suspeito, testa, e às vezes acerta.

O PostgreSQL tem uma extensão chamada `pg_stat_statements` que anota,
sozinha, quantas vezes cada consulta rodou e quanto tempo levou no total.
Este projeto tira uma cópia dessas anotações antes e depois da mudança, e
compara as duas — apontando o que piorou, o quanto piorou e, principal-
mente, **o quanto isso custou de verdade**.

## A demonstração, do começo ao fim

O projeto simula o acidente mais comum: uma migração de banco que apaga um
índice sem querer. Ninguém percebe, porque nada dá erro — o sistema só
fica mais lento.

```
1. base saudável, com todos os índices  →  tira a foto "antes"
2. alguém apaga um índice                →  ninguém percebe
3. o sistema continua rodando            →  tira a foto "depois"
4. compara as duas fotos                 →  o radar aponta o culpado
```

O resultado:

| Situação | Consulta | Chamadas | Antes | Depois | Ficou | Custou |
|----------|----------|----------|-------|--------|-------|--------|
| grave | Histórico de pedidos de um cliente | 400 | 0,06 ms | 8,57 ms | 151x mais lenta | 3,4 s |
| regressão | Clientes de um segmento sem pedido | 20 | 7,59 ms | 19,98 ms | 2,6x | 248 ms |

E o relatório em Markdown explica o porquê:

```
- Média antes: 0,06 ms
- Média no intervalo: 8,57 ms
- Chamadas no intervalo: 400
- Blocos por chamada: 19,3 -> 1.903,0

O número de blocos lidos por chamada explodiu junto com o tempo. O padrão
combina com índice removido ou ignorado: o plano trocou por uma varredura
de tabela.
```

Recriando o índice e comparando de novo, o radar acusa a melhora: a mesma
consulta aparece como `melhorou`, 0,02x — ou seja, cinquenta vezes mais
rápida do que estava.

## O que você precisa ter instalado

- **Docker Desktop** — sobe o banco de dados sem instalar nada permanente.
  [docker.com](https://www.docker.com/products/docker-desktop/)
- **Python 3.11 ou mais novo** —
  [python.org](https://www.python.org/downloads/), marcando "Add Python to
  PATH" na instalação.

## Como rodar

**1. Configuração e banco.**

```bash
cp .env.example .env
docker compose up -d
```

**2. Ambiente do Python.**

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
```

No Linux ou macOS: `source .venv/bin/activate`.

**3. Monte a base.** Cria 250 mil pedidos e os índices. Leva uns 25
segundos.

```bash
python -m src.cli preparar
```

**4. Agora a demonstração completa**, que leva menos de um minuto:

```bash
# o sistema rodando normalmente
python -m src.cli carga --ciclos 10
python -m src.cli capturar antes --observacao "base com todos os indices"

# alguém apaga um índice sem perceber
python -m src.cli regredir

# o sistema continua rodando, agora mais lento
python -m src.cli carga --ciclos 10
python -m src.cli capturar depois --observacao "sem idx_pedido_cliente_data"

# o que mudou?
python -m src.cli comparar antes depois --relatorio
```

**5. Para ver o radar acusar a melhora**, recrie o índice e compare de
novo:

```bash
python -m src.cli restaurar
python -m src.cli carga --ciclos 10
python -m src.cli capturar corrigido
python -m src.cli comparar depois corrigido
```

### Quando terminar

```bash
docker compose down -v
```

## As três decisões que fazem isso funcionar

### 1. Olhar o intervalo, não o acumulado

O `pg_stat_statements` guarda a média de **todas** as execuções desde que
o banco foi ligado. Isso esconde o problema.

Um exemplo: uma consulta roda há três meses em 0,5 ms e ontem passou a
levar 50 ms. Se ela acumulou um milhão de execuções rápidas e dez mil
lentas, a média sobe de 0,50 ms para 0,99 ms. Parece que dobrou, quando na
verdade ficou cem vezes pior.

O radar calcula o comportamento **só no intervalo entre as duas fotos**:

```
tempo gasto entre as fotos ÷ execuções entre as fotos
```

No exemplo acima, o resultado seria 50 ms, e não 0,99 ms.

### 2. Cruzar o quanto piorou com o quanto isso custa

Uma consulta três vezes mais lenta que roda uma vez por mês não é urgente.
Uma vinte por cento mais lenta que roda mil vezes por minuto é. Ordenar a
lista por qualquer um dos dois critérios sozinho produz uma lista inútil.

O radar só marca como regressão o que passa dos **dois** limites ao mesmo
tempo:

```bash
python -m src.cli comparar antes depois --fator 1.5 --impacto 100
```

O "impacto" é o tempo extra total que a consulta consumiu por causa da
piora — em outras palavras, quanto de processamento aquela regressão
custou de verdade.

### 3. Contar blocos, somando memória e disco

A leitura de disco isolada engana. Numa base que cabe na memória, a
varredura de tabela lê tudo da memória e o contador de disco fica em zero,
mesmo com o problema acontecendo.

O que denuncia a mudança é o total de blocos que a consulta toca por
execução. No exemplo: 19 blocos viraram 1.903.

## Usando num sistema de verdade

O comando `comparar` termina com código de erro quando encontra regressão
grave, então serve como etapa de uma esteira de deploy:

```bash
python -m src.cli capturar pre_deploy
# ... deploy e período de observação ...
python -m src.cli capturar pos_deploy
python -m src.cli comparar pre_deploy pos_deploy --relatorio || exit 1
```

Para apontar para um banco real, o necessário é a extensão instalada e um
usuário com permissão de leitura de estatísticas. As fotos e a comparação
não escrevem nada fora do schema `radar`.

Os nomes das fotos são únicos: repetir o mesmo nome substitui a anterior.
Isso evita encher a tabela de `antes`, `antes2`, `antes_agora_vai`.

## Estrutura das pastas

```
sql/01_estrutura.sql   a base observada, o histórico e a função de comparação
sql/02_dados.sql       os dados de mentira
sql/03_indices.sql     os índices do estado saudável
carga/*.sql            as cinco consultas que simulam o uso do sistema
src/carga.py           roda as consultas com pesos e parâmetros variados
src/radar.py           tira as fotos e compara
src/relatorio.py       escreve o Markdown
docs/metodologia.md    o detalhe de cada decisão de medição
```

A comparação é uma função escrita em SQL, dentro do banco, e não em
Python. O cálculo é todo soma e agrupamento sobre duas tabelas — coisa que
o banco faz melhor — e desse jeito ela fica disponível para qualquer
ferramenta que converse com o banco, inclusive um painel de BI, sem passar
pelo terminal.

## Sobre a carga simulada

Cinco consultas com pesos diferentes, imitando o que uma aplicação faria:
a tela de conta do cliente é chamada quarenta vezes por ciclo, o relatório
de campanha duas.

Os parâmetros mudam a cada chamada. Isso importa: se fosse sempre o mesmo
cliente, o banco responderia da memória depois da primeira vez e a medição
não diria nada sobre o comportamento real.

## Problemas comuns

**"ports are not available" ou "bind: An attempt was made to access a socket
in a way forbidden by its access permissions".** O Windows reserva faixas de
porta para uso próprio, e elas mudam a cada reinício. Veja quais estão
reservadas com:

```bash
netsh int ipv4 show excludedportrange protocol=tcp
```

Se a porta do projeto estiver numa das faixas, mude `POSTGRES_PORT` no
arquivo `.env` para qualquer valor livre abaixo de 49152 e suba de novo.

**"O banco recusou a senha."** Você mudou a senha no `.env` depois de já
ter subido o banco. Recrie com `docker compose down -v && docker compose up -d`.

**"Captura 'antes' não existe."** As fotos são gravadas no banco. Se você
rodou `docker compose down -v`, elas foram junto. Refaça desde o
`preparar`.

**O comando `comparar` não mostra nada.** Provavelmente não houve carga
entre as duas fotos. O radar ignora consultas que não rodaram no intervalo
— não há o que comparar.

## Limitações

- O identificador interno de cada consulta muda entre versões do
  PostgreSQL e quando o texto da consulta muda. Comparar fotos tiradas em
  versões diferentes marca tudo como "nova".
- O `pg_stat_statements` tem um limite de consultas distintas que consegue
  guardar. Numa instância com muita variedade, as menos frequentes são
  descartadas e não aparecem.
- A medição é do banco, não da aplicação. Tempo de rede, de fila de
  conexão e de conversão de dados não entram na conta.
- O radar aponta a consulta suspeita, mas não compara automaticamente o
  caminho que o banco escolheu antes e depois. Fazer isso exigiria uma
  coleta bem mais pesada.

---

## 👤 Autor

Desenvolvido por **Caio Vinícius Barbosa Barros**.

Se você tiver dúvidas, sugestões ou quiser reportar um problema, sinta-se à vontade para entrar em contato:

*   **✉️ E-mail:** [caio@dynamicmotioncentury.com.br](mailto:caio@dynamicmotioncentury.com.br)
*   **🌐 Site/Portfólio:** [www.dynamicmotioncentury.com.br](https://dynamicmotioncentury.com.br)
*   **💼 LinkedIn:** [linkedin.com/in/caio-vinicius-dmc](https://linkedin.com/in/caio-vinicius-dmc)
*   **🐙 GitHub:** [@caio-vinicius-dmc](https://github.com/caio-vinicius-dmc)

💡 *Se este projeto te ajudou, deixe uma ⭐ no repositório!*
