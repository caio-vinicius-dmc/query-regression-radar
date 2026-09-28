# Comparação: antes -> depois

Gerado em 26/09/2026 às 00:22.

Critério: uma consulta vira regressão quando fica pelo menos 1,5x mais lenta **e** consome ao menos 100 ms a mais no intervalo. Os dois critérios juntos, porque nenhum dos dois sozinho separa o que importa: 3x mais lenta rodando uma vez por mês não é urgente, e 20% mais lenta rodando mil vezes por minuto é.

## Resumo

- 7 consultas comparadas
- **1 regressão grave**
- 1 regressão
- 0 consultas novas (não existiam na captura anterior)
- 0 melhoraram

| Situação | Chamadas | Antes | Depois | Fator | Impacto | Consulta |
|----------|----------|-------|--------|-------|---------|----------|
| grave | 400 | 0,06 ms | 8,57 ms | 150,90x | 3,4 s | `Histórico de pedidos de um cliente. É a consulta mais chamada do   sistema: aparece em tod` |
| regressão | 20 | 7,59 ms | 19,98 ms | 2,63x | 248 ms | `Clientes de um segmento sem pedido recente. Usada em campanha. SELECT c.id, c.nome, c.cida` |

## Regressões graves

### 150,90x mais lenta, 3,4 s de impacto

```sql
Histórico de pedidos de um cliente. É a consulta mais chamada do   sistema: aparece em toda tela de conta.   Depende de idx_pedido_cliente_data. SELECT p.id, p.criado_em, p.status, p.valor_total FROM loja.pedido p WHERE p.cliente_id = $1 ORDER BY p.criado_em DESC LIMIT $2
```

- Média antes: 0,06 ms
- Média no intervalo: 8,57 ms
- Chamadas no intervalo: 400
- Blocos por chamada: 19,3 -> 1.903,0

O número de blocos lidos por chamada explodiu junto com o tempo. O padrão combina com índice removido ou ignorado: o plano trocou por uma varredura de tabela. Vale rodar um EXPLAIN nesta consulta antes de qualquer outra coisa.
