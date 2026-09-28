# Metodologia

Por que a medição é feita assim. Quase todas as decisões abaixo corrigem
uma primeira versão que dava números plausíveis e errados.

## O problema com o mean_exec_time

`pg_stat_statements` guarda, por consulta, o total acumulado desde o último
reset: `calls`, `total_exec_time`, `mean_exec_time`. O `mean_exec_time` é
simplesmente `total_exec_time / calls`.

Parece a métrica óbvia para comparar duas capturas. Não é.

Imagine uma consulta que roda há três meses a 0,5 ms e, depois do deploy de
ontem, passou a levar 50 ms. Se ela acumulou um milhão de chamadas rápidas
e dez mil lentas, a média acumulada vai de 0,50 ms para 0,99 ms. Um fator
de 2x, quando a realidade é 100x.

Quanto mais antiga a instância, pior fica a diluição -- e é justamente na
instância antiga que a regressão custa caro.

## A média do intervalo

O radar trabalha com a diferença entre as duas capturas:

```
tempo_intervalo    = total_exec_time_depois - total_exec_time_antes
chamadas_intervalo = calls_depois           - calls_antes
media_intervalo    = tempo_intervalo / chamadas_intervalo
```

Isso mede exclusivamente o que aconteceu **entre** as capturas. No exemplo
acima, o resultado seria 50 ms, não 0,99 ms.

O lado "antes" da comparação continua usando o `mean_exec_time` acumulado,
e isso é proposital: ele representa o comportamento conhecido como bom,
consolidado ao longo de muitas execuções. O que interessa saber é se o
intervalo recente desviou disso.

Consultas com `chamadas_intervalo = 0` são descartadas. Não houve execução
nova entre as capturas, então não há o que comparar.

## Por que fator e impacto juntos

Ordenar por fator de piora traz uma lista dominada por consultas
irrelevantes: qualquer coisa que rodou três vezes e por acaso pegou um
momento ruim aparece com 8x.

Ordenar por impacto traz outra lista enviesada: as consultas mais chamadas
sempre lideram, tenham piorado ou não.

A classificação usa os dois:

| Situação | Critério |
|----------|----------|
| `grave` | fator ≥ 2× o mínimo **e** impacto ≥ o mínimo |
| `regressao` | fator ≥ mínimo **e** impacto ≥ o mínimo |
| `melhorou` | fator ≤ 1/mínimo |
| `nova` | não existia na captura anterior |
| `ok` | o resto |

O impacto é calculado como:

```
impacto = tempo_intervalo - (media_antes × chamadas_intervalo)
```

Ou seja: quanto tempo a mais o banco gastou naquela consulta por causa da
piora. É uma grandeza de custo, não de percepção -- e é o que permite
priorizar quando há seis regressões na lista.

## Blocos por chamada, cache incluído

A primeira versão reportava só `shared_blks_read`, a leitura de disco. Na
demonstração, o índice sumiu, o tempo foi de 0,06 ms para 7 ms, e a leitura
de disco... foi de 46 para **zero**.

O motivo: a tabela inteira cabe em `shared_buffers`. A varredura sequencial
lê tudo do cache, então o contador de disco não se mexe. Olhar só para ele
esconderia exatamente o caso que a ferramenta existe para achar.

Hoje a métrica é `(shared_blks_hit + shared_blks_read) / calls`. No mesmo
cenário: 19,3 blocos por chamada viraram 1.903,0. Isso sim é a assinatura
de uma varredura de tabela.

O diagnóstico automático dispara quando os blocos por chamada crescem pelo
menos 5x e passam de 100 -- combinação que, na prática, quase sempre
significa plano trocado.

## Rótulos únicos

Cada captura tem um rótulo, e recapturar com o mesmo nome substitui a
anterior.

A alternativa -- acumular capturas e comparar por data -- parece mais
flexível, mas na prática enche a tabela de `antes`, `antes2`,
`antes_agora_vai` durante a investigação. Substituir é o comportamento
mais útil para quem está iterando, e nomear a captura com o que ela
representa (`pre_deploy`, `pos_deploy`) é o que faz a comparação ficar
legível meses depois.

## Filtro de ruído

O radar precisa ignorar as próprias consultas. Sem isso, o `INSERT` da
captura aparece entre as regressões e esconde o que importa.

Um detalhe custou tempo: o filtro `query NOT ILIKE '%radar.%'` não pegava
as checagens internas de chave estrangeira, porque o PostgreSQL as
normaliza com o nome do schema entre aspas (`"radar"."captura"`). Foram
necessários os dois padrões.

## O comentário da consulta como identificação

`pg_stat_statements` guarda o texto normalizado da consulta, comentário de
abertura incluído. A primeira versão descartava o comentário e o relatório
ficava com linhas do tipo `SELECT p.id, p.criado_em, p.status FROM
loja.pedido p WHERE...`, indistinguíveis entre si.

Hoje o comentário fica. `Histórico de pedidos de um cliente. E a consulta
mais chamada do sistema` identifica muito melhor do que as primeiras
colunas do `SELECT`, e não custa nada -- o texto já estava lá.

Na prática, isso vale como argumento para comentar as consultas da
aplicação: o comentário vira o nome delas em qualquer ferramenta que leia o
`pg_stat_statements`.

## Por que a comparação é uma função SQL

`radar.comparar(antes, depois)` é uma função no banco, não código Python.

O cálculo é inteiramente agregação sobre duas tabelas -- o tipo de coisa
que o banco faz melhor, e sem trazer milhares de linhas pela rede. E, como
função, fica disponível para qualquer ferramenta que fale com o banco:
um dashboard de BI pode consultá-la direto, sem passar pela CLI.

Um detalhe do PostgreSQL que vale registrar: `CREATE OR REPLACE FUNCTION`
não consegue alterar o tipo de retorno. Acrescentar uma coluna à função
exige `DROP FUNCTION` antes -- e, sem ele, o script de estrutura falha no
meio, mas de um jeito que parece ter funcionado.

## A carga simulada

Sem tráfego não há estatística. A carga executa as cinco consultas de
`carga/` com pesos diferentes:

| Consulta | Chamadas por ciclo | Papel |
|----------|-------------------|-------|
| `01_pedidos_do_cliente` | 40 | tela de conta, a mais chamada |
| `03_itens_do_pedido` | 30 | detalhe, vem logo depois da 01 |
| `02_faturamento_periodo` | 6 | relatório recorrente |
| `04_top_produtos_uf` | 3 | relatório pesado |
| `05_clientes_sem_compra` | 2 | campanha |

Os pesos importam porque o impacto depende deles. Uma piora na consulta de
peso 40 custa vinte vezes mais que a mesma piora na de peso 2, e é essa
diferença que a ferramenta precisa refletir.

Os parâmetros são sorteados a cada chamada, com semente fixa. Com o mesmo
cliente sempre, o cache resolveria tudo depois da primeira execução e a
medição não diria nada sobre o comportamento real; com semente fixa, duas
execuções da carga produzem a mesma sequência de parâmetros e os números
ficam comparáveis.
