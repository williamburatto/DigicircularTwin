"""Gerador de telemetria sintética calibrada (OPC UA NodeIds + tópicos MQTT Sparkplug-B).

Os telemetras reais de chão de fábrica são protegidos por sigilo industrial. Aqui as
médias e limites vêm de dados públicos (fontes.py) e a variabilidade é estocástica:
perfil de turno, ruído AR(1), deriva de sensor, outliers e dados faltantes.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .federacao import KWH_POR_M3_GN
from .fontes import v

PONTOS = {
    # nó, ativo, variável, unidade, NodeId OPC UA
    "agro": [("abate", "suinos_h", "cab/h", "ns=2;s=Oeste.Abate.Contador"),
             ("utilidades", "agua_m3_h", "m3/h", "ns=2;s=Oeste.Utilidades.FT101"),
             ("ete", "temp_efluente_c", "°C", "ns=2;s=Oeste.ETE.TT201"),
             ("ete", "og_mg_l", "mg/L", "ns=2;s=Oeste.ETE.AIT202"),
             ("ete", "ph", "-", "ns=2;s=Oeste.ETE.AIT203"),
             ("flotador", "gordura_kg_h", "kg/h", "ns=2;s=Oeste.ETE.Flotador.WT301")],
    "textil": [("tinturaria", "producao_kg_h", "kg/h", "ns=3;s=Vale.Tinturaria.WT100"),
               ("utilidades", "eletrica_kw", "kW", "ns=3;s=Vale.Utilidades.JT110"),
               ("caldeira", "gn_m3_h", "Nm3/h", "ns=3;s=Vale.Caldeira.FT120"),
               ("tinturaria", "agua_m3_h", "m3/h", "ns=3;s=Vale.Tinturaria.FT130"),
               ("ete", "temp_efluente_c", "°C", "ns=3;s=Vale.ETE.TT140"),
               ("ete", "ph", "-", "ns=3;s=Vale.ETE.AIT141")],
}


def _ar1(rng, n, phi=0.85, sigma=0.05):
    x = np.zeros(n)
    e = rng.normal(0, sigma * np.sqrt(1 - phi ** 2), n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


def _turno(horas):
    """Perfil de produção: 3 turnos seg-sáb, domingo parado, troca de turno às 6/14/22 h."""
    h = horas % 24
    dia = (horas // 24) % 7
    base = np.where(dia == 6, 0.0, 1.0)
    vale = 1 - 0.35 * (np.isin(h, [6, 14, 22]))
    return base * vale


def gerar(dias=14, semente=11, inicio=datetime(2026, 3, 2)):
    rng = np.random.default_rng(semente)
    n = dias * 24
    horas = np.arange(n)
    perfil = _turno(horas)
    fator_op = 7 / 6                                  # produção concentrada em 6 dias
    s = {}
    # agro
    suinos_h = v("planta_ref_suinos_dia") / 24 * fator_op * perfil * (1 + _ar1(rng, n))
    s["agro.abate.suinos_h"] = suinos_h
    s["agro.utilidades.agua_m3_h"] = suinos_h * v("agua_por_suino") / 1000 * (1 + _ar1(rng, n, sigma=0.04)) + 2.0
    s["agro.ete.temp_efluente_c"] = 31 + 4 * perfil + _ar1(rng, n, 0.95, 0.5) * 4
    s["agro.ete.og_mg_l"] = np.clip(28 + 10 * perfil + _ar1(rng, n, 0.9, 0.35) * 20, 2, None)
    s["agro.ete.ph"] = 7.2 + _ar1(rng, n, 0.9, 0.06) * 6
    s["agro.flotador.gordura_kg_h"] = suinos_h * v("gordura_por_suino") * (1 + _ar1(rng, n, sigma=0.08))
    # têxtil
    prod = v("textil_t_dia") * 1000 / 24 * fator_op * perfil * (1 + _ar1(rng, n, sigma=0.06))
    s["textil.tinturaria.producao_kg_h"] = prod
    s["textil.utilidades.eletrica_kw"] = prod * v("eletr_textil") / 1000 * (1 + _ar1(rng, n, sigma=0.04)) + 25
    s["textil.caldeira.gn_m3_h"] = prod * v("gn_textil") / 1000 * (1 + _ar1(rng, n, sigma=0.07))
    s["textil.tinturaria.agua_m3_h"] = prod * v("agua_textil_sc") / 1000 * (1 + _ar1(rng, n, sigma=0.08))
    s["textil.ete.temp_efluente_c"] = 32 + 4 * perfil + _ar1(rng, n, 0.95, 0.5) * 4
    s["textil.ete.ph"] = 8.3 + _ar1(rng, n, 0.9, 0.06) * 8
    # falhas de sensor: 0,5 % outliers, 1 % faltantes, deriva lenta no pH têxtil
    for k in s:
        x = s[k]
        out = rng.random(n) < 0.005
        x[out] = x[out] * rng.choice([0.0, 3.0], out.sum())
        miss = rng.random(n) < 0.01
        x[miss] = np.nan
    s["textil.ete.ph"] += np.linspace(0, 0.4, n)
    t = [inicio + timedelta(hours=int(i)) for i in horas]
    return t, s


def limites():
    return {"temp_efluente_c": (None, v("lim_temp_efluente")), "og_mg_l": (None, v("lim_og_animal")),
            "ph": (v("lim_ph_min"), v("lim_ph_max"))}


def alarmes(s):
    lim = limites()
    res = {}
    for k, x in s.items():
        var = k.split(".")[-1]
        if var in lim:
            lo, hi = lim[var]
            viol = np.zeros_like(x, dtype=bool)
            if lo is not None:
                viol |= x < lo
            if hi is not None:
                viol |= x > hi
            res[k] = int(np.nansum(viol))
    return res


def exportar(t, s, pasta):
    pasta = Path(pasta); pasta.mkdir(parents=True, exist_ok=True)
    node_ids = {f"{no}.{a}.{var}": nid for no, lst in PONTOS.items() for a, var, _, nid in lst}
    with open(pasta / "telemetria_mqtt.jsonl", "w", encoding="utf-8") as f:
        for i, ts in enumerate(t):
            for k, x in s.items():
                no, ativo, var = k.split(".")
                val = None if np.isnan(x[i]) else round(float(x[i]), 3)
                f.write(json.dumps({"topic": f"spBv1.0/DT2SC/DDATA/{no}/{ativo}", "timestamp": ts.isoformat(),
                                    "metric": var, "value": val, "nodeId": node_ids[k],
                                    "quality": "Good" if val is not None else "Bad_NoCommunication"},
                                   ensure_ascii=False) + "\n")
    with open(pasta / "telemetria.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp"] + list(s))
        for i, ts in enumerate(t):
            w.writerow([ts.isoformat()] + ["" if np.isnan(s[k][i]) else round(float(s[k][i]), 3) for k in s])


def verificar_calibracao(s):
    """Compara as médias da série com as intensidades públicas (fecha o laço de calibração)."""
    prod = np.nansum(s["textil.tinturaria.producao_kg_h"]) / 1000
    suinos = np.nansum(s["agro.abate.suinos_h"])
    return {
        "eletr_kwh_t": np.nansum(s["textil.utilidades.eletrica_kw"]) / prod,
        "gn_m3_t": np.nansum(s["textil.caldeira.gn_m3_h"]) / prod,
        "energia_kwh_t": (np.nansum(s["textil.utilidades.eletrica_kw"])
                          + np.nansum(s["textil.caldeira.gn_m3_h"]) * KWH_POR_M3_GN) / prod,
        "agua_l_suino": np.nansum(s["agro.utilidades.agua_m3_h"]) * 1000 / suinos,
        "gordura_kg_suino": np.nansum(s["agro.flotador.gordura_kg_h"]) / suinos,
    }
