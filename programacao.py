"""Programação colaborativa de lotes de tingimento com tarifa de energia e tetos compartilhados de gás e água/efluente.

Problema: várias tinturarias (plantas) de um mesmo polo programam seus lotes em jatos/ramas. Cada lote consome eletricidade
(tarifa por horário), gás e água. O polo tem tetos horários compartilhados (contrato de gás e capacidade da ETE coletiva).
Quatro modos de decisão são comparados:

  isolado     cada planta programa por prazo de entrega (EDD) e começa assim que a máquina libera (prática comum).
  otimizado   cada planta otimiza sozinha o próprio custo, sem olhar o polo.
  federado    cada planta otimiza o próprio problema recebendo apenas preços (sinais) calculados pelo coordenador a partir da
              carga horária agregada. Nenhuma planta vê pedidos de outra.
  centralizado  um único otimizador vê todos os pedidos (limite superior de desempenho, exige compartilhar dados).

O tempo é discreto em horas. Consumos de cada lote são distribuídos de forma uniforme na duração.
"""
from __future__ import annotations

import dataclasses
import io
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import fontes

TONS = {0: "claro", 1: "médio", 2: "escuro"}


@dataclass
class Lote:
    id: str
    planta: int
    kg: float
    tom: int              # 0 claro, 1 médio, 2 escuro
    dur: int              # horas
    pronto: int           # hora em que o material está disponível
    prazo: int            # hora de entrega
    gas: float            # m3 no lote
    kwh: float            # kWh no lote
    agua: float           # m3 no lote


@dataclass
class Instancia:
    H: int
    plantas: list                     # nomes
    maquinas: list                    # nº de máquinas por planta
    lotes: list
    tar_e: np.ndarray                 # R$/kWh por hora (len H)
    tar_gas: float = 0.0              # R$/m3
    tar_agua: float = 0.0             # R$/m3 (água + efluente)
    cap_gas: float = np.inf           # m3/h compartilhado no polo
    cap_agua: float = np.inf          # m3/h compartilhado no polo
    limp_h: int = 1                   # horas de limpeza ao passar de tom escuro para claro
    limp_agua: float = 0.0            # m3 de água por limpeza
    pen_atraso: float = 0.0           # R$ por kg e por hora de atraso
    ef_eletr: float = 0.0             # kgCO2e/kWh
    ef_gas: float = 0.0               # kgCO2e/m3
    origem: str = ""


# ------------------------------------------------------------------------------------------------ fatores de referência
def fatores_referencia():
    """Fatores de emissão do registro do modelo: rede elétrica (SIN 2023) e gás natural (fator por TJ e PCI)."""
    ef_e = fontes.IDX["ef_sin_2023"].valor / 1000.0          # kgCO2/kWh
    ef_tj = fontes.IDX["ef_gn_tj"].valor                      # tCO2/TJ = kgCO2/GJ
    pci_gj_m3 = 0.0359                                         # GJ/m3: confirmar na fatura da distribuidora
    return ef_e, ef_tj * pci_gj_m3


