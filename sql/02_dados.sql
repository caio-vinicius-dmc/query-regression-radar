-- Massa sintética da base observada.
-- Marcadores trocados pelo carregador: {qtd_clientes}, {qtd_pedidos}.

SELECT setseed(0.19);

TRUNCATE loja.item_pedido, loja.pedido, loja.produto, loja.cliente CASCADE;

INSERT INTO loja.cliente (id, nome, email, cidade, uf, segmento)
SELECT
    g,
    'Cliente ' || g,
    'cliente' || g || '@exemplo.invalido',
    (ARRAY['Sao Paulo','Campinas','Rio de Janeiro','Belo Horizonte','Curitiba',
           'Porto Alegre','Salvador','Recife','Fortaleza','Goiania'])[1 + (g % 10)],
    (ARRAY['SP','SP','RJ','MG','PR','RS','BA','PE','CE','GO'])[1 + (g % 10)],
    CASE WHEN random() < 0.70 THEN 'Varejo'
         WHEN random() < 0.92 THEN 'Recorrente'
         ELSE 'Corporativo' END
FROM generate_series(1, {qtd_clientes}) AS g;

INSERT INTO loja.produto (id, sku, nome, categoria, preco)
SELECT
    g,
    'SKU-' || lpad(g::text, 5, '0'),
    'Produto ' || g,
    (ARRAY['Eletronicos','Casa','Moda','Esporte','Livros','Beleza'])[1 + (g % 6)],
    round((random() * 690 + 25)::numeric, 2)
FROM generate_series(1, 1200) AS g;

INSERT INTO loja.pedido (id, cliente_id, criado_em, status, valor_total)
SELECT
    g,
    1 + (random() * ({qtd_clientes} - 1))::int,
    TIMESTAMPTZ '2025-01-01'
        + (random() * 600)::int * INTERVAL '1 day'
        + (random() * 86399)::int * INTERVAL '1 second',
    CASE WHEN random() < 0.015 THEN 'cancelado'
         WHEN random() < 0.08  THEN 'pendente'
         ELSE 'faturado' END,
    round((random() * 1400 + 35)::numeric, 2)
FROM generate_series(1, {qtd_pedidos}) AS g;

-- Número de itens derivado do id, e não de random(): dentro de um LATERAL
-- o planejador pode avaliar a função volátil uma única vez.
WITH itens AS (
    SELECT p.id AS pedido_id,
           n,
           1 + (1199 * power(random(), 2.0))::int AS produto_id,
           1 + (random() * 3)::int                AS quantidade
    FROM loja.pedido p
    CROSS JOIN LATERAL generate_series(1, 1 + (p.id % 3)) AS n
)
INSERT INTO loja.item_pedido (id, pedido_id, produto_id, quantidade, preco_unitario)
SELECT row_number() OVER (), i.pedido_id, i.produto_id, i.quantidade, pr.preco
FROM itens i
JOIN loja.produto pr ON pr.id = i.produto_id;

ANALYZE loja.cliente;
ANALYZE loja.produto;
ANALYZE loja.pedido;
ANALYZE loja.item_pedido;
