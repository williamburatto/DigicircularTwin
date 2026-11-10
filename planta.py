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


def _sem_acento(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(t).lower()) if unicodedata.category(c) != "Mn")


PALAVRAS = {"timestamp": ["data", "hora", "time", "date"], "producao_kg_h": ["prod", "tecido", "kg"],
            "eletrica_kw": ["kwh", "kw", "eletric", "energia", "potencia", "power"], "gn_m3_h": ["gas", "gn", "m3"],
            "agua_m3_h": ["agua", "water"], "cavaco_kg_h": ["cavaco", "biomassa", "chip"], "vapor_kg_h": ["vapor", "steam"],
            "temp_efluente_c": ["temp"], "ph": ["ph"]}


def detectar_mapa(colunas):
    """Sugere {coluna_padrão: coluna_do_arquivo}: primeiro por nome exato, depois por palavras-chave no nome."""
    baixo = {c.lower().strip(): c for c in colunas}
    mapa = {p: next((baixo[a] for a in nomes if a in baixo), None) for p, nomes in ALIASES.items()}
    usadas = {x for x in mapa.values() if x}
    for p in COLUNAS:
        if mapa[p]:
            continue
        for c in colunas:
            t = _sem_acento(c)
            if c not in usadas and any(k in t for k in PALAVRAS[p]) and not (p == "producao_kg_h" and "kwh" in t):
                if p == "gn_m3_h" and ("agua" in t or "vapor" in t):
                    continue
                mapa[p] = c; usadas.add(c); break
    return mapa


def sugerir_unidade(padrao, nome_coluna):
    """Sugere a unidade pela escrita do cabeçalho (ex.: 'Prod (t/h)' -> 't/h'; 'kWh' -> 'kWh no intervalo')."""
    t = _sem_acento(nome_coluna)
    ops = list(UNIDADES.get(padrao, {}))
    pistas = {"producao_kg_h": [("t/h", "t/h"), ("kg/h", "kg/h"), ("(t)", "t no intervalo"), ("(kg)", "kg no intervalo")],
              "eletrica_kw": [("kwh", "kWh no intervalo"), ("mwh", "MWh no intervalo"), ("mw", "MW"), ("kw", "kW"), ("(w)", "W")],
              "agua_m3_h": [("l/h", "L/h"), ("m3/h", "m³/h"), ("(m3)", "m³ no intervalo"), ("(l)", "L no intervalo")],
              "gn_m3_h": [("m3/h", "m³/h"), ("(m3)", "m³ no intervalo")]}
    for chave, un in pistas.get(padrao, []):
        if chave in t and un in ops:
            return un
    return ops[0] if ops else None


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


# ------------------------------------------------------------------------------------------------ importação amigável
NOMES_AMIGAVEIS = {
    "timestamp": "Data e hora", "producao_kg_h": "Produção de tecido", "eletrica_kw": "Eletricidade",
    "gn_m3_h": "Gás natural", "agua_m3_h": "Água", "cavaco_kg_h": "Cavaco (biomassa)", "vapor_kg_h": "Vapor",
    "temp_efluente_c": "Temperatura do efluente", "ph": "pH do efluente"}
# unidade -> (fator para a unidade padrão, é_acumulado). "no intervalo" = valor somado no período entre duas linhas.
UNIDADES = {
    "producao_kg_h": {"kg/h": (1, False), "t/h": (1000, False), "kg no intervalo": (1, True), "t no intervalo": (1000, True)},
    "eletrica_kw": {"kW": (1, False), "W": (0.001, False), "MW": (1000, False),
                    "kWh no intervalo": (1, True), "MWh no intervalo": (1000, True)},
    "gn_m3_h": {"m³/h": (1, False), "m³ no intervalo": (1, True)},
    "agua_m3_h": {"m³/h": (1, False), "L/h": (0.001, False), "m³ no intervalo": (1, True), "L no intervalo": (0.001, True)},
    "cavaco_kg_h": {"kg/h": (1, False), "t/h": (1000, False), "kg no intervalo": (1, True)},
    "vapor_kg_h": {"kg/h": (1, False), "t/h": (1000, False), "kg no intervalo": (1, True)},
    "temp_efluente_c": {"°C": (1, False)}, "ph": {"pH": (1, False)},
}
ABAS_EXCEL = (".xlsx", ".xlsm")


