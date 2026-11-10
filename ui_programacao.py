"""Aba Streamlit: programação colaborativa de lotes de tingimento."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from . import programacao as P

NOMES = {"isolado": "Isolado (prática comum)", "otimizado": "Otimizado sozinho", "federado": "Federado (cotas)",
         "centralizado": "Centralizado (limite)"}


def _graf_carga(inst, res, chave, cap, rot):
    fig, ax = plt.subplots(figsize=(8, 2.8))
    for md, r in res.items():
        ax.plot(r[chave], label=NOMES[md], lw=1.2)
    if np.isfinite(cap):
        ax.axhline(cap, color="k", ls="--", lw=1, label="teto do polo")
    ax.set_xlabel("hora do horizonte")
    ax.set_ylabel(rot)
    ax.legend(fontsize=7, ncol=3)
    fig.tight_layout()
    return fig


def _gantt(inst, r):
    fig, ax = plt.subplots(figsize=(8, 0.5 + 0.28 * sum(inst.maquinas)))
    y, ticks, cores = 0, [], {0: "#9ec5e8", 1: "#5b94c7", 2: "#1f4e79"}
    for p, nome in enumerate(inst.plantas):
        for m in range(inst.maquinas[p]):
            for i, (mm, s, f, limp) in r["agenda"].items():
                L = inst.lotes[i]
                if L.planta == p and mm == m:
                    atrasado = f > L.prazo
                    ax.barh(y, f - s, left=s, color=cores[L.tom], edgecolor="red" if atrasado else "white", lw=1.2)
            ticks.append((y, f"{nome[-1]}{m+1}"))
            y += 1
    ax.set_yticks([t[0] for t in ticks], [t[1] for t in ticks], fontsize=7)
    ax.set_xlabel("hora (borda vermelha = entrega atrasada; azul claro a escuro = tom)")
    ax.invert_yaxis()
    fig.tight_layout()
    return fig


def aba_programacao():
    st.subheader("Programação colaborativa de lotes de tingimento")
    st.write("Esta ferramenta decide **em que máquina e em que horário** entra cada lote para gastar menos com energia na ponta e para "
             "que as tinturarias do polo **não estourem juntas** o contrato de gás e a capacidade da ETE coletiva, sem que uma empresa "
             "veja os pedidos da outra. Usa dados que já existem no ERP/PCP; não precisa de sensores novos.")
    with st.expander("Passo a passo", expanded=True):
        st.markdown("1. Baixe a planilha-modelo e preencha: **Pedidos** (um lote por linha, com gás, energia e água medidos ou da ficha técnica), "
                    "**Plantas** (nº de máquinas), **Tarifa** (R$/kWh por hora do dia) e **Parametros** (tetos e preços).\n"
                    "2. Envie a planilha aqui (ou use o exemplo sintético para ver como funciona).\n"
                    "3. Clique em *Programar* e compare os quatro modos.\n"
                    "4. Baixe a agenda do modo escolhido.")
    st.download_button("⬇️ Planilha-modelo (Excel)", P.modelo_excel(), "modelo_programacao.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    up = st.file_uploader("Planilha preenchida", type="xlsx")
    if up is not None:
        try:
            inst, av = P.ler_excel(up)
            for a in av:
                st.warning(a)
            st.session_state["inst_prog"] = inst
        except Exception as e:
            st.error(f"Não consegui ler a planilha: {e}")
    c1, c2, c3 = st.columns(3)
    with c1:
        n_pl = st.number_input("Exemplo: nº de empresas", 2, 5, 3)
    with c2:
        n_lt = st.number_input("Exemplo: lotes por empresa", 6, 30, 14)
    with c3:
        frac = st.slider("Exemplo: teto = fração do pico atual", 0.5, 1.0, 0.8)
    if st.button("Usar exemplo sintético"):
        st.session_state["inst_prog"] = P.gerar_instancia(0, int(n_pl), int(n_lt), fracao_teto=frac)
    inst = st.session_state.get("inst_prog")
    if inst is None:
        st.info("Envie uma planilha ou use o exemplo sintético.")
        return
    st.caption(f"Dados: **{inst.origem}**. {len(inst.lotes)} lotes, {len(inst.plantas)} plantas, horizonte de {inst.H} h. "
               f"Teto de gás {inst.cap_gas:,.0f} m³/h, teto de água {inst.cap_agua:,.0f} m³/h.")
    if "sint" in inst.origem:
        st.warning("Exemplo sintético: serve para demonstrar o método. Não use estes números como resultado da pesquisa.")
    it = st.slider("Esforço de busca (mais alto demora mais)", 60, 400, 150, step=30)
    if st.button("Programar", type="primary"):
        with st.spinner("Calculando as quatro programações…"):
            res = P.comparar(inst, iters=it)
        st.session_state["res_prog"] = res
    res = st.session_state.get("res_prog")
    if not res:
        return
    for md, r in res.items():
        er = P.verificar_agenda(inst, r["agenda"])
        if er:
            st.error(f"{NOMES[md]}: {er[0]}")
    tab = P.tabela_comparacao(res).rename(columns=NOMES)
    st.dataframe(tab.style.format(lambda v: f"{v:,.1f}" if isinstance(v, float) else v))
    iso, fed = res["isolado"], res["federado"]
    st.success(f"No modo federado o polo ficou **{fed['horas_acima_teto_gas']} h** acima do teto de gás e **{fed['horas_acima_teto_agua']} h** "
               f"acima do teto de água (no isolado: {iso['horas_acima_teto_gas']} h e {iso['horas_acima_teto_agua']} h). "
               f"O custo variou {100 * (fed['custo_total_r'] - iso['custo_total_r']) / iso['custo_total_r']:+.1f}% em relação ao isolado.")
    st.pyplot(_graf_carga(inst, res, "carga_gas", inst.cap_gas, "gás (m³/h)"))
    st.pyplot(_graf_carga(inst, res, "carga_agua", inst.cap_agua, "água (m³/h)"))
    modo = st.selectbox("Ver agenda de", list(res), format_func=NOMES.get, index=2)
    st.pyplot(_gantt(inst, res[modo]))
    ag = pd.DataFrame([{"lote": inst.lotes[i].id, "empresa": inst.plantas[inst.lotes[i].planta], "maquina": m + 1, "inicio_h": s, "fim_h": f,
                        "prazo_h": inst.lotes[i].prazo, "atrasado": f > inst.lotes[i].prazo, "limpeza_antes": l}
                       for i, (m, s, f, l) in sorted(res[modo]["agenda"].items(), key=lambda kv: kv[1][1])])
    st.download_button("⬇️ Agenda (CSV)", ag.to_csv(index=False), f"agenda_{modo}.csv")
    with st.expander("Como ler cada resultado"):
        st.markdown(
            "- **Isolado:** cada empresa programa por prazo e começa assim que a máquina libera. É o retrato da prática comum.\n"
            "- **Otimizado sozinho:** cada empresa busca o menor custo, mas sem olhar o polo. Pode economizar, mas os picos continuam coincidindo.\n"
            "- **Federado:** um coordenador divide o teto horário em cotas e cada empresa programa dentro da sua. Compartilha só a carga horária "
            "e o atraso total. A soma das cotas nunca passa do teto, então não estoura o contrato.\n"
            "- **Centralizado:** um único otimizador vê todos os pedidos. Serve de referência do que é possível, mas exige abrir os dados.\n"
            "- **CO₂e:** nesta versão o fator da rede é constante, então mudar o horário não muda a emissão. Para ganho de CO₂e por horário "
            "é preciso o fator horário da rede (a incluir).\n"
            "- **Atraso (kg·h):** soma de quilos entregues depois do prazo vezes as horas de atraso.")
    st.caption("Limites: o modelo usa horas inteiras, consumo uniforme por lote e máquinas idênticas por empresa. Valide com o PCP antes de "
               "aplicar na fábrica e compare a agenda do app com o realizado.")
