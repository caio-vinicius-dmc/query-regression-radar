"""Linha de comando do radar.

Fluxo típico de uma demonstração:

    python -m src.cli preparar
    python -m src.cli carga --ciclos 12
    python -m src.cli capturar antes --observacao "base com todos os índices"
    python -m src.cli regredir
    python -m src.cli carga --ciclos 12
    python -m src.cli capturar depois --observacao "sem idx_pedido_cliente_data"
    python -m src.cli comparar antes depois

Outros comandos: `capturas` lista o que já foi capturado, `restaurar`
recria os índices.
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.table import Table

from . import banco, carga, config, radar, relatorio
from .relatorio import ROTULO

console = Console()

COR = {
    "grave": "red",
    "regressao": "yellow",
    "nova": "cyan",
    "melhorou": "green",
    "ok": "white",
}


def _quando(instante) -> str:
    """Escreve o instante no fuso de quem está lendo.

    A coluna é `timestamptz`, então o banco guarda o instante certo -- mas o
    container roda em UTC. Formatar lá dentro faria quem capturou às 18h ver
    21h na listagem, e a hora da captura é justamente o que se usa para
    saber qual delas é a mais recente.
    """
    if instante is None:
        return "-"
    return instante.astimezone().strftime("%d/%m %H:%M:%S")


def _br(valor, casas: int = 0) -> str:
    if valor is None:
        return "-"
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


def comando_preparar(args: argparse.Namespace) -> int:
    cfg = config.carregar()
    console.print(f"Conectando em {cfg.destino_legivel()}...")
    banco.esperar_banco(cfg)

    console.print("Criando schema, extensão e histórico...")
    banco.criar_estrutura(cfg)

    console.print(f"Gerando a massa ({_br(cfg.qtd_pedidos)} pedidos)...")
    segundos = banco.carregar_dados(cfg)

    console.print("Criando índices e rodando VACUUM ANALYZE...")
    banco.criar_indices(cfg)

    console.print("Zerando o pg_stat_statements...")
    radar.resetar_estatisticas(cfg)

    tabela = Table(title=f"Base pronta em {_br(segundos, 1)}s")
    tabela.add_column("Tabela")
    tabela.add_column("Linhas", justify="right")
    for nome, quantidade in banco.contar_linhas(cfg).items():
        tabela.add_row(nome, _br(quantidade))
    console.print(tabela)

    console.print("\nPróximo passo: [bold]python -m src.cli carga[/bold]")
    return 0


def comando_carga(args: argparse.Namespace) -> int:
    cfg = config.carregar()
    banco.esperar_banco(cfg)

    console.print(f"Rodando {args.ciclos} ciclos de carga...")
    resultado = carga.executar(cfg, ciclos=args.ciclos, semente=args.semente)

    tabela = Table(
        title=f"{_br(resultado['total'])} chamadas em {_br(resultado['segundos'], 1)}s"
    )
    tabela.add_column("Consulta")
    tabela.add_column("Chamadas", justify="right")
    for nome, quantidade in resultado["chamadas"].items():
        tabela.add_row(nome, _br(quantidade))
    console.print(tabela)
    return 0


def comando_capturar(args: argparse.Namespace) -> int:
    cfg = config.carregar()
    banco.esperar_banco(cfg)

    resultado = radar.capturar(cfg, args.rotulo, args.observacao)
    console.print(
        f"Captura [bold]{resultado['rotulo']}[/bold]: "
        f"{resultado['consultas']} consultas distintas, "
        f"{_br(resultado['chamadas'])} chamadas acumuladas."
    )
    return 0


def comando_capturas(args: argparse.Namespace) -> int:
    cfg = config.carregar()
    banco.esperar_banco(cfg)

    linhas = radar.listar_capturas(cfg)
    if not linhas:
        console.print("Nenhuma captura ainda.")
        return 0

    tabela = Table(title="Capturas")
    for coluna in ("Rótulo", "Quando", "Consultas", "Chamadas", "Observação"):
        tabela.add_column(coluna)
    for linha in linhas:
        tabela.add_row(
            linha["rotulo"],
            _quando(linha["capturado_em"]),
            str(linha["consultas"]),
            _br(linha["chamadas"]),
            linha["observacao"] or "",
        )
    console.print(tabela)
    return 0


def comando_regredir(args: argparse.Namespace) -> int:
    cfg = config.carregar()
    banco.esperar_banco(cfg)

    existia = banco.derrubar_indice(cfg, args.indice)
    if not existia:
        console.print(f"[yellow]O índice {args.indice} já não existia.[/yellow]")
    else:
        console.print(f"Índice [bold]{args.indice}[/bold] removido.")

    console.print("Índices restantes: " + ", ".join(banco.indices_existentes(cfg)))
    console.print(
        "\nAgora rode a carga de novo e capture com outro rótulo para ver o efeito."
    )
    return 0


def comando_restaurar(args: argparse.Namespace) -> int:
    cfg = config.carregar()
    banco.esperar_banco(cfg)
    banco.criar_indices(cfg)
    console.print("Índices recriados: " + ", ".join(banco.indices_existentes(cfg)))
    return 0


def comando_comparar(args: argparse.Namespace) -> int:
    cfg = config.carregar()
    banco.esperar_banco(cfg)

    resultados = radar.comparar(cfg, args.antes, args.depois)
    classificados = [
        (r, r.classificar(args.fator, args.impacto)) for r in resultados
    ]

    mostrar = [
        (r, situacao)
        for r, situacao in classificados
        if args.tudo or situacao != "ok"
    ]

    if not mostrar:
        console.print(
            f"[green]Nenhuma regressão entre '{args.antes}' e '{args.depois}'[/green] "
            f"(limites: {args.fator}x de piora e {args.impacto} ms de impacto)."
        )
    else:
        tabela = Table(title=f"{args.antes} -> {args.depois}")
        tabela.add_column("Situação")
        # Sem no_wrap, uma consulta de 400 caracteres quebra em vinte
        # linhas e a tabela deixa de ser legível no terminal. O texto
        # completo continua no relatório em Markdown.
        tabela.add_column("Consulta", no_wrap=True, max_width=32, overflow="ellipsis")
        for coluna in ("Chamadas", "Antes", "Depois", "Fator", "Impacto"):
            tabela.add_column(coluna, justify="right")

        for r, situacao in mostrar:
            cor = COR[situacao]
            tabela.add_row(
                f"[{cor}]{ROTULO.get(situacao, situacao)}[/{cor}]",
                r.consulta,
                _br(r.chamadas_depois),
                _br(r.media_antes_ms, 2) + " ms" if not r.nova else "-",
                _br(r.media_depois_ms, 2) + " ms",
                _br(r.fator, 2) + "x" if r.fator else "-",
                _tempo(r.impacto_ms),
            )
        console.print(tabela)

    graves = sum(1 for _, s in classificados if s == "grave")
    regressoes = sum(1 for _, s in classificados if s == "regressao")
    console.print(
        f"{len(classificados)} consultas comparadas: "
        f"{graves} {'grave' if graves == 1 else 'graves'}, "
        f"{regressoes} {'regressão' if regressoes == 1 else 'regressões'}."
    )

    if args.relatorio:
        destino = relatorio.salvar(
            relatorio.montar(args.antes, args.depois, classificados, args.fator, args.impacto)
        )
        console.print(f"Relatório em [bold]{destino.relative_to(config.RAIZ)}[/bold]")

    # Código 1 quando há regressão grave: serve como etapa de pipeline.
    return 1 if graves else 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="query-radar",
        description="Deteccao de regressão de performance a partir do pg_stat_statements.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("preparar", help="cria a base, a massa e os índices")
    p.set_defaults(funcao=comando_preparar)

    p = sub.add_parser("carga", help="executa a carga simulada")
    p.add_argument("--ciclos", type=int, default=10)
    p.add_argument("--semente", type=int, default=7)
    p.set_defaults(funcao=comando_carga)

    p = sub.add_parser("capturar", help="grava o estado atual do pg_stat_statements")
    p.add_argument("rotulo")
    p.add_argument("--observacao", help="texto livre, aparece no relatório")
    p.set_defaults(funcao=comando_capturar)

    p = sub.add_parser("capturas", help="lista as capturas já feitas")
    p.set_defaults(funcao=comando_capturas)

    p = sub.add_parser("regredir", help="derruba um índice para simular a regressão")
    p.add_argument("--indice", default=banco.INDICE_ALVO)
    p.set_defaults(funcao=comando_regredir)

    p = sub.add_parser("restaurar", help="recria os índices")
    p.set_defaults(funcao=comando_restaurar)

    p = sub.add_parser("comparar", help="compara duas capturas")
    p.add_argument("antes")
    p.add_argument("depois")
    p.add_argument(
        "--fator",
        type=float,
        default=1.5,
        help="quantas vezes mais lenta para virar regressão (padrão: 1.5)",
    )
    p.add_argument(
        "--impacto",
        type=float,
        default=100.0,
        help="tempo extra mínimo, em ms, para o caso merecer atenção (padrão: 100)",
    )
    p.add_argument("--tudo", action="store_true", help="mostra também o que ficou ok")
    p.add_argument("--relatorio", action="store_true", help="grava um Markdown")
    p.set_defaults(funcao=comando_comparar)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        return args.funcao(args)
    except (RuntimeError, FileNotFoundError) as erro:
        console.print(f"[red]{erro}[/red]")
        return 2


if __name__ == "__main__":
    sys.exit(main())
