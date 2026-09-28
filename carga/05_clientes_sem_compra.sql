-- Clientes de um segmento sem pedido recente. Usada em campanha.
SELECT c.id, c.nome, c.cidade
FROM loja.cliente c
WHERE c.segmento = %(segmento)s
  AND NOT EXISTS (
      SELECT 1 FROM loja.pedido p
       WHERE p.cliente_id = c.id
         AND p.criado_em >= %(desde)s
  )
LIMIT 50;
