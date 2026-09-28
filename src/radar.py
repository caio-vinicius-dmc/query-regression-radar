"""Captura e comparação das estatísticas do pg_stat_statements."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from .config import Config

# As consultas do próprio radar não interessam no relatório: sem este
# filtro, o INSERT da captura e as checagens de chave estrangeira aparecem
# entre as regressões e escondem o que importa.
#
# A aspa dupla em '"radar"' não é descuido: o Postgres normaliza as
# checagens internas de FK com o nome do schema entre aspas, e o padrão sem
# elas não casa.
FILTRO_RUIDO = """
    s.query NOT ILIKE '%%radar.%%'
AND s.query NOT ILIKE '%%"radar"%%'
AND s.query NOT ILIKE '%%pg_stat_statements%%'
AND s.query NOT ILIKE '%%pg_indexes%%'
AND s.query NOT ILIKE '%%pg_catalog%%'
AND s.query NOT ILIKE '%%information_schema%%'
AND s.query NOT ILIKE 'COMMIT%%'
AND s.query NOT ILIKE 'BEGIN%%'
AND s.query NOT ILIKE 'SET %%'
AND s.query NOT ILIKE 'VACUUM%%'
AND s.query NOT ILIKE 'ANALYZE%%'
AND s.query NOT ILIKE 'CREATE%%'
AND s.query NOT ILIKE 'DROP%%'
"""


@contextmanager
def conectar(cfg: Config, autocommit: bool = False) -> Iterator[psycopg.Connection]:
    with psycopg.connect(cfg.dsn, row_factory=dict_row, autocommit=autocommit) as conexao:
        yield conexao


@dataclass
class Regressao:
    queryid: int
    consulta: str
    chamadas_antes: int
    chamadas_depois: int
    media_antes_ms: float
    media_depois_ms: float
    fator: float | None
    impacto_ms: float
    blocos_por_chamada_antes: float
    blocos_por_chamada_depois: float

    @property
    def nova(self) -> bool:
        """Consulta que não existia na captura anterior.

        Não é regressão: é algo novo. Costuma aparecer depois de um deploy
        e merece atenção por outro motivo -- ninguém mediu aquilo antes.
        """
        return self.chamadas_antes == 0

    def classificar(self, fator_minimo: float, impacto_minimo: float) -> str:
        if self.nova:
            return "nova"
        if self.fator is None:
            return "ok"
        if self.fator >= fator_minimo * 2 and self.impacto_ms >= impacto_minimo:
            return "grave"
        if self.fator >= fator_minimo and self.impacto_ms >= impacto_minimo:
            return "regressao"
        if self.fator <= 1 / fator_minimo:
            return "melhorou"
        return "ok"


def capturar(cfg: Config, rotulo: str, observacao: str | None = None) -> dict:
    """Copia o estado atual do pg_stat_statements para o histórico.

    O rótulo é único: recapturar com o mesmo nome substitui a captura
    anterior. É o comportamento útil quando se está iterando -- e evita
    encher a tabela de 'antes', 'antes2', 'antes_agora_vai'.
    """
    with conectar(cfg, autocommit=True) as conexao:
        conexao.execute("DELETE FROM radar.captura WHERE rotulo = %s", (rotulo,))
        linha = conexao.execute(
            "INSERT INTO radar.captura (rotulo, observacao) VALUES (%s, %s) RETURNING id",
            (rotulo, observacao),
        ).fetchone()
        captura_id = linha["id"]

        resultado = conexao.execute(
            f"""
            INSERT INTO radar.amostra (
                captura_id, queryid, consulta, calls,
                total_exec_time, mean_exec_time, linhas,
                blocos_cache, blocos_disco
            )
            SELECT %s,
                   s.queryid,
                   -- O pg_stat_statements guarda o comentário que abre a
                   -- consulta, e ele e a melhor identificação que existe:
                   -- "Historico de pedidos de um cliente" diz mais do que
                   -- "SELECT p.id, p.criado_em". Em vez de descartar, o
                   -- radar só tira os traços e o espaço extra.
                   left(btrim(regexp_replace(s.query, '(--|\\s+)', ' ', 'g')), 400),
                   s.calls,
                   s.total_exec_time,
                   s.mean_exec_time,
                   s.rows,
                   s.shared_blks_hit,
                   s.shared_blks_read
              FROM pg_stat_statements s
              JOIN pg_database d ON d.oid = s.dbid
             WHERE d.datname = current_database()
               AND s.queryid IS NOT NULL
               AND {FILTRO_RUIDO}
            """,
            (captura_id,),
        )

        total = conexao.execute(
            "SELECT count(*) AS total, sum(calls) AS chamadas "
            "FROM radar.amostra WHERE captura_id = %s",
            (captura_id,),
        ).fetchone()

    return {
        "id": captura_id,
        "rotulo": rotulo,
        "consultas": total["total"],
        "chamadas": total["chamadas"] or 0,
    }


def listar_capturas(cfg: Config) -> list[dict]:
    with conectar(cfg) as conexao:
        return conexao.execute(
            """
            SELECT c.rotulo,
                   c.observacao,
                   c.capturado_em,
                   count(a.queryid)   AS consultas,
                   coalesce(sum(a.calls), 0) AS chamadas
              FROM radar.captura c
              LEFT JOIN radar.amostra a ON a.captura_id = c.id
             GROUP BY c.id, c.rotulo, c.observacao, c.capturado_em
             ORDER BY c.capturado_em
            """
        ).fetchall()


def comparar(cfg: Config, antes: str, depois: str) -> list[Regressao]:
    with conectar(cfg) as conexao:
        existentes = {
            linha["rotulo"]
            for linha in conexao.execute("SELECT rotulo FROM radar.captura").fetchall()
        }
        for rotulo in (antes, depois):
            if rotulo not in existentes:
                disponiveis = ", ".join(sorted(existentes)) or "nenhuma"
                raise RuntimeError(
                    f"Captura '{rotulo}' não existe. Disponíveis: {disponiveis}"
                )

        linhas = conexao.execute(
            "SELECT * FROM radar.comparar(%s, %s)", (antes, depois)
        ).fetchall()

    return [Regressao(**linha) for linha in linhas]


def resetar_estatisticas(cfg: Config) -> None:
    """Zera o pg_stat_statements.

    Usado só na preparação do laboratório. Em produção o reset apaga o
    histórico de todo mundo, e quem estiver medindo ao mesmo tempo perde o
    trabalho -- por isso o comando avisa antes.
    """
    with conectar(cfg, autocommit=True) as conexao:
        conexao.execute("SELECT pg_stat_statements_reset()")