def tarifa_horaria(H, fp, ponta, ponta_h=(18, 19, 20), dias_uteis_apenas=True, inicio_dow=0):
    """Perfil horário de R$/kWh: fora de ponta e ponta nos dias úteis (inicio_dow: 0 = segunda)."""
    t = np.full(H, float(fp))
    for h in range(H):
        d = (inicio_dow + h // 24) % 7
        if h % 24 in ponta_h and (d < 5 or not dias_uteis_apenas):
            t[h] = ponta
    return t


# ------------------------------------------------------------------------------------------------ decodificador
def _janela_custo(pre, s, d):
    return pre[s + d] - pre[s]


def decodificar(inst: Instancia, lotes, perm, bg_gas=None, bg_agua=None, lam_gas=None, lam_agua=None,
                teto_gas=None, teto_agua=None, espera_max=24, so_planta=None):
    """Aloca os lotes na ordem `perm` (lista de índices em `lotes`): máquina e hora de início de menor custo.

    bg_*: carga horária de terceiros (só o agregado). lam_*: preço-sombra por hora (R$/m3). teto_*: capacidade residual horária.
    Devolve dict com agenda e cargas horárias da própria seleção de lotes.
    """
    H = inst.H
    zeros = np.zeros(H)
    bg_gas = zeros if bg_gas is None else bg_gas
    bg_agua = zeros if bg_agua is None else bg_agua
    lg = zeros if lam_gas is None else lam_gas
    la = zeros if lam_agua is None else lam_agua
    tg = np.full(H, np.inf) if teto_gas is None else teto_gas
    ta = np.full(H, np.inf) if teto_agua is None else teto_agua
    pre_e = np.concatenate([[0.0], np.cumsum(inst.tar_e)])
    pre_lg = np.concatenate([[0.0], np.cumsum(lg)])
    pre_la = np.concatenate([[0.0], np.cumsum(la)])
    plantas = sorted({lotes[i].planta for i in perm})
    livre = {p: np.zeros(inst.maquinas[p], dtype=int) for p in plantas}
    ult_tom = {p: np.full(inst.maquinas[p], -1, dtype=int) for p in plantas}
    carga_g, carga_a = np.zeros(H), np.zeros(H)
    agenda = {}
    for i in perm:
        L = lotes[i]
        d = max(1, L.dur)
        melhor = None
        for m in range(inst.maquinas[L.planta]):
            limp = inst.limp_h if ult_tom[L.planta][m] > L.tom else 0
            ini = max(L.pronto, int(livre[L.planta][m]) + limp)
            folga = max(0, L.prazo - d - ini)
            fim_busca = min(inst.H - d, ini + min(max(folga, 0), espera_max) if espera_max is not None else inst.H - d)
            if ini > inst.H - d:
                continue
            for s in range(ini, max(ini, fim_busca) + 1):
                g, a = L.gas / d, L.agua / d
                if limp:
                    a_total = a + inst.limp_agua / d
                else:
                    a_total = a
                viol = 0.0
                jan_g = carga_g[s:s + d] + bg_gas[s:s + d] + g
                jan_a = carga_a[s:s + d] + bg_agua[s:s + d] + a_total
                viol = float(np.maximum(jan_g - tg[s:s + d], 0).sum() + np.maximum(jan_a - ta[s:s + d], 0).sum())
                custo = (L.kwh / d) * _janela_custo(pre_e, s, d) + g * (inst.tar_gas * d + _janela_custo(pre_lg, s, d)) \
                    + a_total * (inst.tar_agua * d + _janela_custo(pre_la, s, d))
                atraso = max(0, s + d - L.prazo)
                custo += inst.pen_atraso * L.kg * atraso + 1e6 * viol
                if melhor is None or custo < melhor[0]:
                    melhor = (custo, m, s, limp, a_total)
        if melhor is None:                       # sem espaço no horizonte: aloca no fim, marcando como atrasado
            m = int(np.argmin(livre[L.planta]))
            s = max(0, min(inst.H - d, int(livre[L.planta][m])))
            melhor = (0.0, m, s, 0, L.agua / d)
        _, m, s, limp, a_tot = melhor
        carga_g[s:s + d] += L.gas / d
        carga_a[s:s + d] += a_tot
        livre[L.planta][m] = s + d
        ult_tom[L.planta][m] = L.tom
        agenda[i] = (m, s, s + d, bool(limp))
    return {"agenda": agenda, "gas": carga_g, "agua": carga_a}


def decodificar_asap(inst, lotes, perm):
    """Prática comum: ordem EDD, cada lote entra na primeira máquina livre, o mais cedo possível, sem olhar tarifa nem teto."""
    return decodificar(inst, lotes, perm, espera_max=0)


# ------------------------------------------------------------------------------------------------ métricas
def metricas(inst, lotes, agenda, so_polo=True):
    H = inst.H
    cg, ca, ce = np.zeros(H), np.zeros(H), np.zeros(H)
    atraso_kg_h, n_atrasados, custo_limp = 0.0, 0, 0.0
    for i, (m, s, f, limp) in agenda.items():
        L = lotes[i]
        d = f - s
        cg[s:f] += L.gas / d
        a = L.agua / d + (inst.limp_agua / d if limp else 0.0)
        ca[s:f] += a
        ce[s:f] += L.kwh / d
        at = max(0, f - L.prazo)
        atraso_kg_h += at * L.kg
        n_atrasados += int(at > 0)
    custo_e = float((ce * inst.tar_e).sum())
    custo_g = float(cg.sum() * inst.tar_gas)
    custo_a = float(ca.sum() * inst.tar_agua)
    co2 = float(ce.sum() * inst.ef_eletr + cg.sum() * inst.ef_gas)
    exc_g = np.maximum(cg - inst.cap_gas, 0)
    exc_a = np.maximum(ca - inst.cap_agua, 0)
    return {"custo_energia_r": custo_e, "custo_gas_r": custo_g, "custo_agua_r": custo_a,
            "custo_total_r": custo_e + custo_g + custo_a, "co2e_kg": co2,
            "atraso_kg_h": float(atraso_kg_h), "lotes_atrasados": int(n_atrasados),
            "pico_gas_m3_h": float(cg.max()), "pico_agua_m3_h": float(ca.max()),
            "horas_acima_teto_gas": int((exc_g > 1e-9).sum()), "horas_acima_teto_agua": int((exc_a > 1e-9).sum()),
            "excesso_gas_m3": float(exc_g.sum()), "excesso_agua_m3": float(exc_a.sum()),
            "makespan_h": int(max(f for _, _, f, _ in agenda.values())) if agenda else 0,
            "carga_gas": cg, "carga_agua": ca, "carga_eletr": ce}


def _objetivo(inst, lotes, res, lam=None):
    m = metricas(inst, lotes, res["agenda"])
    return m["custo_total_r"] + inst.pen_atraso * m["atraso_kg_h"]


# ------------------------------------------------------------------------------------------------ busca local
def _otimizar_planta(inst, lotes, idx, rng, iters, perm0=None, **kw):
    """Recozimento simulado sobre a ordem dos lotes de uma planta (ou de todas, no modo centralizado)."""
    perm = list(perm0) if perm0 is not None else sorted(idx, key=lambda i: lotes[i].prazo)
    def avaliar(p):
        r = decodificar(inst, lotes, p, **kw)
        return _objetivo_local(inst, lotes, r, kw), r
    atual, r_atual = avaliar(perm)
    melhor, r_melhor, p_melhor = atual, r_atual, list(perm)
    T0 = max(1.0, abs(atual) * 0.01)
    n = len(perm)
    for k in range(iters):
        if n < 2:
            break
        T = T0 * (1 - k / iters) + 1e-9
        q = list(perm)
        if rng.random() < 0.5:
            a, b = rng.choice(n, 2, replace=False)
            q[a], q[b] = q[b], q[a]
        else:
            a, b = rng.choice(n, 2, replace=False)
            q.insert(b, q.pop(a))
        v, r = avaliar(q)
        if v < atual or rng.random() < np.exp((atual - v) / T):
            perm, atual, r_atual = q, v, r
            if v < melhor:
                melhor, r_melhor, p_melhor = v, r, list(q)
    return p_melhor, r_melhor


def _objetivo_local(inst, lotes, r, kw):
    """Custo próprio (energia, gás, água, atraso) + preço-sombra + penalidade pesada por exceder o teto residual."""
    H = inst.H
    ce = np.zeros(H)
    cg, ca = r["gas"], r["agua"]
    atr = 0.0
    for i, (m, s, f, limp) in r["agenda"].items():
        L = lotes[i]
        ce[s:f] += L.kwh / (f - s)
        atr += max(0, f - L.prazo) * L.kg
    v = float((ce * inst.tar_e).sum() + cg.sum() * inst.tar_gas + ca.sum() * inst.tar_agua + inst.pen_atraso * atr)
    if kw.get("lam_gas") is not None:
        v += float((cg * kw["lam_gas"]).sum())
    if kw.get("lam_agua") is not None:
        v += float((ca * kw["lam_agua"]).sum())
    tg, ta = kw.get("teto_gas"), kw.get("teto_agua")
    bgg, bga = kw.get("bg_gas"), kw.get("bg_agua")
    if tg is not None:
        v += 1e6 * float(np.maximum(cg + (0 if bgg is None else bgg) - tg, 0).sum())
    if ta is not None:
        v += 1e6 * float(np.maximum(ca + (0 if bga is None else bga) - ta, 0).sum())
    return v


# ------------------------------------------------------------------------------------------------ modos
def _por_planta(inst):
    return {p: [i for i, L in enumerate(inst.lotes) if L.planta == p] for p in range(len(inst.plantas))}


def _juntar(inst, partes):
    ag = {}
    for r in partes:
        ag.update(r["agenda"])
    return ag


def resolver(inst: Instancia, modo="federado", iters=300, rodadas=8, seed=0):
    rng = np.random.default_rng(seed)
    lotes, H = inst.lotes, inst.H
    pp = _por_planta(inst)
    info = {"modo": modo}
    if modo == "isolado":
        partes = [decodificar_asap(inst, lotes, sorted(ix, key=lambda i: lotes[i].prazo)) for ix in pp.values()]
        info["dados_compartilhados"] = "nenhum"
    elif modo == "otimizado":
        partes = [_otimizar_planta(inst, lotes, ix, rng, iters)[1] for ix in pp.values()]
        info["dados_compartilhados"] = "nenhum"
    elif modo == "centralizado":
        tg = np.full(H, inst.cap_gas)
        ta = np.full(H, inst.cap_agua)
        _, r = _otimizar_planta(inst, lotes, list(range(len(lotes))), rng, iters * len(pp), teto_gas=tg, teto_agua=ta)
        partes = [r]
        info["dados_compartilhados"] = "todos os pedidos de todas as plantas"
    elif modo == "federado":
        # Decomposição por cotas: o coordenador divide o teto horário em cotas por planta (a soma nunca passa do teto).
        # Cada planta otimiza sozinha dentro da própria cota e devolve apenas sua carga horária e o atraso total.
        # Folgas de cota são realocadas para as plantas que atrasaram. Nenhuma planta vê pedidos de outra.
        nP = len(pp)
        kg_p = np.array([sum(lotes[i].kg for i in ix) for ix in pp.values()], dtype=float)
        part = kg_p / kg_p.sum()
        qg = np.array([np.full(H, inst.cap_gas * part[p]) for p in range(nP)])
        qa = np.array([np.full(H, inst.cap_agua * part[p]) for p in range(nP)])
        perms = {p: sorted(ix, key=lambda i: lotes[i].prazo) for p, ix in pp.items()}
        melhor, hist = None, []
        for k in range(rodadas):
            res = {}
            for p in pp:
                perms[p], res[p] = _otimizar_planta(inst, lotes, pp[p], rng, iters, perm0=perms[p], teto_gas=qg[p], teto_agua=qa[p])
            late = np.array([sum(max(0, f - lotes[i].prazo) * lotes[i].kg for i, (m, s_, f, l) in res[p]["agenda"].items()) for p in pp])
            agenda = _juntar(inst, res.values())
            m = metricas(inst, lotes, agenda)
            hist.append(float(late.sum()))
            chave = (m["horas_acima_teto_gas"] + m["horas_acima_teto_agua"], m["atraso_kg_h"], m["custo_total_r"])
            if melhor is None or chave < melhor[0]:
                melhor = (chave, agenda)
            cargas = {"gas": np.array([res[p]["gas"] for p in pp]), "agua": np.array([res[p]["agua"] for p in pp])}
            falta = {"gas": np.maximum(cargas["gas"] - qg, 0), "agua": np.maximum(cargas["agua"] - qa, 0)}
            if late.sum() == 0 and falta["gas"].sum() + falta["agua"].sum() < 1e-9:
                break
            w = late / late.sum() if late.sum() > 0 else np.ones(nP) / nP
            for q, rec in ((qg, "gas"), (qa, "agua")):
                carga, need = cargas[rec], falta[rec]
                doa = 0.7 * np.maximum(q - carga, 0)
                pool = doa.sum(0)
                q -= doa
                n_tot = need.sum(0)
                dar = np.minimum(pool, n_tot)                       # primeiro cobre o excesso hora a hora
                with np.errstate(invalid="ignore", divide="ignore"):
                    q += np.where(n_tot > 0, need / np.where(n_tot > 0, n_tot, 1), 0) * dar
                q += np.outer(w, pool - dar)                        # o resto vai para quem atrasou
        if melhor[0][0] > 0:                          # reparo: cada planta, em sequência, respeita a folga que as demais deixam
            ag = melhor[1]
            for _ in range(2):
                for p in pp:
                    outros = {i: v for i, v in ag.items() if lotes[i].planta != p}
                    og, oa = np.zeros(H), np.zeros(H)
                    for i, (m_, s_, f_, l_) in outros.items():
                        og[s_:f_] += lotes[i].gas / (f_ - s_)
                        oa[s_:f_] += lotes[i].agua / (f_ - s_) + (inst.limp_agua / (f_ - s_) if l_ else 0.0)
                    pr, rr = _otimizar_planta(inst, lotes, pp[p], rng, iters, perm0=perms[p], bg_gas=og, bg_agua=oa,
                                              teto_gas=np.full(H, inst.cap_gas), teto_agua=np.full(H, inst.cap_agua))
                    perms[p] = pr
                    ag = {**outros, **rr["agenda"]}
                m = metricas(inst, lotes, ag)
                chave = (m["horas_acima_teto_gas"] + m["horas_acima_teto_agua"], m["atraso_kg_h"], m["custo_total_r"])
                if chave < melhor[0]:
                    melhor = (chave, ag)
                if chave[0] == 0:
                    break
        partes = [{"agenda": melhor[1]}]
        info["dados_compartilhados"] = "só a carga horária de gás e água e o atraso total de cada planta"
        info["rodadas"] = len(hist)
        info["atraso_por_rodada"] = hist
    else:
        raise ValueError(modo)
    agenda = _juntar(inst, partes)
    m = metricas(inst, lotes, agenda)
    m.update(info)
    m["agenda"] = agenda
    return m


def comparar(inst, modos=("isolado", "otimizado", "federado", "centralizado"), iters=300, seed=0):
    return {md: resolver(inst, md, iters=iters, seed=seed) for md in modos}


def tabela_comparacao(res):
    chaves = [("custo_total_r", "Custo total (R$)"), ("co2e_kg", "CO₂e (kg)"), ("atraso_kg_h", "Atraso (kg·h)"),
              ("lotes_atrasados", "Lotes atrasados"), ("pico_gas_m3_h", "Pico de gás (m³/h)"), ("pico_agua_m3_h", "Pico de água (m³/h)"),
              ("horas_acima_teto_gas", "Horas acima do teto de gás"), ("horas_acima_teto_agua", "Horas acima do teto de água"),
              ("dados_compartilhados", "Dados compartilhados")]
    return pd.DataFrame({md: {rot: r.get(k) for k, rot in chaves} for md, r in res.items()})


def verificar_agenda(inst, agenda):
    """Auditoria: nenhuma sobreposição de máquina, janela de disponibilidade respeitada, horizonte respeitado."""
    erros = []
    por_maq = {}
    for i, (m, s, f, limp) in agenda.items():
        L = inst.lotes[i]
        if s < L.pronto:
            erros.append(f"{L.id}: começa antes de o material estar pronto")
        if f > inst.H or s < 0:
            erros.append(f"{L.id}: fora do horizonte")
        if f - s != max(1, L.dur):
            erros.append(f"{L.id}: duração diferente da informada")
        por_maq.setdefault((L.planta, m), []).append((s, f, L.id))
    for k, v in por_maq.items():
        v.sort()
        for (s1, f1, a), (s2, f2, b) in zip(v, v[1:]):
            if s2 < f1:
                erros.append(f"máquina {k}: {a} e {b} se sobrepõem")
    if len(agenda) != len(inst.lotes):
        erros.append("há lotes sem agenda")
    return erros


# ------------------------------------------------------------------------------------------------ instância sintética (demonstração e experimentos)
def gerar_instancia(seed=0, n_plantas=3, lotes_por_planta=18, H=168, maq=(3, 2, 3), fracao_teto=0.8,
                    tar_fp=0.55, tar_ponta=2.4, tar_gas=None, tar_agua=9.0, pen_atraso=0.02):
    """Instância SINTÉTICA para demonstração. Consumos específicos vêm do registro (média de SC); tarifas e penalidade são parâmetros."""
    rng = np.random.default_rng(seed)
    kwh_kg = fontes.IDX["eletr_textil"].valor / 1000.0
    gas_kg = fontes.IDX["gn_textil"].valor / 1000.0
    agua_kg = 0.170
    tar_gas = fontes.IDX["tarifa_gn_ind"].valor if tar_gas is None else tar_gas
    lotes = []
    for p in range(n_plantas):
        for k in range(lotes_por_planta):
            kg = float(rng.choice([300, 450, 600, 800, 1000, 1200]))
            dur = int(rng.integers(5, 11))
            pronto = int(rng.integers(0, H - 60))
            prazo = int(min(H, pronto + dur + rng.integers(12, 72)))
            var = rng.normal(1, 0.08, 3).clip(0.8, 1.2)
            lotes.append(Lote(f"P{p+1}-L{k+1:02d}", p, kg, int(rng.integers(0, 3)), dur, pronto, prazo,
                              kg * gas_kg * var[0], kg * kwh_kg * var[1], kg * agua_kg * var[2]))
    ef_e, ef_g = fatores_referencia()
    inst = Instancia(H, [f"Planta {chr(65+p)}" for p in range(n_plantas)], list(maq[:n_plantas]) + [2] * max(0, n_plantas - len(maq)),
                     lotes, tarifa_horaria(H, tar_fp, tar_ponta), tar_gas, tar_agua, np.inf, np.inf, 1, 2.0, pen_atraso, ef_e, ef_g,
                     origem="sintética (demonstração)")
    base = resolver(inst, "isolado")
    inst.cap_gas = float(base["pico_gas_m3_h"] * fracao_teto)
    inst.cap_agua = float(base["pico_agua_m3_h"] * fracao_teto)
    return inst


# ------------------------------------------------------------------------------------------------ importação do ERP/PCP (Excel)
COLUNAS_PEDIDOS = ["id", "planta", "kg", "tonalidade", "duracao_h", "pronto_h", "prazo_h", "gas_m3", "eletr_kwh", "agua_m3"]


def modelo_excel(inst=None):
    """Planilha-modelo com abas Pedidos, Plantas, Tarifa e Parametros (exemplo preenchido a partir de uma instância)."""
    inst = inst or gerar_instancia(0, 2, 5)
    ped = pd.DataFrame([{"id": L.id, "planta": inst.plantas[L.planta], "kg": L.kg, "tonalidade": TONS[L.tom], "duracao_h": L.dur,
                         "pronto_h": L.pronto, "prazo_h": L.prazo, "gas_m3": round(L.gas, 1), "eletr_kwh": round(L.kwh, 1),
                         "agua_m3": round(L.agua, 2)} for L in inst.lotes])
    pl = pd.DataFrame({"planta": inst.plantas, "maquinas": inst.maquinas})
    tar = pd.DataFrame({"hora_do_dia": range(24), "r_kwh": [float(inst.tar_e[h]) for h in range(24)]})
    par = pd.DataFrame([("horizonte_h", inst.H), ("tarifa_gas_r_m3", inst.tar_gas), ("tarifa_agua_efluente_r_m3", inst.tar_agua),
                        ("teto_gas_m3_h", inst.cap_gas), ("teto_agua_m3_h", inst.cap_agua), ("limpeza_h", inst.limp_h),
                        ("limpeza_agua_m3", inst.limp_agua), ("multa_atraso_r_kg_h", inst.pen_atraso),
                        ("dia_da_semana_inicio_0seg", 0)], columns=["parametro", "valor"])
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        ped.to_excel(w, "Pedidos", index=False)
        pl.to_excel(w, "Plantas", index=False)
        tar.to_excel(w, "Tarifa", index=False)
        par.to_excel(w, "Parametros", index=False)
    return bio.getvalue()


def ler_excel(arquivo):
    """Lê a planilha-modelo e devolve (Instancia, avisos). Lotes sem gás/energia/água informados ficam fora (não se estima por hipótese)."""
    x = pd.ExcelFile(arquivo)
    ped, pl, tar, par = (x.parse(n) for n in ("Pedidos", "Plantas", "Tarifa", "Parametros"))
    av = []
    p = dict(zip(par["parametro"], par["valor"]))
    H = int(p["horizonte_h"])
    nomes = list(pl["planta"])
    inv = {v: k for k, v in TONS.items()}
    lotes = []
    for _, r in ped.iterrows():
        if r["planta"] not in nomes:
            av.append(f"{r['id']}: planta '{r['planta']}' não consta na aba Plantas")
            continue
        if any(pd.isna(r[c]) for c in COLUNAS_PEDIDOS):
            av.append(f"{r['id']}: há campo vazio (gás, energia e água devem vir de medição ou ficha técnica); lote ignorado")
            continue
        tom = inv.get(str(r["tonalidade"]).strip().lower())
        if tom is None:
            av.append(f"{r['id']}: tonalidade deve ser claro, médio ou escuro")
            continue
        lotes.append(Lote(str(r["id"]), nomes.index(r["planta"]), float(r["kg"]), tom, int(r["duracao_h"]), int(r["pronto_h"]),
                          int(r["prazo_h"]), float(r["gas_m3"]), float(r["eletr_kwh"]), float(r["agua_m3"])))
    t24 = dict(zip(tar["hora_do_dia"], tar["r_kwh"]))
    dow0 = int(p.get("dia_da_semana_inicio_0seg", 0))
    tar_e = np.array([float(t24[h % 24]) for h in range(H)])
    ef_e, ef_g = fatores_referencia()
    inst = Instancia(H, nomes, [int(m) for m in pl["maquinas"]], lotes, tar_e, float(p["tarifa_gas_r_m3"]), float(p["tarifa_agua_efluente_r_m3"]),
                     float(p["teto_gas_m3_h"]), float(p["teto_agua_m3_h"]), int(p["limpeza_h"]), float(p["limpeza_agua_m3"]),
                     float(p["multa_atraso_r_kg_h"]), ef_e, ef_g, origem="planilha do ERP/PCP")
    for L in lotes:
        if L.prazo - L.pronto < L.dur:
            av.append(f"{L.id}: prazo menor que pronto + duração (não há como cumprir)")
    return inst, av
