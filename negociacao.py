"""Negociação multiagente frigorífico–usina–tinturaria com espaço de dados e humano no laço.

Espelha os agentes JADE em java/ (mesmos parâmetros e protocolo):
  N1  usina <-> frigorífico : gate fee g (R$/t) pago pelo frigorífico à usina
  N2  usina <-> tinturaria  : preço do biometano p (R$/m3) e volume V (m3/dia), contrato take-or-pay

Táticas dependentes do tempo (Faratin, Sierra & Jennings, 1998):
  oferta(t) = aspiração + (reserva - aspiração) * (t/T)^(1/beta)
Aceita-se a oferta do oponente se for ao menos tão boa quanto a próxima oferta própria.

Regimes de informação (governança de dados):
  isolado    – cada empresa só conhece dados públicos (registro); oponente estimado por faixas amplas
  espaco     – conectores de espaço de dados trocam agregados com políticas de uso (finalidade,
               retenção, proibição de repasse): previsão de resíduos, faixa de demanda, faixa de custo
  total      – transparência completa (referência teórica; viola sigilo industrial)

Humano no laço (autonomia limitada):
  - a tinturaria só aceita sozinha p <= tarifa do gás; prêmio ESG acima disso exige aprovação do gestor
  - contratos acima de LIMITE_CONSELHO (R$/ano) exigem aprovação do conselho da usina
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .economia import amostrar_econ, custo_nivelado
from .federacao import EF_GN_KG_M3
from .fontes import v

T_RODADAS = 20
LIMITE_CONSELHO = 5e6        # R$/ano
DIAS_OPERACAO_TEX = 300
DEMANDA_TEX = v("gn_textil") * v("textil_t_dia")     # m3/dia de gás da tinturaria de referência (~11.400)

REGIMES = {
    #           sigma da oferta de resíduos | erro de crença sobre o oponente | fração da demanda contratada
    "isolado": {"sigma_res": 0.25, "erro_crenca": 0.30, "frac_volume": 0.50, "exposicao": 0},
    "espaco":  {"sigma_res": 0.08, "erro_crenca": 0.10, "frac_volume": 0.90, "exposicao": 3},
    "total":   {"sigma_res": 0.05, "erro_crenca": 0.00, "frac_volume": 1.00, "exposicao": 15},
}

POLITICAS_USO = {   # políticas no estilo ODRL/IDS aplicadas pelos conectores (regime "espaco")
    "previsao_residuos": {"provedor": "frigorifico", "consumidores": ["usina"], "agregacao": "semanal, ±faixa",
                          "finalidade": "negociacao_DT2", "retencao_dias": 30, "repasse": False},
    "faixa_demanda_gas": {"provedor": "tinturaria", "consumidores": ["usina"], "agregacao": "mensal, faixa 10%",
                          "finalidade": "negociacao_DT2", "retencao_dias": 30, "repasse": False},
    "faixa_custo_bio":   {"provedor": "usina", "consumidores": ["tinturaria", "frigorifico"], "agregacao": "±10%",
                          "finalidade": "negociacao_DT2", "retencao_dias": 30, "repasse": False},
}


class Conector:
    """Conector de espaço de dados: só entrega um ativo se a política de uso permitir."""

    def __init__(self, dono):
        self.dono, self.log = dono, []

    def consultar(self, ativo, consumidor, finalidade, regime):
        pol = POLITICAS_USO.get(ativo)
        ok = (regime == "total") or (regime == "espaco" and pol is not None and pol["provedor"] == self.dono
                                     and consumidor in pol["consumidores"] and finalidade == pol["finalidade"])
        self.log.append((ativo, consumidor, finalidade, "permit" if ok else "deny"))
        return ok


def _oferta(asp, res, t, beta):
    return asp + (res - asp) * (t / T_RODADAS) ** (1.0 / beta)


def negociar(res_comprador, asp_comprador, res_vendedor, asp_vendedor, beta_c=1.0, beta_v=0.5):
    """Barganha alternada de preço. Comprador quer preço baixo; vendedor, alto.
    Retorna (preço, rodada) ou (None, T)."""
    for t in range(T_RODADAS + 1):
        of_v = _oferta(asp_vendedor, res_vendedor, t, beta_v)        # vendedor propõe
        prox_c = _oferta(asp_comprador, res_comprador, min(t + 1, T_RODADAS), beta_c)
        if of_v <= prox_c and of_v <= res_comprador:
            return of_v, t
        of_c = _oferta(asp_comprador, res_comprador, t, beta_c)      # comprador contrapropõe
        prox_v = _oferta(asp_vendedor, res_vendedor, min(t + 1, T_RODADAS), beta_v)
        if of_c >= prox_v and of_c >= res_vendedor:
            return of_c, t
    return None, T_RODADAS


@dataclass
class Resultado:
    acordo: bool
    g: float | None = None
    p: float | None = None
    volume: float = 0.0
    rodadas: int = 0
    rodadas_n1: int = 0
    rodadas_n2: int = 0
    dias: float = 0.0
    escalado: bool = False
    aprovado_humano: bool | None = None
    co2_evitado_t: float = 0.0
    excedente_tex: float = 0.0
    excedente_usina: float = 0.0
    excedente_frig: float = 0.0
    log: list = field(default_factory=list)


def simular_negociacao(regime, n=5000, semente=7, humano=True, preco_carbono=0.0):
    cfg = REGIMES[regime]
    r = np.random.default_rng(semente)
    e = amostrar_econ(n, semente=101)
    esg = r.uniform(0.0, 0.10, n)                       # prêmio ESG que o gestor pode autorizar
    lat = r.uniform(2, 10, n)                            # latência de decisão humana (dias)
    aprova_p = 0.85
    out = []
    for i in range(n):
        ei = {k: x[i] for k, x in e.items()}
        res = Resultado(False)
        # ---------- N1: gate fee (frigorífico paga à usina para destinar resíduos)
        g_res_frig = ei["gate_aterro"]                             # não paga mais do que paga ao aterro hoje
        g_res_usina = 0.0                                          # aceitaria receber de graça
        err = cfg["erro_crenca"]
        asp_usina = g_res_frig * (1 + r.uniform(-err, err))       # crença da usina sobre o teto do frigorífico
        asp_frig = g_res_usina + abs(r.normal(0, err)) * 20       # crença do frigorífico sobre o piso da usina
        g, t1 = negociar(g_res_frig, asp_frig, g_res_usina, asp_usina, beta_c=1.0, beta_v=0.5)
        if g is None:
            out.append(res); continue
        # ---------- N2: biometano (usina vende; tinturaria compra)
        lcob = float(custo_nivelado(ei, g))
        premio_risco = 0.6 * cfg["sigma_res"]                      # risco de faltar resíduo no take-or-pay
        p_res_usina = max(0.0, lcob) * (1 + premio_risco) + 0.05   # margem mínima R$0,05/m3
        tarifa = ei["tarifa_gn"]
        p_aut_tex = tarifa + preco_carbono * EF_GN_KG_M3 / 1000    # autonomia do agente: até a tarifa evitada
        p_res_tex = p_aut_tex * (1 + esg[i]) if humano else p_aut_tex
        asp_tex = p_res_usina * (1 + r.uniform(-err, err))
        asp_usina2 = p_res_tex * (1 + r.uniform(-err, err))
        p, t2 = negociar(p_res_tex, asp_tex, p_res_usina, asp_usina2, beta_c=1.0, beta_v=0.5)
        dias = t1 + t2
        if p is None:
            res.g, res.rodadas, res.dias = g, t1 + t2, dias
            out.append(res); continue
        volume = min(cfg["frac_volume"] * DEMANDA_TEX, v("hub_capacidade") * ei["fc"])
        valor_anual = p * volume * DIAS_OPERACAO_TEX
        # ---------- humano no laço
        precisa = humano and ((p > p_aut_tex) or (valor_anual > LIMITE_CONSELHO))
        if precisa:
            res.escalado = True
            dias += lat[i]
            res.aprovado_humano = bool(r.random() < aprova_p)
            if not res.aprovado_humano:
                res.g, res.p, res.rodadas, res.dias = g, p, t1 + t2, dias
                out.append(res); continue
        res.acordo, res.g, res.p, res.volume, res.rodadas, res.dias = True, g, p, volume, t1 + t2, dias
        res.rodadas_n1, res.rodadas_n2 = t1, t2
        res.co2_evitado_t = volume * DIAS_OPERACAO_TEX * EF_GN_KG_M3 / 1000
        res.excedente_tex = (tarifa - p) * volume * DIAS_OPERACAO_TEX
        res.excedente_usina = (p - lcob) * volume * DIAS_OPERACAO_TEX
        res.excedente_frig = (g_res_frig - g) * v("hub_residuos") * 365 * ei["fc"] * volume / v("hub_capacidade")
        out.append(res)
    return out


def resumir(lista):
    ac = [x for x in lista if x.acordo]
    f = lambda xs: (float(np.mean(xs)) if len(xs) else float("nan"))
    return {
        "taxa_acordo": len(ac) / len(lista),
        "preco_medio": f([x.p for x in ac]),
        "gate_medio": f([x.g for x in ac]),
        "volume_medio": f([x.volume for x in ac]),
        "rodadas": f([x.rodadas for x in ac]),
        "rodadas_n1": f([x.rodadas_n1 for x in ac]),
        "rodadas_n2": f([x.rodadas_n2 for x in ac]),
        "dias": f([x.dias for x in ac]),
        "escalados": float(np.mean([x.escalado for x in lista])),
        "rejeitados_humano": float(np.mean([x.aprovado_humano is False for x in lista])),
        "co2_evitado_t_ano": float(np.mean([x.co2_evitado_t for x in lista])),        # média incluindo falhas
        "excedente_tex_mi": f([x.excedente_tex / 1e6 for x in ac]),
        "excedente_usina_mi": f([x.excedente_usina / 1e6 for x in ac]),
        "excedente_frig_mi": f([x.excedente_frig / 1e6 for x in ac]),
        "acordos_com_premio": float(np.mean([x.acordo and x.escalado and x.p is not None for x in lista])),
    }


def experimento(n=5000):
    res = {}
    for reg in REGIMES:
        for hum in (False, True):
            res[f"{reg}|{'humano' if hum else 'autonomo'}"] = resumir(simular_negociacao(reg, n, humano=hum))
    return res
