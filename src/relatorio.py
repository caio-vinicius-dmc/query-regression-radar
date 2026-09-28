"""Relatório em Markdown da comparação entre duas capturas."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import RAIZ
from .radar import Regressao

PASTA = RAIZ / "relatorios"

ORDEM = {"grave": 0, "regressao": 1, "nova": 2, "melhorou": 3, "ok": 4}

# O valor interno fica sem acento (é comparado no código); o rótulo que
# aparece no relatório é escrito por extenso e em português corrente.
ROTULO = {
    "grave": "grave",
    "regressao": "regressão",
    "nova": "nova",
    "melhorou": "melhorou",
    "ok": "ok",
}


def _plural(quantidade: int, singular: str, plural: str) -> str:
    """Concorda o substantivo com o número.

    "1 regressões graves" denuncia texto montado por concatenação. Custa
    três linhas evitar.
    """
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def _br(valor: float, casas: int = 0) -> str:
    bruto = f"{valor:,.{casas}f}"
    return bruto.replace(",", "@").replace(".", ",").replace("@", ".")


def _tempo(ms: float) -> str:
    """Impacto em ms ou em segundos, conforme a ordem de grandeza.

    "2.832 ms" no padrão brasileiro tem ponto de milhar e se confunde com
    dois milissegundos e pouco. Acima de um segundo, o número fica muito
    mais legível na unidade maior.
    """
    if abs(ms) >= 1000:
        return _br(ms / 1000, 1) + " s"
    # Arredondar um valor negativo pequeno produz "-0 ms", que parece defeito
    # de formatação. Abaixo de meio milissegundo o sinal não diz nada mesmo.
    if abs(ms) < 0.5:
        return "0 ms"
    return _br(ms, 0) + " ms"


def montar(
    antes: str,
    depois: str,
    classificados: list[tuple[Regressao, str]],
    fator_minimo: float,
    impacto_minimo: float,
) -> str:
    agora = datetime.now().strftime("%d/%m/%Y às %H:%M")
    graves = [r for r, s in classificados if s == "grave"]
    regressoes = [r for r, s in classificados if s == "regressao"]
    melhorias = [r for r, s in classificados if s == "melhorou"]
    novas = [r for r, s in classificados if s == "nova"]

    partes = [
        f"# Comparação: {antes} -> {depois}",
        "",
        f"Gerado em {agora}.",
        "",
        f"Critério: uma consulta vira regressão quando fica pelo menos "
        f"{fator_minimo}x mais lenta **e** consome ao menos {_br(impacto_minimo)} ms "
        f"a mais no intervalo. Os dois critérios juntos, porque nenhum dos "
        f"dois sozinho separa o que importa: 3x mais lenta rodando uma vez "
        f"por mês não é urgente, e 20% mais lenta rodando mil vezes por "
        f"minuto é.",
        "",
        "## Resumo",
        "",
        f"- {_plural(len(classificados), 'consulta comparada', 'consultas comparadas')}",
        f"- **{_plural(len(graves), 'regressão grave', 'regressões graves')}**",
        f"- {_plural(len(regressoes), 'regressão', 'regressões')}",
        f"- {_plural(len(novas), 'consulta nova', 'consultas novas')} (não existiam na captura anterior)",
        f"- {len(melhorias)} melhoraram",
        "",
    ]

    relevantes = [(r, s) for r, s in classificados if s != "ok"]
    if not relevantes:
        partes.extend(["Nenhuma consulta fora do critério.", ""])
        return "\n".join(partes)

    partes.extend(
        [
            "| Situação | Chamadas | Antes | Depois | Fator | Impacto | Consulta |",
            "|----------|----------|-------|--------|-------|---------|----------|",
        ]
    )
    for r, situacao in sorted(relevantes, key=lambda x: (ORDEM[x[1]], -x[0].impacto_ms)):
        antes_ms = "-" if r.nova else _br(r.media_antes_ms, 2) + " ms"
        fator = _br(r.fator, 2) + "x" if r.fator else "-"
        consulta = r.consulta[:90].replace("|", r"\|")
        partes.append(
            f"| {ROTULO.get(situacao, situacao)} | {_br(r.chamadas_depois)} | {antes_ms} | "
            f"{_br(r.media_depois_ms, 2)} ms | {fator} | {_tempo(r.impacto_ms)} | "
            f"`{consulta}` |"
        )

    partes.append("")

    if graves:
        partes.extend(["## Regressões graves", ""])
        for r in sorted(graves, key=lambda x: -x.impacto_ms):
            partes.extend(
                [
                    f"### {_br(r.fator, 2)}x mais lenta, {_tempo(r.impacto_ms)} de impacto",
                    "",
                    "```sql",
                    r.consulta,
                    "```",
                    "",
                    f"- Média antes: {_br(r.media_antes_ms, 2)} ms",
                    f"- Média no intervalo: {_br(r.media_depois_ms, 2)} ms",
                    f"- Chamadas no intervalo: {_br(r.chamadas_depois)}",
                    f"- Blocos por chamada: {_br(r.blocos_por_chamada_antes, 1)} -> "
                    f"{_br(r.blocos_por_chamada_depois, 1)}",
                    "",
                ]
            )
            if r.blocos_por_chamada_depois > max(r.blocos_por_chamada_antes * 5, 100):
                partes.extend(
                    [
                        "O número de blocos lidos por chamada explodiu junto com o "
                        "tempo. O padrão combina com índice removido ou ignorado: "
                        "o plano trocou por uma varredura de tabela. Vale rodar um "
                        "EXPLAIN nesta consulta antes de qualquer outra coisa.",
                        "",
                    ]
                )

    return "\n".join(partes)


def salvar(conteudo: str) -> Path:
    PASTA.mkdir(exist_ok=True)
    destino = PASTA / f"{datetime.now():%Y-%m-%d_%H%M%S}.md"
    destino.write_text(conteudo, encoding="utf-8")
    return destino
