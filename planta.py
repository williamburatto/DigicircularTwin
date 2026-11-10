"""Modo planta: carrega dados reais de uma tinturaria (CSV de SCADA/historiador/MQTT), mede KPIs,
detecta anomalias, calibra o gêmeo com a própria planta e reavalia cenários e economia.

Nada sai da máquina: roda local (notebook, Streamlit ou linha de comando) e usa só numpy/pandas.

Colunas padrão (taxas instantâneas; o intervalo vem dos timestamps):
  timestamp, producao_kg_h, eletrica_kw, gn_m3_h, agua_m3_h, cavaco_kg_h, vapor_kg_h, temp_efluente_c, ph
Só timestamp, producao_kg_h e eletrica_kw são obrigatórias.
"""
from __future__ import annotations

import dataclasses
from contextlib import contextmanager

import numpy as np
import pandas as pd

from . import fontes
from .avaliacao import avaliar
from .economia import avaliar_economia, custo_cavaco_m3eq
from .federacao import EF_GN_KG_M3, KWH_POR_M3_GN, Politica
from .fontes import v

COLUNAS = ["timestamp", "producao_kg_h", "eletrica_kw", "gn_m3_h", "agua_m3_h", "cavaco_kg_h",
           "vapor_kg_h", "temp_efluente_c", "ph"]
OBRIGATORIAS = ["timestamp", "producao_kg_h", "eletrica_kw"]
ALIASES = {
    "timestamp": ["timestamp", "data_hora", "datahora", "datetime", "time", "date", "ts"],
    "producao_kg_h": ["producao_kg_h", "producao", "production_kg_h", "kg_h", "textil.tinturaria.producao_kg_h"],
    "eletrica_kw": ["eletrica_kw", "potencia_kw", "power_kw", "kw", "textil.utilidades.eletrica_kw"],
    "gn_m3_h": ["gn_m3_h", "gas_m3_h", "gas_nm3_h", "textil.caldeira.gn_m3_h"],
    "agua_m3_h": ["agua_m3_h", "water_m3_h", "textil.tinturaria.agua_m3_h"],
    "cavaco_kg_h": ["cavaco_kg_h", "chips_kg_h", "biomassa_kg_h"],
    "vapor_kg_h": ["vapor_kg_h", "steam_kg_h"],
    "temp_efluente_c": ["temp_efluente_c", "temp_efluente", "textil.ete.temp_efluente_c"],
    "ph": ["ph", "ph_efluente", "textil.ete.ph"],
}


def detectar_mapa(colunas):
    """Sugere {coluna_padrão: coluna_do_arquivo} por nome (sem diferenciar maiúsculas)."""
    baixo = {c.lower().strip(): c for c in colunas}
    return {p: next((baixo[a] for a in nomes if a in baixo), None) for p, nomes in ALIASES.items()}


def carregar(origem, mapa=None, fator=None):
    """Lê CSV (caminho, buffer ou DataFrame) e devolve DataFrame padronizado.

    mapa  : {coluna_padrão: coluna_do_arquivo}; se None, detecta pelos nomes.
    fator : {coluna_padrão: multiplicador} para converter unidades (ex.: {'eletrica_kw': 0.001} se vier em W).
    """
    df = origem.copy() if isinstance(origem, pd.DataFrame) else pd.read_csv(origem, sep=None, engine="python")
    mapa = {k: x for k, x in (mapa or detectar_mapa(df.columns)).items() if x}
    faltam = [c for c in OBRIGATORIAS if c not in mapa or mapa[c] not in df.columns]
    if faltam:
        raise ValueError(f"colunas obrigatórias ausentes ou não mapeadas: {faltam}. Colunas do arquivo: {list(df.columns)}")
    out = pd.DataFrame({p: df[c] for p, c in mapa.items() if c in df.columns})
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    for c in out.columns.drop("timestamp"):
        out[c] = pd.to_numeric(out[c], errors="coerce") * (fator or {}).get(c, 1.0)
    out = out.dropna(subset=["timestamp"]).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    for c in COLUNAS:
        if c not in out:
            out[c] = np.nan
    passo = out["timestamp"].diff().dt.total_seconds().div(3600)
    mediana = float(passo.median()) if passo.notna().any() else 1.0
    # lacunas maiores que 3 passos viram "sem dado" (não são integradas)
    out["dt_h"] = passo.shift(-1).fillna(mediana).where(lambda s: s <= 3 * mediana, 0.0)
    return out[COLUNAS + ["dt_h"]]


