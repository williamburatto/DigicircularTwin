"""Camada econômica: custo nivelado do biometano (preço de equilíbrio), VPL por elo e custo evitado.

Tarifas reguladas públicas: Celesc A4 Verde (ANEEL REH 3.511/2025) e componente de gás+transporte
da SCGÁS (ARESC Res. 287/2024). Valores em R$ reais (sem tributos recuperáveis: a indústria
credita ICMS/PIS/COFINS, logo a análise usa tarifas sem tributos).
"""
from __future__ import annotations

import numpy as np

from .federacao import EF_GN_KG_M3
from .fontes import IDX, v


def _u(r, k, n):
    d = IDX[k]
    return r.uniform(d.lo, d.hi, n) if d.hi > d.lo else np.full(n, d.valor)


def amostrar_econ(n, semente=101):
    r = np.random.default_rng(semente)
    tg = IDX["tarifa_gn_ind"]
    return {
        "capex": r.uniform(v("capex_hub_min"), v("capex_hub_max"), n),
        "opex_frac": _u(r, "opex_frac", n),
        "kwh_m3": _u(r, "kwh_upgrading", n),
        "fc": _u(r, "fator_capacidade", n),
        "p_dig": _u(r, "preco_digestato", n),
        "wacc": _u(r, "wacc", n),
        "tarifa_gn": r.triangular(tg.lo, tg.valor, tg.hi, n),
        "gate_aterro": _u(r, "gate_fee_ref", n),          # custo atual do frigorífico por tonelada destinada
    }


def crf(r, n):
    return r * (1 + r) ** n / ((1 + r) ** n - 1)


def tarifa_eletrica_media(frac_ponta=0.125):
    """Hub operando 24 h: 3 h de ponta por dia útil (≈12,5 % da energia)."""
    return frac_ponta * v("celesc_a4v_ponta") + (1 - frac_ponta) * v("celesc_a4v_fponta")


def custo_nivelado(e, gate_recebido=0.0):
    """Preço de equilíbrio do biometano (R$/m3) para VPL = 0 do hub, dado o gate fee recebido (R$/t)."""
    anos = v("vida_util")
    q = v("hub_capacidade") * 365 * e["fc"]
    opex = e["opex_frac"] * e["capex"] + q * e["kwh_m3"] * tarifa_eletrica_media()
    dig = v("hub_digestato") * 12 * e["p_dig"]
    gate = v("hub_residuos") * 365 * e["fc"] * gate_recebido
    return (e["capex"] * crf(e["wacc"], anos) + opex - dig - gate) / q


def vpl(fluxo_anual, taxa, anos, capex=0.0):
    fator = (1 - (1 + taxa) ** -anos) / taxa
    return fluxo_anual * fator - capex


def avaliar_economia(n=10000, preco_carbono=(0, 100, 250, 500)):
    e = amostrar_econ(n)
    p0 = custo_nivelado(e, 0.0)
    p_gate = custo_nivelado(e, e["gate_aterro"])          # hub recebe o que o frigorífico paga hoje ao aterro
    # Disposição máxima a pagar da tinturaria = tarifa evitada + valor do carbono evitado
    wtp = {c: e["tarifa_gn"] + c * EF_GN_KG_M3 / 1000 for c in preco_carbono}
    # preço de carbono que iguala custo do biometano e tarifa (break-even)
    c_eq0 = np.maximum(0, (p0 - e["tarifa_gn"]) / (EF_GN_KG_M3 / 1000))
    c_eq_gate = np.maximum(0, (p_gate - e["tarifa_gn"]) / (EF_GN_KG_M3 / 1000))
    # VPL do sistema (hub + tinturaria + frigorífico) — independe dos preços de transferência
    anos = v("vida_util")
    q = v("hub_capacidade") * 365 * e["fc"]
    t_res = v("hub_residuos") * 365 * e["fc"]
    opex = e["opex_frac"] * e["capex"] + q * e["kwh_m3"] * tarifa_eletrica_media()
    fluxo_sis = {c: q * (e["tarifa_gn"] + c * EF_GN_KG_M3 / 1000) + t_res * e["gate_aterro"]
                 + v("hub_digestato") * 12 * e["p_dig"] - opex for c in preco_carbono}
    vpl_sis = {c: vpl(fluxo_sis[c], e["wacc"], anos, e["capex"]) for c in preco_carbono}
    return {"amostras": e, "p_equilibrio_sem_gate": p0, "p_equilibrio_com_gate": p_gate, "wtp": wtp,
            "c_equilibrio_sem_gate": c_eq0, "c_equilibrio_com_gate": c_eq_gate, "vpl_sistema": vpl_sis,
            "tarifa_eletr_media": tarifa_eletrica_media()}


