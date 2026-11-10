"""Interface Streamlit da coleta multiempresa (abas 'Contribuir com dados' e 'Painel do pesquisador')."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from . import coleta as C

_SEM = {"MED": "🟢", "FAT": "🟢", "LAU": "🟢", "CON": "🟢", "PUB": "🟡", "EST": "🔴"}


def _auto():
    """Valores sugeridos a partir da planilha já importada na aba 'Sua empresa' (a empresa confirma a evidência)."""
    if "res_emp" not in st.session_state:
        return {}
    cal, res = st.session_state["res_emp"]
    k, par = res["kpis"], cal["parametros"]
    out = {"eletr": k.get("eletr_kwh_t"), "gas": k.get("gn_m3_t"), "agua": k.get("agua_m3_t"),
           "t_dia": par["textil_t_dia"][0], "dias": par.get("dias_operacao", (None,))[0]}
    return {a: v for a, v in out.items() if v is not None and v == v}


def aba_contribuir():
    st.subheader("Contribuir com dados medidos")
    st.write("Este é o protocolo de coleta do estudo. Ele pede **apenas o que o modelo ainda não mede**: cada campo substitui uma "
             "hipótese do artigo. Nada fica salvo no servidor: ao final você baixa um arquivo e o envia à equipe de pesquisa.")
    tipo = st.radio("Tipo da sua empresa", list(C.TIPOS), format_func=C.TIPOS.get, horizontal=True)
    com_mod = st.toggle("Incluir módulos opcionais (calor, tarifa, gás coletivo, lodo, solar, circularidade)", value=False,
                        help="Os módulos só calculam resultado quando todos os dados deles forem informados com evidência.")
    auto = _auto()
    if auto:
        st.success("Dados da sua planilha foram usados para pré-preencher os campos marcados com 📎. Confirme a evidência de cada um.")
    itens = {}
    for bloco, lista in C.blocos_do_tipo(tipo, com_mod).items():
        with st.expander(f"{bloco} ({len(lista)} campos)", expanded=(bloco == "Perfil e escala")):
            for it in lista:
                c1, c2, c3 = st.columns([2.2, 1.4, 1.6])
                sug = auto.get(it.auto) if it.auto else None
                with c1:
                    v = st.number_input(f"{it.rotulo} ({it.unidade}){' 📎' if sug is not None else ''}", value=None if sug is None else float(sug),
                                        key=f"v_{tipo}_{it.id}", help=it.ajuda, format="%.4g")
                with c2:
                    padrao = it.evid[0] if it.evid else "MED"
                    ev = st.selectbox("De onde vem", [e for e in C.EVID], index=list(C.EVID).index(padrao),
                                      format_func=lambda e: f"{_SEM[e]} {C.EVID[e]}", key=f"e_{tipo}_{it.id}", label_visibility="visible")
                with c3:
                    per = st.number_input("Período coberto (dias)", value=None, min_value=1, max_value=3660, key=f"p_{tipo}_{it.id}")
                if v is not None:
                    reg = {"valor": v, "evidencia": ev, "periodo_dias": per}
                    for nivel, msg in C.validar_item(it, reg):
                        (st.error if nivel == "erro" else st.warning)(msg)
                    itens[it.id] = reg
    frac, falta = C.completude(tipo, itens)
    st.progress(frac, text=f"Completude dos campos obrigatórios com evidência publicável: {frac:.0%}")
    if falta:
        st.caption("Faltam: " + "; ".join(i.rotulo for i in falta[:8]) + ("…" if len(falta) > 8 else ""))
    st.markdown("**Consentimento**")
    st.info(C.CONSENTIMENTO_V1)
    aceite = st.checkbox("Li e aceito o termo acima")
    publicar = st.checkbox("Autorizo incluir meus valores, sem identificação, no conjunto de dados aberto do artigo")
    regiao = st.text_input("Região (opcional, ex.: Vale do Itajaí)")
    if st.button("Gerar arquivo de contribuição", type="primary", disabled=not (aceite and itens)):
        pac = C.novo_pacote(tipo, itens, aceite, publicar, regiao)
        st.session_state["pacote"] = pac
    pac = st.session_state.get("pacote")
    if pac:
        st.success(f"Arquivo gerado. Código anônimo: {pac['id_anonimo']}. Selo: {pac['selo_sha256'][:12]}…")
        st.download_button("⬇️ Baixar contribuição (JSON)", json.dumps(pac, ensure_ascii=False, indent=1),
                           file_name=f"contribuicao_{pac['id_anonimo']}.json", mime="application/json")
        st.caption("Envie o arquivo por e-mail ao pesquisador responsável ou pelo SENAI. O arquivo não contém nome da empresa.")
    if tipo == "tinturaria" and com_mod:
        st.markdown("### Resultados dos módulos com os seus dados")
        res = C.modulos_com_dados(itens)
        for nome, r in res.items():
            if r["ok"]:
                x = r["resultado"]
                st.success(f"{nome}: economia R$ {x['economia_r_ano']:,.0f}/ano · CO₂e evitado {x['co2e_evitado_t_ano']:,.0f} t/ano")
            else:
                st.caption(f"⏸️ {nome}: faltam {', '.join(r['faltam'][:3])}{'…' if len(r['faltam']) > 3 else ''}")


def aba_pesquisador():
    st.subheader("Painel do pesquisador")
    st.write("Envie os arquivos de contribuição recebidos. O painel valida o selo, agrega, mostra o que ainda falta e "
             "roda de novo os resultados do artigo com os valores medidos.")
    ups = st.file_uploader("Arquivos de contribuição (JSON)", type="json", accept_multiple_files=True)
    pacotes = []
    for u in ups or []:
        try:
            pacotes.append(json.load(u))
        except Exception:
            st.error(f"{u.name}: arquivo ilegível")
    if not pacotes:
        st.info("Nenhum arquivo carregado.")
        return
    linhas = []
    for p in pacotes:
        ok, m = C.verificar_pacote(p)
        linhas.append({"Código": p.get("id_anonimo"), "Tipo": p.get("tipo_empresa"), "Itens": len(p.get("itens", {})),
                       "Válido": "✅" if ok else "❌ " + "; ".join(m)})
    st.dataframe(pd.DataFrame(linhas), hide_index=True)
    agg, ult = C.agregar(pacotes)
    n_emp = len(ult)
    st.metric("Empresas válidas", n_emp, help=f"Estatísticas só são publicadas com n ≥ {C.K_MIN}.")
    if n_emp < C.K_MIN:
        st.warning(f"Com menos de {C.K_MIN} empresas nenhuma estatística é divulgada, para não identificar ninguém.")
        return
    st.markdown("### Parâmetros medidos")
    tab = pd.DataFrame([l for l in C.tabela_parametros(agg) if l["publicavel"] == "sim"])
    st.dataframe(tab, hide_index=True)
    st.markdown("### O que ainda é hipótese ou literatura")
    st.dataframe(pd.DataFrame(C.painel_lacunas(agg)), hide_index=True)
    st.caption("Amostra por conveniência: descreva como estudo multicaso e não generalize para todo o setor.")
    if st.button("Rodar de novo os resultados do artigo com os dados medidos"):
        with st.spinner("Simulando…"):
            st.session_state["reav"] = C.reavaliar(agg, n=1000)
    r = st.session_state.get("reav")
    if r:
        st.write("Parâmetros trocados: " + ", ".join(r["parametros_trocados"]))
        a, d = r["antes"], r["depois"]
        st.dataframe(pd.DataFrame([{"Cenário": k, "CO₂e antes (kg/t)": a[k]["co2_tex_kg_t"], "CO₂e depois (kg/t)": d[k]["co2_tex_kg_t"]}
                                   for k in a if k != "economia"]), hide_index=True)
        st.write(f"Probabilidade de o biometano competir com o gás: {a['economia']['prob_competitivo_sem_gate']:.0%} → "
                 f"{d['economia']['prob_competitivo_sem_gate']:.0%} (sem gate fee).")
    st.download_button("⬇️ Tabela de parâmetros (CSV)", tab.to_csv(index=False), "parametros_medidos.csv")
    st.download_button("⬇️ Tabela LaTeX", C.tabela_latex(agg), "parametros_medidos.tex")
    ds = [l for l in C.dataset_anonimizado(ult)]
    st.download_button("⬇️ Dados anonimizados (CSV)", pd.DataFrame(ds).to_csv(index=False), "dados_anonimizados.csv")
