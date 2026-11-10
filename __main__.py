"""CLI do DT2-SC.

  python -m dt2sc avaliar --n 10000 --saida saida/          # Monte Carlo + figuras + JSON
  python -m dt2sc telemetria --dias 14 --saida saida/        # gera JSONL MQTT/OPC UA e CSV
  python -m dt2sc fontes --saida saida/                      # tabela de proveniência (CSV e LaTeX)
"""
from __future__ import annotations

import argparse
import csv
import json

import numpy as np
from pathlib import Path

from . import figuras as F
from . import telemetria as T
from .avaliacao import avaliar, decompor_co2, series
from .economia import avaliar_cavaco, avaliar_economia
from .negociacao import experimento
from .fontes import D, tabela_latex


def main():
    ap = argparse.ArgumentParser(prog="dt2sc")
    sp = ap.add_subparsers(dest="cmd", required=True)
    a = sp.add_parser("avaliar"); a.add_argument("--n", type=int, default=10000); a.add_argument("--saida", default="saida")
    a.add_argument("--figuras")
    t = sp.add_parser("telemetria"); t.add_argument("--dias", type=int, default=14); t.add_argument("--saida", default="saida")
    t.add_argument("--figuras")
    z = sp.add_parser("sensibilidade"); z.add_argument("--n", type=int, default=4000); z.add_argument("--saida", default="saida")
    f = sp.add_parser("fontes"); f.add_argument("--saida", default="saida")
    ac = sp.add_parser("acesso", help="gerenciar empresas e usuários da plataforma fechada")
    ac.add_argument("acao", choices=["criar-empresa", "criar-usuario", "listar"])
    ac.add_argument("--empresa"); ac.add_argument("--nome"); ac.add_argument("--usuario"); ac.add_argument("--papel", default="empresa")
    ac.add_argument("--saida", default="saida")
    e = sp.add_parser("exemplo"); e.add_argument("--dias", type=int, default=14); e.add_argument("--saida", default="saida")
    pl = sp.add_parser("planta", help="diagnóstico e calibração com CSV real da planta")
    pl.add_argument("csv"); pl.add_argument("--saida", default="saida")
    pl.add_argument("--mapa", help="JSON {coluna_padrão: coluna_do_arquivo}")
    pl.add_argument("--fator", help="JSON {coluna_padrão: multiplicador} (ex.: {\"eletrica_kw\": 0.001} para W)")
    pl.add_argument("--n", type=int, default=3000)
    pl.add_argument("--tarifa-gas", type=float, help="R$/m3 pago pela planta (padrão: paridade Argus)")
    pl.add_argument("--cavaco-r-t", type=float, help="R$/t do cavaco local")
    pl.add_argument("--gate-fee", type=float, help="R$/t de destinação pago hoje pelo frigorífico")
    args = ap.parse_args()
    pasta = Path(args.saida); pasta.mkdir(parents=True, exist_ok=True)

    if args.cmd == "fontes":
        with open(pasta / "fontes.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(["chave", "valor", "unidade", "lo", "hi", "tipo", "fonte", "ano", "ref"])
            for d in D:
                w.writerow([d.chave, d.valor, d.unidade, d.lo, d.hi, d.tipo, d.fonte, d.ano, d.ref])
        tabela_latex(pasta / "tabela_fontes.tex")
        print(f"{len(D)} parâmetros: R={sum(d.tipo == 'R' for d in D)} L={sum(d.tipo == 'L' for d in D)} "
              f"H={sum(d.tipo == 'H' for d in D)}")
    elif args.cmd == "acesso":
        import getpass
        from .acesso import Plataforma
        pl_ = Plataforma()
        if args.acao == "criar-empresa":
            pl_.criar_empresa(args.empresa, args.nome or args.empresa, "cli"); print("empresa criada")
        elif args.acao == "criar-usuario":
            pl_.criar_usuario(args.usuario, getpass.getpass("Senha: "), args.empresa, args.papel, "cli"); print("usuário criado")
        else:
            print(json.dumps({"empresas": pl_.empresas(), "usuarios": {k: {x: y for x, y in v.items() if x != "hash"}
                                                                        for k, v in pl_.usuarios().items()}}, indent=1, ensure_ascii=False))
    elif args.cmd == "exemplo":
        from .planta import exemplo_csv
        exemplo_csv(pasta / "exemplo_planta.csv", args.dias)
        print(f"gerado {pasta / 'exemplo_planta.csv'}")
    elif args.cmd == "planta":
        from . import planta as P
        df = P.carregar(args.csv, json.loads(args.mapa) if args.mapa else None,
                        json.loads(args.fator) if args.fator else None)
        qual = P.qualidade(df); cal = P.calibrar(df); anom = P.anomalias(df)
        res = P.avaliar_planta(cal, args.n, args.tarifa_gas, args.cavaco_r_t, args.gate_fee)
        rel = P.relatorio_md(cal, res, anom, qual)
        (pasta / "planta_relatorio.md").write_text(rel, encoding="utf-8")
        anom.to_csv(pasta / "planta_anomalias.csv", index=False)
        (pasta / "planta_resultados.json").write_text(json.dumps({"qualidade": qual, "calibracao": {
            k: list(x) for k, x in cal["parametros"].items()}, "resultados": res}, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        print(rel)
    elif args.cmd == "sensibilidade":
        from .sensibilidade import rodar
        r = rodar(args.n)
        (pasta / "sensibilidade_v03.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(r, indent=1, ensure_ascii=False))
    elif args.cmd == "telemetria":
        tt, s = T.gerar(args.dias)
        T.exportar(tt, s, pasta)
        F.fig_telemetria(tt, s, args.figuras or pasta / "figuras")
        print(json.dumps({"alarmes": T.alarmes(s), "calibracao": T.verificar_calibracao(s)}, indent=2, default=float))
    else:
        av = avaliar(args.n)
        figs = args.figuras or pasta / "figuras"
        F.fig_cenarios(av, figs)
        F.fig_co2(decompor_co2(av), figs)
        F.fig_controle(series(av), figs)
        F.fig_escala(av, figs)
        ec = avaliar_economia(args.n)
        F.fig_economia(ec, figs)
        neg = experimento(min(args.n, 5000))
        F.fig_negociacao(neg, figs)
        q = lambda x: {"media": float(np.mean(x)), "p5": float(np.percentile(x, 5)), "p95": float(np.percentile(x, 95))}
        saida_ec = {"p_eq_sem_gate": q(ec["p_equilibrio_sem_gate"]), "p_eq_com_gate": q(ec["p_equilibrio_com_gate"]),
                    "tarifa_gn": q(ec["amostras"]["tarifa_gn"]),
                    "prob_competitivo_sem_gate": float(np.mean(ec["p_equilibrio_sem_gate"] <= ec["amostras"]["tarifa_gn"])),
                    "prob_competitivo_com_gate": float(np.mean(ec["p_equilibrio_com_gate"] <= ec["amostras"]["tarifa_gn"])),
                    "c_eq_sem_gate": q(ec["c_equilibrio_sem_gate"]), "tarifa_eletr_media": ec["tarifa_eletr_media"],
                    "vpl_sistema_mi": {str(c): q(x / 1e6) for c, x in ec["vpl_sistema"].items()},
                    "prob_vpl_pos": {str(c): float(np.mean(x > 0)) for c, x in ec["vpl_sistema"].items()}}
        saida = {k: v for k, v in av.items() if not k.startswith("_")}
        saida["decomposicao_co2"] = decompor_co2(av)
        saida["economia"] = saida_ec
        saida["negociacao"] = neg
        saida["cavaco"] = {k: v for k, v in avaliar_cavaco(args.n).items() if k != "c_mix"}
        (pasta / "resultados.json").write_text(json.dumps(saida, indent=2, ensure_ascii=False), encoding="utf-8")
        for nome, r in av["cenarios"].items():
            print(f"{nome:34s} SEI={r['sei']['media']:.3f}  CO2tex={r['co2_tex_kg_t']['media']:7.0f} kg/t  "
                  f"agua={r['agua_tex_m3_t']['media']:6.1f} m3/t  circ={r['circ_agro']['media']:.3f}  "
                  f"bio={100 * r['cobertura_bio']['media']:5.1f}%  dias<SP={r['dias_abaixo_sp']['media']:5.1f}")


if __name__ == "__main__":
    main()
