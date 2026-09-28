-- Histórico de pedidos de um cliente. É a consulta mais chamada do
-- sistema: aparece em toda tela de conta.
-- Depende de idx_pedido_cliente_data.
SELECT p.id, p.criado_em, p.status, p.valor_total
FROM loja.pedido p
WHERE p.cliente_id = %(cliente_id)s
ORDER BY p.criado_em DESC
LIMIT 20;
