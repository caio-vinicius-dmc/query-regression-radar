-- Detalhe de um pedido. Chamada logo depois da consulta 01.
SELECT i.produto_id, pr.nome, i.quantidade, i.preco_unitario
FROM loja.item_pedido i
JOIN loja.produto pr ON pr.id = i.produto_id
WHERE i.pedido_id = %(pedido_id)s;
