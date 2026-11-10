"""Gêmeos digitais locais (LDT agro e LDT têxtil) + camada federada DT2 com controle PID do SEI.

Simulação diária, vetorizada sobre N amostras Monte Carlo (cada amostra = um ano plausível).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .fontes import DESTINACAO_MTR, IDX, v

KWH_POR_M3_GN = v("pci_gn") * 4.1868 / 3600.0          # kcal/m3 -> kWh/m3 (~10,23)
EF_GN_KG_M3 = v("ef_gn_tj") * v("pci_gn") * 4.1868e-6   # tCO2/TJ * TJ/m3 * 1000 kg/t -> kg/m3 (~2,07)
W_SEI = {"E": 0.25, "W": 0.25, "M": 0.30, "C": 0.20}    # Petrillo et al. (2026), Eq. 4
BETA = {"agro": 0.5, "textil": 0.5}


@dataclass
class Politica:
    nome: str
    modo: str = "base"          # base | aberta | pid
    u1: float = 0.0             # fração do resíduo não valorizado desviada à biodigestão
    u2: float | None = None     # teor de rPET no poliéster
    u3: float = 0.0             # reúso de água na tinturaria
    hub: bool = False           # contrato com hub regional de biometano
    hub_m3: float | None = None # volume contratado (m3/dia); None = registro
    sp: float = 0.55            # setpoint do SEI federado (modo pid; também referência das métricas)
    kp: float = 1.0
    ki: float = 0.30
    kd: float = 0.0
    taxa: float = 0.05          # variação máxima do esforço por dia


def _tri(rng, lo, mo, hi, n):
    return rng.triangular(lo, mo, hi, n)


def _u(rng, chave, n):
    d = IDX[chave]
    return rng.uniform(d.lo, d.hi, n) if d.hi > d.lo else np.full(n, d.valor)


def amostrar(n, semente=42):
    """Parâmetros anuais incertos (um vetor por parâmetro)."""
    r = np.random.default_rng(semente)
    p = {
        "ef_grid": r.uniform(v("ef_sin_2025_min"), v("ef_sin_2023"), n),      # kgCO2/MWh
        "agua_suino": _u(r, "agua_por_suino", n),
        "gordura": _u(r, "gordura_por_suino", n),
        "bio_yield": _u(r, "biometano_por_t", n),
        "aceite": _u(r, "aceite_biodigestor", n),
        "agua_tex": _tri(r, v("agua_textil_br"), v("agua_textil_sc"), v("agua_textil_ue"), n),
        "eletr_tex": _u(r, "eletr_textil", n),
        "gn_tex": _u(r, "gn_textil", n),
        "ef_virg": _u(r, "ef_pes_virgem", n),
        "ef_rpet": _u(r, "ef_pes_rpet", n),
        "share_pes": _u(r, "share_poliester", n),
        "aterro": _u(r, "aterro_tco2e_t", n),
        "f_agua": _u(r, "fracao_termica_agua", n),
        "dest": r.integers(0, len(DESTINACAO_MTR), n),
    }
    D = np.array([[s[k] for k in ("reciclagem", "rec_energetica", "coprocess", "aterro", "efluentes", "outro")]
                  for s in DESTINACAO_MTR])
    sel = D[p["dest"]]
    p["valorizado_base"] = sel[:, 0] + sel[:, 1] + sel[:, 2]
    p["desviavel"] = sel[:, 3] + sel[:, 4] + sel[:, 5]
    p["share_aterro"] = sel[:, 3]
    return p


def simular(pol: Politica, p: dict, maximos: dict | None = None, semente=7, dias=365, guardar_serie=False,
            evento=True, sp_ref=None):
    n = len(p["ef_grid"])
    r = np.random.default_rng(semente)          # números aleatórios comuns entre cenários
    op = v("dias_operacao") / 365.0
    suinos_dia = v("planta_ref_suinos_dia") * op
    tex_dia = v("textil_t_dia") * op
    rpet_base, rpet_max, reuso_max = v("rpet_base"), v("rpet_max"), v("reuso_agua_max")

    acc = {k: np.zeros(n) for k in ("agua_a", "agua_t", "eletr", "gn_dem", "gn_fos", "bio", "co2_t", "co2_a",
                                     "prod_t", "suinos", "res_val", "res_tot", "lev", "abaixo", "sei", "sei2")}
    integ, erro_ant = np.zeros(n), np.zeros(n)
    s = np.zeros(n)                                  # esforço do controlador [0,1]
    sp = np.full(n, pol.sp) if sp_ref is None else np.asarray(sp_ref)
    sei_med = sp.copy()
    serie = []
    for d in range(dias):
        mes = d // 30.4
        ef = p["ef_grid"] * (1 + 0.15 * np.sin(2 * np.pi * (mes - 3) / 12))  # sazonalidade hidrológica (forma hipotética)
        prod_a = suinos_dia * np.exp(r.normal(0, 0.10, n) - 0.005)          # ±10 % (ruído do DT2)
        prod_t = tex_dia * np.exp(r.normal(0, 0.10, n) - 0.005)
        disp_bio = np.exp(r.normal(0, 0.15, n) - 0.011)                      # disponibilidade do biodigestor
        if evento and 150 <= d < 180:                                        # parada do biodigestor/hub (30 dias)
            disp_bio = disp_bio * 0.1

        # ---- alavancas
        if pol.modo == "pid":
            e = sp - sei_med
            integ = np.clip(integ + e, -5, 5)
            alvo = np.clip(pol.kp * e + pol.ki * integ + pol.kd * (e - erro_ant) + 0.3, 0, 1)
            s = np.clip(alvo, s - pol.taxa, s + pol.taxa) if d > 0 else alvo   # limite de taxa dos atuadores
            erro_ant = e
            # ordem de mérito: biodigestão -> reúso de água -> rPET
            u1 = np.clip(3 * s, 0, 1)
            u3 = np.clip(3 * s - 1, 0, 1) * reuso_max
            u2 = rpet_base + np.clip(3 * s - 2, 0, 1) * (rpet_max - rpet_base)
        else:
            u1 = np.full(n, pol.u1)
            u3 = np.full(n, pol.u3)
            u2 = np.full(n, rpet_base if pol.u2 is None else pol.u2)

        # ---- LDT agro (Oeste)
        gord_t = prod_a * p["gordura"] / 1000.0
        desv = gord_t * p["desviavel"] * u1 * p["aceite"]
        aterro_t = gord_t * p["share_aterro"] * (1 - u1 * p["aceite"])
        bio = desv * p["bio_yield"] * disp_bio
        if pol.hub:
            bio = bio + (v("hub_contratado") if pol.hub_m3 is None else pol.hub_m3) * disp_bio
        agua_a = prod_a * p["agua_suino"] / 1000.0
        co2_a = aterro_t * p["aterro"] * 1000.0                              # kg
        val = gord_t * p["valorizado_base"] + desv

        # ---- LDT têxtil (Vale do Itajaí)
        agua_t = prod_t * p["agua_tex"] * (1 - u3)
        eletr = prod_t * p["eletr_tex"]
        gn_dem = prod_t * p["gn_tex"] * (1 - u3 * p["f_agua"] * 0.5)        # metade do calor recuperado no reúso
        gn_fos = np.maximum(0.0, gn_dem - bio)
        fibra = prod_t * 1000 * p["share_pes"] * ((1 - u2) * p["ef_virg"] + u2 * p["ef_rpet"])
        co2_t = eletr * ef / 1000.0 + gn_fos * EF_GN_KG_M3 + fibra           # kg

        for k, x in (("agua_a", agua_a), ("agua_t", agua_t), ("eletr", eletr), ("gn_dem", gn_dem),
                     ("gn_fos", gn_fos), ("bio", np.minimum(bio, gn_dem)), ("co2_t", co2_t), ("co2_a", co2_a),
                     ("prod_t", prod_t), ("suinos", prod_a), ("res_val", val), ("res_tot", gord_t)):
            acc[k] += x
        acc["lev"] += (u1 + u3 / reuso_max + (u2 - rpet_base) / (rpet_max - rpet_base)) / 3

        # ---- SEI diário medido (com 1 dia de atraso para o controlador)
        if maximos is not None:
            ind = indicadores_dia(prod_t, prod_a, eletr, gn_dem, agua_t, agua_a, co2_t, co2_a,
                                  val, gord_t, u2, p["share_pes"])
            sei_dia = sei_federado(ind, maximos)
            sei_med = sei_dia
            acc["sei"] += sei_dia
            acc["sei2"] += sei_dia ** 2
            acc["abaixo"] += (sei_dia < sp - 0.01)             # banda de tolerância de 0,01
            if guardar_serie:
                serie.append((float(np.median(sei_dia)), float(np.percentile(sei_dia, 5)),
                              float(np.percentile(sei_dia, 95)), float(np.median(s if pol.modo == "pid" else u1))))
    out = {
        "energia_kwh_t": (acc["eletr"] + acc["gn_dem"] * KWH_POR_M3_GN) / acc["prod_t"],
        "gn_fossil_m3_t": acc["gn_fos"] / acc["prod_t"],
        "agua_tex_m3_t": acc["agua_t"] / acc["prod_t"],
        "agua_agro_l_suino": acc["agua_a"] * 1000 / acc["suinos"],
        "co2_tex_kg_t": acc["co2_t"] / acc["prod_t"],
        "co2_agro_kg_1000suinos": acc["co2_a"] / acc["suinos"] * 1000,
        "co2_total_t_ano": (acc["co2_t"] + acc["co2_a"]) / 1000,
        "circ_agro": acc["res_val"] / acc["res_tot"],
        "biometano_m3_ano": acc["bio"],
        "cobertura_bio": acc["bio"] / acc["gn_dem"],
        "esforco": acc["lev"] / dias,
        "co2_tex_t_ano": acc["co2_t"] / 1000,
    }
    if maximos is not None:
        out["sei"] = acc["sei"] / dias
        out["sei_dp"] = np.sqrt(np.maximum(acc["sei2"] / dias - out["sei"] ** 2, 0))
        out["dias_abaixo_sp"] = acc["abaixo"]
    if guardar_serie:
        out["_serie"] = serie
    return out


def indicadores_dia(prod_t, prod_a, eletr, gn_dem, agua_t, agua_a, co2_t, co2_a, val, gord, u2, share_pes):
    return {
        "E_t": (eletr + gn_dem * KWH_POR_M3_GN) / prod_t,
        "W_t": agua_t / prod_t,
        "M_t": u2 * share_pes,
        "C_t": co2_t / prod_t,
        "W_a": agua_a * 1000 / prod_a,
        "M_a": val / gord,
        "C_a": co2_a / prod_a * 1000,
    }


def sei_federado(i, mx):
    w = W_SEI
    sei_t = (w["E"] * (1 - i["E_t"] / mx["E_t"]) + w["W"] * (1 - i["W_t"] / mx["W_t"])
             + w["M"] * (i["M_t"] / mx["M_t"]) + w["C"] * (1 - i["C_t"] / mx["C_t"]))
    ws = w["W"] + w["M"] + w["C"]                         # LDT agro sem termo de energia (pesos renormalizados)
    sei_a = (w["W"] * (1 - i["W_a"] / mx["W_a"]) + w["M"] * i["M_a"] + w["C"] * (1 - i["C_a"] / mx["C_a"])) / ws
    return BETA["agro"] * np.clip(sei_a, -1, 1) + BETA["textil"] * np.clip(sei_t, -1, 1)


def calibrar_maximos(p):
    """Limites de normalização: 1,2 × P95 da linha de base (silos); M_t pelo teto técnico de rPET."""
    b = simular(Politica("base"), p)
    return {
        "E_t": 1.2 * np.percentile(b["energia_kwh_t"], 95),
        "W_t": 1.2 * np.percentile(b["agua_tex_m3_t"], 95),
        "M_t": v("rpet_max") * IDX["share_poliester"].hi,
        "C_t": 1.2 * np.percentile(b["co2_tex_kg_t"], 95),
        "W_a": 1.2 * np.percentile(b["agua_agro_l_suino"], 95),
        "C_a": 1.2 * np.percentile(b["co2_agro_kg_1000suinos"], 95),
    }


def escala_estadual(p):
    """Potencial estadual de biometano a partir da gordura residual não valorizada (por amostra)."""
    gord_t = (v("abate_suinos_sc") * p["gordura"] + v("abate_frangos_sc") * v("gordura_por_frango")) / 1000
    desv = gord_t * p["desviavel"] * p["aceite"]
    bio_dia = desv * p["bio_yield"] / 365
    return {"gordura_t_ano": gord_t, "desviavel_t_ano": desv, "bio_m3_dia": bio_dia,
            "share_scgas": bio_dia / v("scgas_vol_2024")}
