-- Estrutura do laboratório: a base observada e o histórico de capturas.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE SCHEMA IF NOT EXISTS loja;
CREATE SCHEMA IF NOT EXISTS radar;

-- ---------------------------------------------------------------------------
-- Base observada
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS loja.item_pedido CASCADE;
DROP TABLE IF EXISTS loja.pedido CASCADE;
DROP TABLE IF EXISTS loja.produto CASCADE;
DROP TABLE IF EXISTS loja.cliente CASCADE;

CREATE TABLE loja.cliente (
    id        integer PRIMARY KEY,
    nome      text    NOT NULL,
    email     text    NOT NULL,
    cidade    text    NOT NULL,
    uf        char(2) NOT NULL,
    segmento  text    NOT NULL
);

CREATE TABLE loja.produto (
    id        integer PRIMARY KEY,
    sku       text          NOT NULL,
    nome      text          NOT NULL,
    categoria text          NOT NULL,
    preco     numeric(10,2) NOT NULL
);

CREATE TABLE loja.pedido (
    id          integer PRIMARY KEY,
    cliente_id  integer       NOT NULL REFERENCES loja.cliente (id),
    criado_em   timestamptz   NOT NULL,
    status      text          NOT NULL,
    valor_total numeric(12,2) NOT NULL
);

CREATE TABLE loja.item_pedido (
    id             bigint PRIMARY KEY,
    pedido_id      integer       NOT NULL REFERENCES loja.pedido (id),
    produto_id     integer       NOT NULL REFERENCES loja.produto (id),
    quantidade     smallint      NOT NULL,
    preco_unitario numeric(10,2) NOT NULL
);

-- ---------------------------------------------------------------------------
-- Histórico de capturas
-- ---------------------------------------------------------------------------
-- pg_stat_statements e cumulativo e vive em memória: reiniciar o servidor
-- ou chamar o reset apaga tudo. Copiar o conteudo para uma tabela própria,
-- com rótulo e data, e é o que permite comparar "antes do deploy" com
-- "depois do deploy" dias mais tarde.
CREATE TABLE IF NOT EXISTS radar.captura (
    id           bigserial PRIMARY KEY,
    rotulo       text        NOT NULL,
    observacao   text,
    capturado_em timestamptz NOT NULL DEFAULT now(),
    UNIQUE (rotulo)
);

CREATE TABLE IF NOT EXISTS radar.amostra (
    captura_id       bigint  NOT NULL REFERENCES radar.captura (id) ON DELETE CASCADE,
    queryid          bigint  NOT NULL,
    consulta         text    NOT NULL,
    calls            bigint  NOT NULL,
    total_exec_time  double precision NOT NULL,
    mean_exec_time   double precision NOT NULL,
    linhas           bigint  NOT NULL,
    blocos_cache     bigint  NOT NULL,
    blocos_disco     bigint  NOT NULL,
    PRIMARY KEY (captura_id, queryid)
);

-- ---------------------------------------------------------------------------
-- Comparação entre duas capturas
-- ---------------------------------------------------------------------------
-- A métrica correta não é o mean_exec_time acumulado de cada captura: ele
-- mistura todas as execuções desde o último reset, então uma consulta que
-- ficou lenta ontem continua parecendo rápida por causa da média de meses.
--
-- O que interessa é o comportamento NO INTERVALO entre as duas capturas:
-- tempo total que passou a mais, dividido pelas chamadas que passaram a
-- mais. E o mesmo cálculo que as ferramentas de APM fazem.
-- O DROP antes do CREATE não é redundante: CREATE OR REPLACE não consegue
-- alterar o tipo de retorno de uma função. Sem ele, acrescentar uma coluna
-- aqui falha com "cannot change return type of existing function" -- e o
-- script parece ter rodado, porque o erro sai no meio de uma transação que
-- o carregador não interrompe.
DROP FUNCTION IF EXISTS radar.comparar(text, text);

CREATE FUNCTION radar.comparar(rotulo_antes text, rotulo_depois text)
RETURNS TABLE (
    queryid          bigint,
    consulta         text,
    chamadas_antes   bigint,
    chamadas_depois  bigint,
    media_antes_ms   double precision,
    media_depois_ms  double precision,
    fator            double precision,
    impacto_ms       double precision,
    -- Blocos por chamada, somando cache e disco. O total e que denuncia a
    -- varredura de tabela: numa base que cabe em memória, a leitura de
    -- disco fica em zero mesmo com o plano trocado, e olhar só para ela
    -- esconde o problema.
    blocos_por_chamada_antes  double precision,
    blocos_por_chamada_depois double precision
)
LANGUAGE sql STABLE AS $$
    WITH antes AS (
        SELECT a.* FROM radar.amostra a
        JOIN radar.captura c ON c.id = a.captura_id
        WHERE c.rotulo = rotulo_antes
    ),
    depois AS (
        SELECT a.* FROM radar.amostra a
        JOIN radar.captura c ON c.id = a.captura_id
        WHERE c.rotulo = rotulo_depois
    ),
    delta AS (
        SELECT
            d.queryid,
            d.consulta,
            coalesce(a.calls, 0)                           AS calls_acum_antes,
            d.calls                                        AS calls_acum_depois,
            d.calls - coalesce(a.calls, 0)                 AS calls_intervalo,
            d.total_exec_time - coalesce(a.total_exec_time, 0) AS tempo_intervalo,
            (d.blocos_cache + d.blocos_disco)
                - coalesce(a.blocos_cache + a.blocos_disco, 0) AS blocos_intervalo,
            a.mean_exec_time                               AS media_antes,
            (a.blocos_cache + a.blocos_disco)              AS blocos_antes,
            a.calls                                        AS calls_antes
        FROM depois d
        LEFT JOIN antes a ON a.queryid = d.queryid
    )
    SELECT
        delta.queryid,
        delta.consulta,
        coalesce(delta.calls_antes, 0),
        delta.calls_intervalo,
        -- Média da captura anterior: o comportamento conhecido como bom.
        round(coalesce(delta.media_antes, 0)::numeric, 3)::double precision,
        -- Média observada no intervalo entre as duas capturas.
        round((delta.tempo_intervalo / nullif(delta.calls_intervalo, 0))::numeric, 3)::double precision,
        round((
            (delta.tempo_intervalo / nullif(delta.calls_intervalo, 0))
            / nullif(delta.media_antes, 0)
        )::numeric, 2)::double precision,
        -- Impacto: quanto tempo a mais a consulta consumiu no intervalo por
        -- causa da piora. E o que separa "3x mais lenta e roda uma vez por
        -- mês" de "20% mais lenta e roda mil vezes por minuto".
        round((
            delta.tempo_intervalo
            - coalesce(delta.media_antes, 0) * delta.calls_intervalo
        )::numeric, 2)::double precision,
        round((
            coalesce(delta.blocos_antes, 0)::numeric
            / nullif(delta.calls_antes, 0)
        ), 1)::double precision,
        round((
            delta.blocos_intervalo::numeric / nullif(delta.calls_intervalo, 0)
        ), 1)::double precision
    FROM delta
    WHERE delta.calls_intervalo > 0
    ORDER BY 8 DESC;
$$;
