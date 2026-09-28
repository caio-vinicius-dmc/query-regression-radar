"""Preparacao do laboratório: schema, massa e índices."""

from __future__ import annotations

import time

import psycopg

from .config import RAIZ, Config

PASTA_SQL = RAIZ / "sql"

# O índice que o comando "regredir" derruba. E o mais usado da base: sem
# ele, a consulta mais chamada do sistema passa a varrer a tabela inteira.
INDICE_ALVO = "idx_pedido_cliente_data"


def esperar_banco(cfg: Config, tentativas: int = 30, intervalo: float = 2.0) -> None:
    ultimo_erro: Exception | None = None
    for _ in range(tentativas):
        try:
            with psycopg.connect(cfg.dsn, connect_timeout=3) as conexao:
                conexao.execute("SELECT 1")
            return
        except psycopg.OperationalError as erro:
            # Senha recusada não melhora com nova tentativa -- insistir só
            # faz o comando demorar um minuto para dar a mensagem errada.
            #
            # O caso clássico e o volume do Docker ter sido criado com outra
            # senha: o Postgres só lê POSTGRES_PASSWORD na primeira
            # inicialização do diretório de dados e ignora a mudança no .env
            # depois disso.
            if "password authentication failed" in str(erro):
                raise RuntimeError(
                    f"O banco recusou a senha de {cfg.destino_legivel()}. "
                    "Se você mudou POSTGRES_PASSWORD depois de já ter subido o "
                    "container, o volume antigo ainda guarda a senha original. "
                    "Recrie o ambiente com: docker compose down -v && docker compose up -d"
                ) from erro

            ultimo_erro = erro
            time.sleep(intervalo)
    raise RuntimeError(
        f"Sem conexão com {cfg.destino_legivel()}. "
        f"O container subiu? Último erro: {ultimo_erro}"
    )


def _executar(cfg: Config, sql: str, autocommit: bool = False) -> None:
    with psycopg.connect(cfg.dsn, autocommit=autocommit) as conexao:
        conexao.execute(sql)


def criar_estrutura(cfg: Config) -> None:
    _executar(cfg, (PASTA_SQL / "01_estrutura.sql").read_text(encoding="utf-8"))


def carregar_dados(cfg: Config) -> float:
    sql = (PASTA_SQL / "02_dados.sql").read_text(encoding="utf-8").format(
        qtd_clientes=int(cfg.qtd_clientes),
        qtd_pedidos=int(cfg.qtd_pedidos),
    )
    inicio = time.perf_counter()
    _executar(cfg, sql)
    return time.perf_counter() - inicio


def criar_indices(cfg: Config) -> None:
    _executar(cfg, (PASTA_SQL / "03_indices.sql").read_text(encoding="utf-8"))
    # VACUUM fora de transação: o mapa de visibilidade precisa estar em dia
    # para os planos de Index Only Scan valerem alguma coisa.
    _executar(cfg, "VACUUM (ANALYZE) loja.cliente, loja.produto, loja.pedido, loja.item_pedido",
              autocommit=True)


def derrubar_indice(cfg: Config, nome: str = INDICE_ALVO) -> bool:
    """Remove um índice para simular a regressão.

    E o que uma migração mal feita faz sem querer: o índice some, nada
    quebra, e a consulta mais chamada do sistema passa a varrer a tabela.
    """
    with psycopg.connect(cfg.dsn, autocommit=True) as conexao:
        existia = conexao.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s", (nome,)
        ).fetchone()
        conexao.execute(f"DROP INDEX IF EXISTS loja.{nome}")
        conexao.execute("ANALYZE loja.pedido")
    return existia is not None


def contar_linhas(cfg: Config) -> dict[str, int]:
    tabelas = ("cliente", "produto", "pedido", "item_pedido")
    with psycopg.connect(cfg.dsn) as conexao:
        return {
            tabela: conexao.execute(f"SELECT count(*) FROM loja.{tabela}").fetchone()[0]
            for tabela in tabelas
        }


def indices_existentes(cfg: Config) -> list[str]:
    with psycopg.connect(cfg.dsn) as conexao:
        return [
            linha[0]
            for linha in conexao.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'loja' AND indexname LIKE 'idx_%' "
                "ORDER BY indexname"
            ).fetchall()
        ]
