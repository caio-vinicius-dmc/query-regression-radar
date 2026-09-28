"""Configuração lida de variáveis de ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

load_dotenv(RAIZ / ".env")


@dataclass(frozen=True)
class Config:
    host: str
    porta: int
    banco: str
    usuario: str
    senha: str
    qtd_clientes: int
    qtd_pedidos: int

    @property
    def dsn(self) -> str:
        return (
            f"host={self.host} port={self.porta} dbname={self.banco} "
            f"user={self.usuario} password={self.senha}"
        )

    def destino_legivel(self) -> str:
        """Identificacao do banco sem a senha, para log e mensagens."""
        return f"{self.usuario}@{self.host}:{self.porta}/{self.banco}"


def carregar() -> Config:
    return Config(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        porta=int(os.getenv("POSTGRES_PORT", "15437")),
        banco=os.getenv("POSTGRES_DB", "loja"),
        usuario=os.getenv("POSTGRES_USER", "radar"),
        senha=os.getenv("POSTGRES_PASSWORD", "radar_local"),
        qtd_clientes=int(os.getenv("QTD_CLIENTES", "15000")),
        qtd_pedidos=int(os.getenv("QTD_PEDIDOS", "250000")),
    )