def modelo_excel() -> bytes:
    """Planilha-modelo (.xlsx) com a aba Dados (exemplo de 24 h) e a aba Instruções."""
    import io
    from datetime import datetime, timedelta
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Dados"
    ws.append(COLUNAS)
    obrig = PatternFill("solid", fgColor="F4B183")
    opc = PatternFill("solid", fgColor="D9D9D9")
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = obrig if c.value in OBRIGATORIAS else opc
    ini = datetime(2026, 3, 2, 0, 0)
    for h in range(24):
        ativo = 6 <= h < 22
        ws.append([ini + timedelta(hours=h), 440 + 15 * (h % 3) if ativo else 0, 320 + 8 * (h % 4) if ativo else 60,
                   500 + 10 * (h % 3) if ativo else 20, 54 if ativo else 2, None, None, 34.5 if ativo else None,
                   7.1 if ativo else None])
    for r in ws.iter_rows(min_row=2, max_col=1):
        r[0].number_format = "yyyy-mm-dd hh:mm"
    for i, w in enumerate([18, 16, 14, 12, 12, 13, 13, 17, 8], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ws.freeze_panes = "A2"
    ins = wb.create_sheet("Instruções")
    linhas = [
        "COMO PREENCHER",
        "1. Na aba Dados, apague as linhas de exemplo e cole os seus dados a partir da linha 2 (a linha 1 são os nomes das colunas).",
        "2. Uma linha por intervalo de tempo (a cada 15 min, 1 h, etc.), sempre em ordem cronológica.",
        "3. Colunas laranja são obrigatórias (data e hora, produção, eletricidade). As cinzas são opcionais, mas melhoram o resultado.",
        "4. Deixe vazio o que não existe. Não coloque textos como 'n/d' nas células numéricas.",
        "5. Pelo menos 4 semanas de dados. O ideal são 12 meses.",
        "",
        "UNIDADES PADRÃO (se a sua planilha usa outra, escolha a unidade na hora de importar)",
        "producao_kg_h: kg de tecido processado por hora",
        "eletrica_kw: potência elétrica média em kW",
        "gn_m3_h: gás natural em m³ por hora",
        "agua_m3_h: água em m³ por hora",
        "cavaco_kg_h: cavaco queimado em kg por hora",
        "vapor_kg_h: vapor gerado em kg por hora",
        "temp_efluente_c: temperatura do efluente tratado em °C",
        "ph: pH do efluente tratado",
        "",
        "Se você só tem o consumo somado por intervalo (por exemplo kWh por hora), escolha a unidade 'no intervalo' ao importar.",
        "Seus dados não são enviados a ninguém: ficam só na sessão do navegador.",
    ]
    for t in linhas:
        ins.append([t])
    ins["A1"].font = Font(bold=True)
    ins["A8"].font = Font(bold=True)
    ins.column_dimensions["A"].width = 120
    for row in ins.iter_rows():
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def listar_abas(conteudo: bytes, nome: str) -> list[str]:
    import io
    if nome.lower().endswith(ABAS_EXCEL):
        return pd.ExcelFile(io.BytesIO(conteudo), engine="openpyxl").sheet_names
    return []


def ler_tabela(conteudo: bytes, nome: str, aba=None, linha_cabecalho: int = 1) -> pd.DataFrame:
    """Lê Excel (.xlsx) ou CSV a partir dos bytes. linha_cabecalho: linha (1 = primeira) com os nomes das colunas."""
    import io
    bio = io.BytesIO(conteudo)
    h = max(int(linha_cabecalho) - 1, 0)
    if nome.lower().endswith(ABAS_EXCEL):
        df = pd.read_excel(bio, sheet_name=aba if aba is not None else 0, header=h, engine="openpyxl")
    elif nome.lower().endswith(".xls"):
        raise ValueError("arquivo .xls antigo: no Excel, use Salvar como e escolha .xlsx (ou CSV)")
    else:
        df = pd.read_csv(bio, sep=None, engine="python", header=h)
    df = df.dropna(how="all").dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def converter_unidades(df, escolhas):
    """Aplica as unidades escolhidas. escolhas: {coluna_padrão: nome_da_unidade}. Valores 'no intervalo'
    são divididos pelo tamanho do intervalo (dt_h) para virar taxa horária."""
    d = df.copy()
    for c, un in (escolhas or {}).items():
        if c not in d or un not in UNIDADES.get(c, {}):
            continue
        fator, acum = UNIDADES[c][un]
        d[c] = d[c] * fator
        if acum:
            d[c] = d[c].where(d["dt_h"] <= 0, d[c] / d["dt_h"].where(d["dt_h"] > 0))
            d.loc[d["dt_h"] <= 0, c] = 0.0
    return d


REFERENCIA_SC = {"eletr_kwh_t": ("Eletricidade (kWh/t)", "eletr_textil"), "gn_m3_t": ("Gás natural (m³/t)", "gn_textil"),
                 "agua_m3_t": ("Água (m³/t)", "agua_textil_sc")}


def comparar_referencia(k):
    """Tabela: sua planta x referência de SC usada no artigo."""
    linhas = []
    for chave, (nome, par) in REFERENCIA_SC.items():
        x, ref = k.get(chave), v(par)
        if x is None or x != x or x <= 0:
            continue
        linhas.append({"Indicador": nome, "Sua planta": x, "Referência SC (artigo)": ref,
                       "Diferença": f"{100 * (x / ref - 1):+.0f} %"})
    return pd.DataFrame(linhas).set_index("Indicador") if linhas else pd.DataFrame()


def checagens(k, qual=None):
    """Avisos em linguagem simples sobre unidades e consistência: lista de (nivel, texto), nivel em {'erro','aviso','ok'}."""
    L = []
    e, g, a = k["eletr_kwh_t"], k.get("gn_m3_t", 0.0), k.get("agua_m3_t", float("nan"))
    if not 150 <= e <= 3500:
        L.append(("aviso", f"Eletricidade de {e:.0f} kWh/t está fora do usual (200 a 3.000). Confira se a unidade é kW ou W "
                           "e se a produção está em kg/h ou t/h."))
    if g and not 100 <= g <= 4500:
        L.append(("aviso", f"Gás de {g:.0f} m³/t está fora do usual. Confira a unidade do gás e da produção."))
    if a == a and a > 0 and not 20 <= a <= 500:
        L.append(("aviso", f"Água de {a:.0f} m³/t está fora do usual (referências de 80 a 230). Confira a unidade (m³ ou L)."))
    if qual:
        if qual["dias"] < 7:
            L.append(("aviso", f"Só {qual['dias']:.1f} dia(s) de dados: o resultado terá faixa de incerteza maior. O ideal são 4 semanas ou mais."))
        if qual["lacunas"] > 0.05 * qual["linhas"]:
            L.append(("aviso", f"{qual['lacunas']} intervalos sem dados (lacunas). Esses períodos não entram nas somas."))
        faltam = [NOMES_AMIGAVEIS[c].lower() for c, x in qual["por_coluna"].items()
                  if x["presente"] and x["faltantes_pct"] > 20]
        if faltam:
            L.append(("aviso", "Muitos valores vazios em: " + ", ".join(faltam) + "."))
        neg = [NOMES_AMIGAVEIS[c].lower() for c, x in qual["por_coluna"].items() if x["negativos"] > 0]
        if neg:
            L.append(("aviso", "Há valores negativos em: " + ", ".join(neg) + " (tratados como zero)."))
    if not L:
        L.append(("ok", "Os valores parecem coerentes com o esperado para uma tinturaria."))
    return L
