-- Faturamento de uma janela de dias. Roda em relatório, algumas vezes por hora.
SELECT date_trunc('day', p.criado_em) AS dia,
       count(*)                       AS pedidos,
       sum(p.valor_total)             AS receita
FROM loja.pedido p
WHERE p.criado_em >= %(inicio)s
  AND p.criado_em <  %(fim)s
  AND p.status = 'faturado'
GROUP BY 1
ORDER BY 1;
