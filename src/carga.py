"""Simulação de carga: executa as consultas de `carga/` várias vezes.

Sem carga não há estatística. O pg_stat_statements só registra o que foi
executado, então o laboratório precisa gerar tráfego parecido com o de uma
aplicação: cada consulta chamada com frequência diferente e com parâmetros
diferentes a cada vez.

Os parâmetros variarem importa. Se todas as chamadas usassem o mesmo
cliente, o cache resolveria tudo depois da primeira e a medição não diria
nada sobre o comportamento real.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import psycopg

from .config import RAIZ, Config

PASTA_CARGA = RAIZ / "carga"

# Quantas vezes cada consulta roda a cada ciclo. Reflete o peso que ela
# teria numa aplicação: a tela de conta é muito mais chamada do que o
# relatório de campanha.
PESO = {
    "01_pedidos_do_cliente": 40,
    "02_faturamento_periodo": 6,
    "03_itens_do_pedido": 30,
    "04_top_produtos_uf": 3,
    "05_clientes_sem_compra": 2,
}

UFS = ["SP", "RJ", "MG", "PR", "RS", "BA", "PE", "CE", "GO"]
SEGMENTOS = ["Varejo", "Recorrente", "Corporativo"]


@dataclass(frozen=True)
class Consulta:
    nome: str
    sql: str
    descricao: str

    @property
    def parametros_usados(self) -> set[str]:
        return set(re.findall(r"%\((\w+)\)s", self.sql))


def carregar_consultas() -> list[Consulta]:
    consultas = []
    for arquivo in sorted(PASTA_CARGA.glob("*.sql")):
        texto = arquivo.read_text(encoding="utf-8")
        descricao = " ".join(
            linha.lstrip("- ").strip()
            for linha in texto.splitlines()
            if linha.strip().startswith("--")
        )
        consultas.append(Consulta(nome=arquivo.stem, sql=texto, descricao=descricao))

    if not consultas:
        raise FileNotFoundError(f"Nenhuma consulta encontrada em {PASTA_CARGA}")

    return consultas


def _sortear_parametros(aleatorio: random.Random, cfg: Config) -> dict:
    inicio = date(2025, 1, 1) + timedelta(days=aleatorio.randint(0, 540))
    return {
        "cliente_id": aleatorio.randint(1, cfg.qtd_clientes),
        "pedido_id": aleatorio.randint(1, cfg.qtd_pedidos),
        "uf": aleatorio.choice(UFS),
        "segmento": aleatorio.choice(SEGMENTOS),
        "inicio": inicio,
        "fim": inicio + timedelta(days=aleatorio.randint(7, 45)),
        "desde": inicio,
    }


def executar(cfg: Config, ciclos: int = 10, semente: int = 7) -> dict:
    """Roda a carga e devolve quantas chamadas cada consulta recebeu."""
    aleatorio = random.Random(semente)
    consultas = carregar_consultas()
    contagem = {c.nome: 0 for c in consultas}

    inicio = time.perf_counter()

    with psycopg.connect(cfg.dsn) as conexao:
        conexao.autocommit = True
        for _ in range(ciclos):
            for consulta in consultas:
                for _ in range(PESO.get(consulta.nome, 1)):
                    todos = _sortear_parametros(aleatorio, cfg)
                    # Passar só os parâmetros que a consulta usa: o psycopg
                    # aceita extras em dicionário, mas restringir deixa
                    # explícito no código qual consulta usa o quê.
                    usados = {
                        chave: todos[chave] for chave in consulta.parametros_usados
                    }
                    with conexao.cursor() as cursor:
                        cursor.execute(consulta.sql, usados)
                        cursor.fetchall()
                    contagem[consulta.nome] += 1

    return {
        "chamadas": contagem,
        "total": sum(contagem.values()),
        "segundos": time.perf_counter() - inicio,
    }
