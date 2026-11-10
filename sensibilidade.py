"""Sensibilidade v0.3 aos dados reais de SC (Appel 2019, Falani 2022, Justo 2021).

Cada variante altera um parâmetro da tinturaria e reavalia S0, S3 e S4 (Monte Carlo).
A planta de Appel queima cavaco, não gás: por isso o gás é testado em fração.
"""
from __future__ import annotations

import dataclasses
import json
from contextlib import contextmanager

import numpy as np

from . import fontes
from .avaliacao import avaliar


@contextmanager
def _alterar(**kw):
    orig = {k: fontes.IDX[k] for k in kw}
    try:
        for k, val in kw.items():
            val = val if isinstance(val, tuple) else (val, val, val)
            fontes.IDX[k] = dataclasses.replace(orig[k], valor=val[0], lo=val[1], hi=val[2])
        yield
    finally:
        fontes.IDX.update(orig)


VARIANTES = {
    "v0.3 base (Appel: 808 kWh/t)": {},
    "v0.2 eletricidade proxy (1991 kWh/t)": {"eletr_textil": (1991, 1792, 2190)},
    "porte 2 t/dia (Justo)": {"textil_t_dia": 2.0},
    "porte 40,4 t/dia (Appel)": {"textil_t_dia": 40.4},
    "gás -50 % (parte do calor em biomassa)": {"gn_textil": (571.5, 514.5, 628.5)},
    "água 80 L/kg (limite inferior)": {"agua_textil_sc": 80.0},
}


def rodar(n=4000):
    out = {}
    for nome, kw in VARIANTES.items():
        with _alterar(**kw):
            av = avaliar(n)
        c = av["cenarios"]
        k = list(c)
        out[nome] = {
            "sei_s0": c[k[0]]["sei"]["media"],
            "co2_tex_s0": c[k[0]]["co2_tex_kg_t"]["media"],
            "d_co2_tex_s3": c[k[3]]["delta_co2_tex_pct"]["media"],
            "d_co2_tex_s4": c[k[4]]["delta_co2_tex_pct"]["media"],
            "d_agua_s2": c[k[2]]["delta_agua_pct"]["media"],
            "d_energia_s4": c[k[4]]["delta_energia_pct"]["media"],
            "cobertura_bio_s3": c[k[3]]["cobertura_bio"]["media"],
            "cobertura_bio_s4": c[k[4]]["cobertura_bio"]["media"],
        }
    return out


if __name__ == "__main__":
    r = rodar()
    print(json.dumps(r, indent=1, ensure_ascii=False))
