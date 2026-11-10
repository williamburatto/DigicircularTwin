"""Módulos de contribuição à cadeia têxtil (cálculos simplificados de engenharia, transparentes e editáveis).

Cada função devolve um dict com resultados e a lista de premissas, com a origem de cada uma:
  R = referência pública do registro do projeto, L = literatura, F = física/constante, H = hipótese a confirmar.
São estimativas de pré-viabilidade, não projeto de engenharia.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import numpy as np

from .federacao import EF_GN_KG_M3, KWH_POR_M3_GN
from .fontes import v

CP_AGUA_KWH_KG_K = 4.186 / 3600.0      # calor específico da água, kWh/(kg.K)
PCI_CH4_KWH_M3 = 9.97                  # poder calorífico inferior do metano, kWh/m3 (condição normal)
ORIGENS = {"R": "Referência pública", "L": "Literatura", "F": "Física", "H": "Hipótese: confirmar"}


def _payback(capex, economia):
    return capex / economia if capex > 0 and economia > 0 else float("nan")


def _base(economia, co2_t, capex, **extra):
    r = {"economia_r_ano": float(economia), "co2e_evitado_t_ano": float(co2_t), "capex_r": float(capex),
         "payback_anos": float(_payback(capex, economia))}
    r.update({k: float(x) for k, x in extra.items()})
    return r


def _prem(*linhas):
    return [{"Premissa": n, "Valor": val, "Unidade": u, "Origem": ORIGENS[o]} for n, val, u, o in linhas]


# ----------------------------------------------------------------------------- 1. recuperação de calor do efluente
def recuperacao_calor(vazao_m3_dia, t_efluente_c, t_entrada_c, eficiencia, dias_ano, preco_gas, capex_r,
                      eficiencia_caldeira=None):
    ec = eficiencia_caldeira or v("eficiencia_caldeira_gas")
    dT = max(0.0, t_efluente_c - t_entrada_c)
    kwh_dia = vazao_m3_dia * 1000 * CP_AGUA_KWH_KG_K * dT * eficiencia
    kwh_ano = kwh_dia * dias_ano
    gas = kwh_ano / (ec * KWH_POR_M3_GN)
    r = _base(gas * preco_gas, gas * EF_GN_KG_M3 / 1000, capex_r, energia_recuperada_kwh_ano=kwh_ano,
              gas_evitado_m3_ano=gas, agua_preaquecida_c=eficiencia * dT)
    r["premissas"] = _prem(("Calor específico da água", 4.186, "kJ/(kg.K)", "F"), ("Eficiência do trocador", eficiencia, "-", "H"),
                           ("Eficiência da caldeira a gás", ec, "-", "R"), ("Poder calorífico do gás", KWH_POR_M3_GN, "kWh/m³", "R"),
                           ("Fator de emissão do gás", EF_GN_KG_M3, "kgCO₂/m³", "R"))
    return r


# ----------------------------------------------------------------------------- 2. programação por tarifa
def energia_por_janela(df, ini_h=18, fim_h=21, so_dias_uteis=True):
    """Da série da planta: energia (kWh) dentro da janela de ponta, total e dias de produção. Retorna (kwh_ponta, kwh_total, dias)."""
    from . import planta as P
    d = P._integrar(df)
    h = d["timestamp"].dt.hour
    na_janela = (h >= ini_h) & (h < fim_h)
    if so_dias_uteis:
        na_janela &= d["timestamp"].dt.weekday < 5
    ativos = d.loc[d["ativo"], "dia"].nunique()
    return float(d.loc[na_janela, "kwh"].sum()), float(d["kwh"].sum()), int(ativos)


def programacao_tarifa(kwh_ponta_ano, kwh_total_ano, fracao_deslocavel, tarifa_ponta, tarifa_fponta, capex_r=0.0):
    deslocado = kwh_ponta_ano * fracao_deslocavel
    economia = deslocado * max(0.0, tarifa_ponta - tarifa_fponta)
    r = _base(economia, 0.0, capex_r, kwh_deslocado_ano=deslocado, parcela_ponta=kwh_ponta_ano / kwh_total_ano if kwh_total_ano else 0.0)
    r["premissas"] = _prem(("Tarifa de ponta", tarifa_ponta, "R$/kWh", "R"), ("Tarifa fora de ponta", tarifa_fponta, "R$/kWh", "R"),
                           ("Fração da carga de ponta que pode ser deslocada", fracao_deslocavel, "-", "H"))
    r["nota"] = ("O ganho é financeiro: o fator de emissão da rede usado no modelo é plano, então deslocar carga não muda o CO₂e. "
                 "Confirme a janela de ponta e a modalidade tarifária com a distribuidora.")
    return r


# ----------------------------------------------------------------------------- 3. compra coletiva de gás
def compra_coletiva(demandas_m3_dia, preco_base, desc_max, vol_saturacao_m3_dia, dias_ano, hub_m3_dia=0.0):
    """demandas_m3_dia: {empresa: m3/dia}. Preço cai linearmente com o volume até desc_max no volume de saturação (H)."""
    preco = lambda q: preco_base * (1 - desc_max * min(1.0, q / vol_saturacao_m3_dia))
    total = float(sum(demandas_m3_dia.values()))
    p_col = preco(total)
    linhas = []
    for n, q in demandas_m3_dia.items():
        p_ind = preco(q)
        linhas.append({"Empresa": n, "Demanda (m³/dia)": q, "Preço sozinha (R$/m³)": p_ind, "Preço no grupo (R$/m³)": p_col,
                       "Economia (R$/ano)": q * dias_ano * (p_ind - p_col)})
    econ = sum(x["Economia (R$/ano)"] for x in linhas)
    cobertura = min(1.0, hub_m3_dia / total) if total else 0.0
    co2 = min(hub_m3_dia, total) * dias_ano * EF_GN_KG_M3 / 1000      # só se o grupo contratar o biometano do hub
    r = _base(econ, co2, 0.0, demanda_total_m3_dia=total, preco_grupo=p_col, cobertura_hub=cobertura)
    r["tabela"] = linhas
    r["premissas"] = _prem(("Preço de referência do gás (sem desconto)", preco_base, "R$/m³", "R"),
                           ("Desconto máximo por volume", desc_max, "-", "H"),
                           ("Volume em que o desconto máximo é atingido", vol_saturacao_m3_dia, "m³/dia", "H"))
    r["nota"] = ("O desconto por volume é hipótese: peça à distribuidora a tabela real (faixas de consumo e condições de "
                 "contrato). O CO₂e evitado só existe se o grupo contratar biometano do hub.")
    return r


# ----------------------------------------------------------------------------- 4. lodo da ETE em biogás
def biogas_lodo(lodo_t_st_dia, frac_sv, rend_ch4_m3_kg_sv, consumo_proprio, dias_ano, preco_gas, demanda_gas_m3_ano, capex_r):
    sv_kg = lodo_t_st_dia * 1000 * frac_sv
    ch4_dia = sv_kg * rend_ch4_m3_kg_sv
    kwh_liq = ch4_dia * PCI_CH4_KWH_M3 * (1 - consumo_proprio)
    gas_eq = kwh_liq * dias_ano / KWH_POR_M3_GN
    r = _base(gas_eq * preco_gas, gas_eq * EF_GN_KG_M3 / 1000, capex_r, metano_m3_dia=ch4_dia,
              gas_equivalente_m3_ano=gas_eq, cobertura_gas=gas_eq / demanda_gas_m3_ano if demanda_gas_m3_ano else 0.0)
    r["premissas"] = _prem(("Fração de sólidos voláteis no lodo seco", frac_sv, "-", "H"),
                           ("Rendimento de metano", rend_ch4_m3_kg_sv, "m³ CH₄/kg SV", "H"),
                           ("Consumo próprio do digestor (aquecimento e bombas)", consumo_proprio, "-", "H"),
                           ("Poder calorífico do metano", PCI_CH4_KWH_M3, "kWh/m³", "F"))
    r["nota"] = ("Lodo de tinturaria costuma ter potencial baixo e pode conter compostos que inibem a digestão. "
                 "Só um ensaio de potencial bioquímico de metano (BMP) confirma o rendimento.")
    return r


# ----------------------------------------------------------------------------- 5. energia solar
def fotovoltaica(kwp, hsp_kwh_m2_dia, pr, autoconsumo, tarifa_eletr, capex_r_kwp, ef_rede_kg_mwh=None):
    ef = v("ef_sin_2023") if ef_rede_kg_mwh is None else ef_rede_kg_mwh
    kwh = kwp * hsp_kwh_m2_dia * pr * 365
    uteis = kwh * autoconsumo
    r = _base(uteis * tarifa_eletr, uteis * ef / 1e6, kwp * capex_r_kwp, geracao_kwh_ano=kwh, aproveitado_kwh_ano=uteis)
    r["premissas"] = _prem(("Irradiação média diária no plano do painel", hsp_kwh_m2_dia, "kWh/m²/dia", "H"),
                           ("Desempenho global do sistema (PR)", pr, "-", "H"), ("Fração da geração consumida no local", autoconsumo, "-", "H"),
                           ("Custo instalado", capex_r_kwp, "R$/kWp", "H"), ("Fator de emissão da rede (SIN)", ef, "kgCO₂/MWh", "R"))
    return r


def kwp_para_cobrir(kwh_consumo_ano, cobertura, hsp, pr):
    return cobertura * kwh_consumo_ano / (hsp * pr * 365)


def solar_termica(area_m2, hsp_kwh_m2_dia, eficiencia, dias_ano, preco_gas, capex_r_m2, eficiencia_caldeira=None):
    ec = eficiencia_caldeira or v("eficiencia_caldeira_gas")
    kwh = area_m2 * hsp_kwh_m2_dia * eficiencia * dias_ano
    gas = kwh / (ec * KWH_POR_M3_GN)
    r = _base(gas * preco_gas, gas * EF_GN_KG_M3 / 1000, area_m2 * capex_r_m2, energia_termica_kwh_ano=kwh, gas_evitado_m3_ano=gas)
    r["premissas"] = _prem(("Irradiação média diária", hsp_kwh_m2_dia, "kWh/m²/dia", "H"),
                           ("Eficiência média do coletor", eficiencia, "-", "H"), ("Custo instalado", capex_r_m2, "R$/m²", "H"),
                           ("Eficiência da caldeira a gás", ec, "-", "R"))
    return r


# ----------------------------------------------------------------------------- 6. circularidade têxtil
def circularidade(producao_t_ano, perda_pct, reciclavel_pct, preco_venda_r_t, custo_destinacao_r_t, subst_fibra,
                  ef_virgem_kg_kg=None, ef_reciclada_kg_kg=None):
    ev = v("ef_pes_virgem") if ef_virgem_kg_kg is None else ef_virgem_kg_kg
    er = v("ef_pes_rpet") if ef_reciclada_kg_kg is None else ef_reciclada_kg_kg
    aparas = producao_t_ano * perda_pct / 100
    reciclado = aparas * reciclavel_pct / 100
    econ = reciclado * (preco_venda_r_t + custo_destinacao_r_t)
    co2 = reciclado * subst_fibra * max(0.0, ev - er)           # t/t = kgCO2e/kg
    r = _base(econ, co2, 0.0, aparas_t_ano=aparas, desviado_t_ano=reciclado, fibra_virgem_evitada_t_ano=reciclado * subst_fibra)
    r["premissas"] = _prem(("Perda de tecido (aparas e refugo)", perda_pct, "%", "H"), ("Parcela reciclável", reciclavel_pct, "%", "H"),
                           ("Substituição de fibra virgem por reciclada", subst_fibra, "-", "H"),
                           ("Emissão da fibra de poliéster virgem", ev, "kgCO₂e/kg", "L"),
                           ("Emissão da fibra rPET", er, "kgCO₂e/kg", "L"))
    r["nota"] = ("Os fatores de emissão são do poliéster; para algodão ou misturas informe os fatores do seu fornecedor. "
                 "A reciclagem mecânica exige aparas separadas por fibra e cor.")
    return r


# ----------------------------------------------------------------------------- 7. passaporte digital do produto
def passaporte(lote, kpis, ef_fibra_kg_kg, fonte_dados="médias da calibração da planta"):
    """lote: dict com id, cliente, artigo, fibra, composicao, massa_t. kpis: intensidades por tonelada. Devolve o passaporte e o selo SHA-256."""
    m = float(lote["massa_t"])
    ele = kpis["eletr_kwh_t"] * m
    gas = kpis.get("gn_m3_t", 0.0) * m
    agua = kpis.get("agua_m3_t", float("nan")) * m
    ef = v("ef_sin_2023")
    co2_en = gas * EF_GN_KG_M3 + ele * ef / 1000
    co2_fibra = m * 1000 * ef_fibra_kg_kg
    p = {
        "tipo_documento": "Passaporte digital de produto (modelo de demonstração, não oficial)",
        "emitido_em": datetime.now().isoformat(timespec="seconds"),
        "identificacao": {"lote": lote["id"], "cliente": lote.get("cliente", ""), "artigo": lote.get("artigo", ""),
                          "massa_t": m, "composicao": lote.get("composicao", "")},
        "pegada_do_lote": {"eletricidade_kwh": round(ele, 1), "gas_natural_m3": round(gas, 1),
                           "agua_m3": None if agua != agua else round(agua, 1),
                           "co2e_energia_kg": round(co2_en, 1), "co2e_fibra_kg": round(co2_fibra, 1),
                           "co2e_total_kg": round(co2_en + co2_fibra, 1),
                           "co2e_kg_por_kg_tecido": round((co2_en + co2_fibra) / (m * 1000), 3) if m else None},
        "metodo": {"fonte_dos_dados": fonte_dados, "fator_rede_kgco2_mwh": ef, "fator_gas_kgco2_m3": round(EF_GN_KG_M3, 3),
                   "fator_fibra_kgco2e_kg": ef_fibra_kg_kg,
                   "observacao": "Valores por lote estimados a partir de intensidades médias; para auditoria, use medição por lote."},
    }
    canon = json.dumps(p, sort_keys=True, ensure_ascii=False).encode("utf-8")
    p["selo_integridade_sha256"] = hashlib.sha256(canon).hexdigest()
    return p


def passaporte_markdown(p):
    i, g, m = p["identificacao"], p["pegada_do_lote"], p["metodo"]
    return "\n".join([
        f"# {p['tipo_documento']}", "", f"Emitido em: {p['emitido_em']}", "",
        "## Identificação", f"- Lote: {i['lote']}", f"- Cliente: {i['cliente']}", f"- Artigo: {i['artigo']}",
        f"- Composição: {i['composicao']}", f"- Massa: {i['massa_t']} t", "",
        "## Pegada do lote", f"- Eletricidade: {g['eletricidade_kwh']} kWh", f"- Gás natural: {g['gas_natural_m3']} m³",
        f"- Água: {g['agua_m3']} m³", f"- CO₂e da energia: {g['co2e_energia_kg']} kg", f"- CO₂e da fibra: {g['co2e_fibra_kg']} kg",
        f"- **CO₂e total: {g['co2e_total_kg']} kg ({g['co2e_kg_por_kg_tecido']} kg por kg de tecido)**", "",
        "## Método", f"- Fonte dos dados: {m['fonte_dos_dados']}", f"- Fator da rede: {m['fator_rede_kgco2_mwh']} kgCO₂/MWh",
        f"- Fator do gás: {m['fator_gas_kgco2_m3']} kgCO₂/m³", f"- Fator da fibra: {m['fator_fibra_kgco2e_kg']} kgCO₂e/kg",
        f"- {m['observacao']}", "", f"Selo de integridade (SHA-256): `{p['selo_integridade_sha256']}`"])


def selo_valido(p):
    q = {k: x for k, x in p.items() if k != "selo_integridade_sha256"}
    return hashlib.sha256(json.dumps(q, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest() == p.get("selo_integridade_sha256")


def compra_coletiva_proposta(demanda_m3_dia, preco_atual, preco_proposto, dias_ano):
    """Economia a partir de uma proposta real da distribuidora (sem hipótese de desconto)."""
    econ = demanda_m3_dia * dias_ano * max(0.0, preco_atual - preco_proposto)
    r = _base(econ, 0.0, 0.0, demanda_m3_dia=demanda_m3_dia, reducao_preco=max(0.0, preco_atual - preco_proposto))
    r["premissas"] = []
    r["nota"] = "A economia vem da proposta formal da distribuidora; confirme prazo e condições do contrato."
    return r
