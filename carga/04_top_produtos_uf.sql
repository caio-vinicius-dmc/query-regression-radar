-- Produtos mais vendidos em um estado. Relatório pesado, roda poucas vezes.
SELECT pr.categoria,
       pr.nome,
       sum(i.quantidade)                      AS unidades,
       sum(i.quantidade * i.preco_unitario)   AS receita
FROM loja.item_pedido i
JOIN loja.pedido  p  ON p.id = i.pedido_id
JOIN loja.cliente c  ON c.id = p.cliente_id
JOIN loja.produto pr ON pr.id = i.produto_id
WHERE c.uf = %(uf)s
  AND p.criado_em >= %(inicio)s
GROUP BY pr.categoria, pr.nome
ORDER BY receita DESC
LIMIT 15;
