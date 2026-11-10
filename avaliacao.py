"""Avaliação de cenários: Monte Carlo (N=10.000), SEI federado, escala estadual."""
from __future__ import annotations

import numpy as np

from .federacao import Politica, amostrar, calibrar_maximos, escala_estadual, simular

CENARIOS = [
    Politica("S0 Silos (baseline)", "base"),
    Politica("S1 DT2 open loop", "aberta", u1=0.8, u2=0.30, u3=0.25),
    Politica("S2 DT2 closed loop (PI)", "pid"),
    Politica("S3 Closed loop + biomethane hub", "pid", hub=True),
    Politica("S4 Closed loop + negotiated contract", "pid", hub=True, hub_m3=10287.0),
]


def resumo(x):
    x = np.asarray(x)
    return {"media": float(x.mean()), "p5": float(np.percentile(x, 5)), "p95": float(np.percentile(x, 95))}


DELTA_SP = 0.17   # meta: elevar o SEI de cada planta em 0,17 acima da sua própria linha de base


def avaliar(n=10000, semente=42, cenarios=CENARIOS):
    p = amostrar(n, semente)
    mx = calibrar_maximos(p)
    res, brutos = {}, {}
    sp_ref = None
    for pol in cenarios:
        o = simular(pol, p, mx, sp_ref=sp_ref)
        if sp_ref is None:
            sp_ref = o["sei"] + DELTA_SP
        brutos[pol.nome] = o
        res[pol.nome] = {k: resumo(v) for k, v in o.items() if not k.startswith("_")}
    base = brutos[cenarios[0].nome]
    for pol in cenarios[1:]:
        o = brutos[pol.nome]
        res[pol.nome]["p_co2_menor"] = float(np.mean(o["co2_total_t_ano"] < base["co2_total_t_ano"]))
        res[pol.nome]["delta_co2_pct"] = resumo(100 * (o["co2_total_t_ano"] / base["co2_total_t_ano"] - 1))
        res[pol.nome]["delta_co2_tex_pct"] = resumo(100 * (o["co2_tex_kg_t"] / base["co2_tex_kg_t"] - 1))
        res[pol.nome]["delta_agua_pct"] = resumo(100 * (o["agua_tex_m3_t"] / base["agua_tex_m3_t"] - 1))
        res[pol.nome]["delta_energia_pct"] = resumo(100 * (o["energia_kwh_t"] / base["energia_kwh_t"] - 1))
    est = {k: resumo(v) for k, v in escala_estadual(p).items()}
    return {"cenarios": res, "maximos": {k: float(v) for k, v in mx.items()}, "estadual": est,
            "n": n, "_p": p, "_mx": mx, "_brutos": brutos}


def series(av, n=2000):
    """Séries diárias (mediana e P5-P95) para figura do controle em malha fechada."""
    p = amostrar(n, 42)
    out, sp_ref = {}, None
    for pol in CENARIOS:
        o = simular(pol, p, av["_mx"], guardar_serie=True, sp_ref=sp_ref)
        if sp_ref is None:
            sp_ref = o["sei"] + DELTA_SP
        out[pol.nome] = o["_serie"]
    return out


def decompor_co2(av):
    """Decomposição do CO2e da tinturaria (kg/t) por fonte, para S0 e S3 (médias)."""
    from .federacao import EF_GN_KG_M3
    from .fontes import v
    p = av["_p"]
    out = {}
    for nome in (CENARIOS[0].nome, CENARIOS[3].nome, CENARIOS[4].nome):
        b = av["_brutos"][nome]
        gn = float(np.mean(b["gn_fossil_m3_t"] * EF_GN_KG_M3))
        tot = float(np.mean(b["co2_tex_kg_t"]))
        eletr = float(np.mean(p["eletr_tex"] * p["ef_grid"] / 1000))
        out[nome] = {"gas": gn, "electricity": eletr, "fibre": tot - gn - eletr}
    return out
