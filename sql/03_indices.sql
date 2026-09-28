-- Índices do estado "saudável" da base.
--
-- O comando "regredir" derruba o primeiro deles para simular o que
-- acontece quando uma migração esquece um índice para trás. O comando
-- "restaurar" recria todos.

CREATE INDEX IF NOT EXISTS idx_pedido_cliente_data
    ON loja.pedido (cliente_id, criado_em DESC);

CREATE INDEX IF NOT EXISTS idx_pedido_criado_em
    ON loja.pedido (criado_em);

CREATE INDEX IF NOT EXISTS idx_item_pedido
    ON loja.item_pedido (pedido_id);

CREATE INDEX IF NOT EXISTS idx_item_produto
    ON loja.item_pedido (produto_id);

CREATE INDEX IF NOT EXISTS idx_cliente_uf
    ON loja.cliente (uf);