def qualidade(df):
    """Qualidade dos dados: cobertura, faltantes, valores negativos, lacunas e horas de produção."""
    n = len(df)
    res = {"linhas": n, "inicio": str(df["timestamp"].min()), "fim": str(df["timestamp"].max()),
           "dias": float((df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 86400),
           "passo_min": float(df["dt_h"][df["dt_h"] > 0].median() * 60) if n else float("nan"),
           "lacunas": int((df["dt_h"] == 0).sum()), "por_coluna": {}}
    for c in COLUNAS[1:]:
        s = df[c]
        res["por_coluna"][c] = {"presente": bool(s.notna().any()), "faltantes_pct": float(100 * s.isna().mean()),
                                "negativos": int((s < 0).sum())}
    prod = df["producao_kg_h"]
    res["horas_producao"] = float(df.loc[prod > _limiar(prod), "dt_h"].sum())
    return res


def _limiar(prod):
    pos = prod[prod > 0]
    return 0.05 * float(pos.median()) if len(pos) else 0.0


def _integrar(df):
    d = df.copy()
    ativo = d["producao_kg_h"] > _limiar(d["producao_kg_h"])
    d["ativo"] = ativo
    d["dia"] = d["timestamp"].dt.floor("D")
    d["t"] = d["producao_kg_h"].clip(lower=0) * d["dt_h"] / 1000.0
    d["kwh"] = d["eletrica_kw"].clip(lower=0) * d["dt_h"]
    d["gn"] = d["gn_m3_h"].clip(lower=0) * d["dt_h"]
    d["agua"] = d["agua_m3_h"].clip(lower=0) * d["dt_h"]
    d["cav"] = d["cavaco_kg_h"].clip(lower=0) * d["dt_h"]
    d["vap"] = d["vapor_kg_h"].clip(lower=0) * d["dt_h"]
    return d


def kpis(df, ef_grid=None):
    """Totais e intensidades da planta (por tonelada processada) e CO2e (rede SIN + gás natural)."""
    d = _integrar(df)
    ef = v("ef_sin_2023") if ef_grid is None else ef_grid
    t = float(d["t"].sum())
    if t <= 0:
        raise ValueError("produção total zero: verifique a coluna de produção e as unidades (kg/h)")
    r = {"producao_t": t, "eletr_kwh_t": float(d["kwh"].sum() / t)}
    gas = float(d["gn"].sum()) if d["gn_m3_h"].notna().any() else 0.0
    cav_kg = float(d["cav"].sum()) if d["cavaco_kg_h"].notna().any() else 0.0
    r["gn_m3_t"] = gas / t
    r["cavaco_kg_t"] = cav_kg / t
    r["agua_m3_t"] = float(d["agua"].sum() / t) if d["agua_m3_h"].notna().any() else float("nan")
    r["vapor_kg_t"] = float(d["vap"].sum() / t) if d["vapor_kg_h"].notna().any() else float("nan")
    r["energia_kwh_t"] = r["eletr_kwh_t"] + r["gn_m3_t"] * KWH_POR_M3_GN
    r["co2e_gas_kg_t"] = r["gn_m3_t"] * EF_GN_KG_M3
    r["co2e_eletr_kg_t"] = r["eletr_kwh_t"] * ef / 1000.0
    r["co2e_energia_kg_t"] = r["co2e_gas_kg_t"] + r["co2e_eletr_kg_t"]     # sem fibra e sem cavaco (biogênico = 0)
    r["combustivel"] = ("misto" if gas > 0 and cav_kg > 0 else "gás natural" if gas > 0
                        else "cavaco" if cav_kg > 0 else "não informado")
    return r


def intensidades_diarias(df):
    d = _integrar(df)
    g = d[d["ativo"]].groupby("dia").agg(t=("t", "sum"), kwh=("kwh", "sum"), gn=("gn", "sum"),
                                         agua=("agua", "sum"), cav=("cav", "sum"))
    g = g[g["t"] >= 0.5]
    out = pd.DataFrame({"t_dia": g["t"], "eletr_kwh_t": g["kwh"] / g["t"], "gn_m3_t": g["gn"] / g["t"],
                        "agua_m3_t": g["agua"] / g["t"], "cavaco_kg_t": g["cav"] / g["t"]})
    return out.replace(0, np.nan)


def anomalias(df, janela_dias=7, limite_z=4.0):
    """Eventos: consumo específico (kWh/t) fora do padrão (z robusto, mediana/MAD) e limites de efluente."""
    d = _integrar(df)
    ativo = d["ativo"] & (d["t"] > 0)
    esp = (d["kwh"] / d["t"]).where(ativo)
    jan = max(int(janela_dias * 24 / max(d["dt_h"][d["dt_h"] > 0].median(), 1e-6)), 24)
    med = esp.rolling(jan, min_periods=24, center=True).median()
    mad = (esp - med).abs().rolling(jan, min_periods=24, center=True).median()
    z = 0.6745 * (esp - med) / mad.replace(0, np.nan)
    eventos = []
    for i in d.index[(z.abs() > limite_z).fillna(False)]:
        eventos.append({"timestamp": d.at[i, "timestamp"], "tipo": "consumo específico", "valor": float(esp[i]),
                        "z": float(z[i])})
    lim = {"temp_efluente_c": (None, v("lim_temp_efluente")), "ph": (v("lim_ph_min"), v("lim_ph_max"))}
    for c, (lo, hi) in lim.items():
        s = d[c]
        viol = pd.Series(False, index=d.index)
        if lo is not None:
            viol |= s < lo
        if hi is not None:
            viol |= s > hi
        for i in d.index[viol.fillna(False)]:
            eventos.append({"timestamp": d.at[i, "timestamp"], "tipo": f"limite CONAMA 430: {c}", "valor": float(s[i]), "z": np.nan})
    return pd.DataFrame(eventos, columns=["timestamp", "tipo", "valor", "z"]).sort_values("timestamp").reset_index(drop=True)


def _faixa(x, central, minimo_dias=5, rel=0.15):
    x = x.dropna()
    if len(x) >= minimo_dias:
        lo, hi = float(np.percentile(x, 5)), float(np.percentile(x, 95))
        lo, hi = min(lo, central), max(hi, central)
        return lo, hi, False
    return central * (1 - rel), central * (1 + rel), True       # poucos dias: faixa ±15 % (hipótese)


def calibrar(df):
    """Parâmetros do gêmeo estimados da própria planta (valor, lo, hi) + avisos."""
    k = kpis(df)
    dia = intensidades_diarias(df)
    avisos = []
    if len(dia) < 5:
        avisos.append(f"apenas {len(dia)} dia(s) de produção: faixas de incerteza assumidas em ±15 %")
    cal = {}
    lo, hi, _ = _faixa(dia["eletr_kwh_t"], k["eletr_kwh_t"])
    cal["eletr_textil"] = (k["eletr_kwh_t"], lo, hi)
    if k["gn_m3_t"] > 0:
        lo, hi, _ = _faixa(dia["gn_m3_t"], k["gn_m3_t"])
        cal["gn_textil"] = (k["gn_m3_t"], lo, hi)
    if not np.isnan(k["agua_m3_t"]):
        lo, hi, _ = _faixa(dia["agua_m3_t"], k["agua_m3_t"])
        cal["agua_textil_sc"] = (k["agua_m3_t"], lo, hi)
        cal["agua_textil_br"] = (lo, lo, lo)
        cal["agua_textil_ue"] = (hi, hi, hi)
    t_dia = float(dia["t_dia"].mean()) if len(dia) else k["producao_t"]
    cal["textil_t_dia"] = (t_dia, float(dia["t_dia"].min()) if len(dia) else t_dia, float(dia["t_dia"].max()) if len(dia) else t_dia)
    if len(dia) >= 7:
        dias_ano = float(min(365, len(dia) / max(1, (df["timestamp"].max() - df["timestamp"].min()).days + 1) * 365))
        cal["dias_operacao"] = (dias_ano, dias_ano * 0.97, min(365.0, dias_ano * 1.03))
    else:
        avisos.append("menos de 7 dias de dados: dias de operação por ano mantidos em 300 (hipótese)")
    if k["combustivel"] == "cavaco":
        avisos.append("planta a cavaco: cenários de biometano (S3/S4) não se aplicam; gás natural = 0")
    return {"parametros": cal, "kpis": k, "avisos": avisos, "dias_validos": int(len(dia))}


def calibrar_manual(eletr_kwh_t, gn_m3_t, agua_m3_t, t_dia, dias_ano=300, cavaco_kg_t=0.0, incerteza=0.15):
    """Calibração a partir de valores informados à mão (sem série temporal). Faixa = valor +- incerteza."""
    if eletr_kwh_t <= 0 or t_dia <= 0:
        raise ValueError("informe eletricidade (kWh/t) e produção (t/dia) maiores que zero")
    f = lambda x: (x, x * (1 - incerteza), x * (1 + incerteza))
    par = {"eletr_textil": f(eletr_kwh_t), "textil_t_dia": f(t_dia),
           "dias_operacao": (dias_ano, dias_ano * 0.97, min(365.0, dias_ano * 1.03))}
    if gn_m3_t > 0:
        par["gn_textil"] = f(gn_m3_t)
    if agua_m3_t > 0:
        par["agua_textil_sc"] = f(agua_m3_t)
        par["agua_textil_br"] = (agua_m3_t * (1 - incerteza),) * 3
        par["agua_textil_ue"] = (agua_m3_t * (1 + incerteza),) * 3
    ef = v("ef_sin_2023")
    k = {"producao_t": t_dia * dias_ano, "eletr_kwh_t": float(eletr_kwh_t), "gn_m3_t": float(gn_m3_t),
         "cavaco_kg_t": float(cavaco_kg_t), "agua_m3_t": float(agua_m3_t) if agua_m3_t > 0 else float("nan"),
         "vapor_kg_t": float("nan")}
    k["energia_kwh_t"] = eletr_kwh_t + gn_m3_t * KWH_POR_M3_GN
    k["co2e_gas_kg_t"] = gn_m3_t * EF_GN_KG_M3
    k["co2e_eletr_kg_t"] = eletr_kwh_t * ef / 1000.0
    k["co2e_energia_kg_t"] = k["co2e_gas_kg_t"] + k["co2e_eletr_kg_t"]
    k["combustivel"] = ("misto" if gn_m3_t > 0 and cavaco_kg_t > 0 else "gás natural" if gn_m3_t > 0
                        else "cavaco" if cavaco_kg_t > 0 else "não informado")
    avisos = [f"valores informados manualmente: faixa de incerteza assumida em ±{incerteza:.0%}"]
    if k["combustivel"] == "cavaco":
        avisos.append("planta a cavaco: cenários de biometano (S3/S4) não se aplicam; gás natural = 0")
    return {"parametros": par, "kpis": k, "avisos": avisos, "dias_validos": 0}


@contextmanager
def aplicar(cal):
    """Sobrepõe temporariamente parâmetros do registro com os calibrados da planta."""
    orig = {}
    try:
        for k, (val, lo, hi) in cal["parametros"].items():
            orig[k] = fontes.IDX[k]
            fontes.IDX[k] = dataclasses.replace(orig[k], valor=val, lo=min(lo, val), hi=max(hi, val), tipo="R",
                                                 fonte="Dados da planta (medidos)")
        yield
    finally:
        fontes.IDX.update(orig)


def avaliar_planta(cal, n=3000, tarifa_gas=None, preco_cavaco_r_t=None, gate_fee=None):
    """Cenários S0-S4 e economia com os parâmetros da planta.

    tarifa_gas        : R$/m3 pago pelo gás (padrão: paridade Argus). Substitui a referência do biometano.
    preco_cavaco_r_t  : R$/t do cavaco da região; calcula o custo por m3 de gás equivalente.
    gate_fee          : R$/t de destinação pago hoje pelo frigorífico parceiro (padrão: referência pública).
    """
    k = cal["kpis"]
    a_gas = k["gn_m3_t"] > 0
    extra = {}
    if tarifa_gas:
        extra["tarifa_gn_ind"] = (tarifa_gas, tarifa_gas * 0.97, tarifa_gas * 1.03)
    if gate_fee:
        extra["gate_fee_ref"] = (gate_fee, gate_fee * 0.8, gate_fee * 1.0)
    cal2 = {"parametros": {**cal["parametros"], **extra}}
    with aplicar(cal2):
        demanda_gas = v("gn_textil") * v("textil_t_dia") if a_gas else 0.0
        cen = [Politica("S0 Silos (baseline)", "base"),
               Politica("S1 DT2 open loop", "aberta", u1=0.8, u2=0.30, u3=0.25),
               Politica("S2 DT2 closed loop (PI)", "pid")]
        if a_gas:
            cen += [Politica("S3 Closed loop + biomethane hub", "pid", hub=True),
                    Politica("S4 Closed loop + negotiated contract", "pid", hub=True, hub_m3=0.9 * demanda_gas)]
        av = avaliar(n, cenarios=cen)
        res = {"kpis": k, "avisos": cal["avisos"], "demanda_gas_m3_dia": demanda_gas, "cenarios": av["cenarios"]}
        if a_gas:
            ec = avaliar_economia(n)
            tg = ec["amostras"]["tarifa_gn"]
            q = lambda x: {"media": float(np.mean(x)), "p5": float(np.percentile(x, 5)), "p95": float(np.percentile(x, 95))}
            res["economia"] = {"paridade_ou_tarifa": q(tg), "p_equilibrio_sem_gate": q(ec["p_equilibrio_sem_gate"]),
                               "p_equilibrio_com_gate": q(ec["p_equilibrio_com_gate"]),
                               "prob_competitivo_sem_gate": float(np.mean(ec["p_equilibrio_sem_gate"] <= tg)),
                               "prob_competitivo_com_gate": float(np.mean(ec["p_equilibrio_com_gate"] <= tg)),
                               "vpl_hub_mi": q(ec["vpl_sistema"][0] / 1e6)}
            if preco_cavaco_r_t:
                c = custo_cavaco_m3eq(preco_cavaco_r_t, "t", v("cavaco_pci"), v("cavaco_densidade"),
                                      v("eficiencia_caldeira_cavaco"), v("eficiencia_caldeira_gas"))
                res["economia"]["cavaco_r_m3eq"] = float(c)
                res["economia"]["prob_biometano_menor_que_cavaco_sem_gate"] = float(np.mean(ec["p_equilibrio_sem_gate"] <= c))
                res["economia"]["prob_biometano_menor_que_cavaco_com_gate"] = float(np.mean(ec["p_equilibrio_com_gate"] <= c))
        elif preco_cavaco_r_t:
            res["economia"] = {"cavaco_r_m3eq": float(custo_cavaco_m3eq(
                preco_cavaco_r_t, "t", v("cavaco_pci"), v("cavaco_densidade"),
                v("eficiencia_caldeira_cavaco"), v("eficiencia_caldeira_gas")))}
    return res


def relatorio_md(cal, res, anom=None, qual=None):
    """Relatório curto em Markdown para a gerência da planta."""
    k = res["kpis"]
    L = ["# DT2-SC - diagnóstico da planta", ""]
    if qual:
        L += [f"- Período: {qual['inicio']} a {qual['fim']} ({qual['dias']:.1f} dias), passo {qual['passo_min']:.0f} min, "
              f"{qual['lacunas']} lacunas, {qual['horas_producao']:.0f} h de produção", ""]
    L += ["## Intensidades medidas", f"- Produção: {k['producao_t']:.1f} t",
          f"- Eletricidade: {k['eletr_kwh_t']:.0f} kWh/t", f"- Gás natural: {k['gn_m3_t']:.0f} m3/t",
          f"- Cavaco: {k['cavaco_kg_t']:.0f} kg/t", f"- Água: {k['agua_m3_t']:.1f} m3/t",
          f"- CO2e de energia (sem fibra): {k['co2e_energia_kg_t']:.0f} kg/t (combustível: {k['combustivel']})", ""]
    if "cenarios" in res:
        L += ["## Cenários do gêmeo (média [P5; P95])", "| Cenário | SEI | CO2e (kg/t) | Água (m3/t) |", "|---|---|---|---|"]
        for nome, r in res["cenarios"].items():
            f = lambda m, d=2: f"{r[m]['media']:.{d}f} [{r[m]['p5']:.{d}f}; {r[m]['p95']:.{d}f}]"
            L.append(f"| {nome} | {f('sei', 3)} | {f('co2_tex_kg_t', 0)} | {f('agua_tex_m3_t', 1)} |")
        L.append("")
    e = res.get("economia")
    if e and "p_equilibrio_sem_gate" in e:
        L += ["## Economia do biometano", f"- Referência de preço do gás: R$ {e['paridade_ou_tarifa']['media']:.2f}/m3",
              f"- Preço de equilíbrio sem taxa de destinação: R$ {e['p_equilibrio_sem_gate']['media']:.2f}/m3 "
              f"(competitivo em {100 * e['prob_competitivo_sem_gate']:.0f}% das amostras)",
              f"- Com taxa de destinação: R$ {e['p_equilibrio_com_gate']['media']:.2f}/m3 "
              f"({100 * e['prob_competitivo_com_gate']:.0f}%)",
              f"- VPL do hub de referência: R$ {e['vpl_hub_mi']['media']:.0f} mi [{e['vpl_hub_mi']['p5']:.0f}; {e['vpl_hub_mi']['p95']:.0f}]"]
    if e and "cavaco_r_m3eq" in e:
        L.append(f"- Cavaco: R$ {e['cavaco_r_m3eq']:.2f} por m3 de gás equivalente")
    if res.get("avisos"):
        L += ["", "## Avisos"] + [f"- {a}" for a in res["avisos"]]
    if anom is not None and len(anom):
        L += ["", f"## Anomalias: {len(anom)} eventos", anom.groupby("tipo").size().to_string()]
    return "\n".join(L)


def exemplo_csv(caminho, dias=14, semente=11):
    """Gera um CSV de demonstração (dados sintéticos calibrados) no formato esperado."""
    from .telemetria import gerar
    t, s = gerar(dias, semente)
    df = pd.DataFrame({"timestamp": t,
                       "producao_kg_h": s["textil.tinturaria.producao_kg_h"], "eletrica_kw": s["textil.utilidades.eletrica_kw"],
                       "gn_m3_h": s["textil.caldeira.gn_m3_h"], "agua_m3_h": s["textil.tinturaria.agua_m3_h"],
                       "temp_efluente_c": s["textil.ete.temp_efluente_c"], "ph": s["textil.ete.ph"]})
    df.to_csv(caminho, index=False)
    return df