def custo_evitado_tinturaria(v_m3_dia, preco_bio, tarifa_gn, dias=300, preco_carbono=0.0):
    """Custo evitado anual (R$) ao trocar gás fóssil por biometano contratado."""
    return v_m3_dia * dias * (tarifa_gn - preco_bio + preco_carbono * EF_GN_KG_M3 / 1000)


# ---------------------------------------------------------------------------------------------
# v0.3: cavaco como combustível concorrente (preços anunciados em SC, MF Rural)
# ---------------------------------------------------------------------------------------------
CAVACO_ENERGIA = {                      # chave: (unidade, município)
    "cavaco_imbituba": ("t", "Imbituba"), "cavaco_sao_miguel_oeste": ("t", "São Miguel do Oeste"),
    "cavaco_mafra": ("t", "Mafra"), "cavaco_porto_belo": ("m3", "Porto Belo"),
    "cavaco_joinville": ("m3", "Joinville"), "cavaco_garuva": ("m3", "Garuva"),
}
KWH_POR_M3_GN = 10.23


def custo_cavaco_m3eq(preco, unidade, pci_mwh_t, dens_kg_m3, ef_cav, ef_gas):
    """Custo do cavaco por m3 de gás natural equivalente em calor útil (R$/m3eq).
    preco em R$/t ou R$/m3; pci em MWh/t; calor útil igual => combustível = KWH_POR_M3_GN*ef_gas/ef_cav."""
    preco_t = preco if unidade == "t" else preco / (dens_kg_m3 / 1000.0)
    kwh_combustivel = KWH_POR_M3_GN * ef_gas / ef_cav
    return preco_t / (pci_mwh_t * 1000.0) * kwh_combustivel


def avaliar_cavaco(n=10000, semente=202):
    r = np.random.default_rng(semente)
    e = amostrar_econ(n)
    pci = r.uniform(IDX["cavaco_pci"].lo, IDX["cavaco_pci"].hi, n)
    dens = r.uniform(IDX["cavaco_densidade"].lo, IDX["cavaco_densidade"].hi, n)
    ec = r.uniform(IDX["eficiencia_caldeira_cavaco"].lo, IDX["eficiencia_caldeira_cavaco"].hi, n)
    eg = r.uniform(IDX["eficiencia_caldeira_gas"].lo, IDX["eficiencia_caldeira_gas"].hi, n)
    por_municipio = {}
    for k, (un, mun) in CAVACO_ENERGIA.items():
        c = custo_cavaco_m3eq(IDX[k].valor, un, pci, dens, ec, eg)
        por_municipio[mun] = {"preco": IDX[k].valor, "unidade": un, "m3eq_media": float(c.mean()),
                              "m3eq_p5": float(np.percentile(c, 5)), "m3eq_p95": float(np.percentile(c, 95))}
    # mistura uniforme das seis ofertas = incerteza de qual fornecedor/município atende a tinturaria
    idx = r.integers(0, len(CAVACO_ENERGIA), n)
    chaves = list(CAVACO_ENERGIA)
    c_mix = np.array([custo_cavaco_m3eq(IDX[chaves[i]].valor, CAVACO_ENERGIA[chaves[i]][0], pci[j], dens[j], ec[j], eg[j])
                      for j, i in enumerate(idx)])
    p0 = custo_nivelado(e, 0.0)
    p_gate = custo_nivelado(e, e["gate_aterro"])
    return {"por_municipio": por_municipio, "c_mix": c_mix,
            "mix": {"media": float(c_mix.mean()), "p5": float(np.percentile(c_mix, 5)), "p95": float(np.percentile(c_mix, 95))},
            "p_bio_menor_que_cavaco_sem_gate": float(np.mean(p0 <= c_mix)),
            "p_bio_menor_que_cavaco_com_gate": float(np.mean(p_gate <= c_mix)),
            "razao_gas_cavaco": float(np.mean(e["tarifa_gn"] / c_mix)),
            "economia_gas_para_cavaco_r_m3": {"media": float((e["tarifa_gn"] - c_mix).mean()),
                                              "p5": float(np.percentile(e["tarifa_gn"] - c_mix, 5)),
                                              "p95": float(np.percentile(e["tarifa_gn"] - c_mix, 95))}}
