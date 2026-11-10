"""DT2-SC · simulador aberto: mostra os resultados do artigo e permite que uma empresa informe os próprios dados
para verificar a viabilidade, como no artigo. Sem login; nada é gravado no servidor (tudo fica na sessão).
Executar:  streamlit run app.py"""
import io
import json
import os
import sys
import types
from pathlib import Path
import time

import pandas as pd
import streamlit as st


def _garantir_pacote():
    """Acha o pacote dt2sc mesmo que a pasta esteja aninhada, renomeada ou com os arquivos soltos na raiz.
    Se não achar, mostra na tela os arquivos do repositório para facilitar o diagnóstico."""
    base = Path(__file__).resolve().parent
    sys.path.insert(0, str(base))
    import importlib.util
    try:
        if importlib.util.find_spec("dt2sc.planta") is not None:
            return
    except ModuleNotFoundError:
        pass
    sys.modules.pop("dt2sc", None)      # descarta um "dt2sc" vazio (pasta sem o código) antes de procurar
    achados = [p.parent for p in sorted(base.rglob("planta.py")) if (p.parent / "acesso.py").exists()]
    if achados:
        pkg = types.ModuleType("dt2sc")
        pkg.__path__ = [str(achados[0])]
        sys.modules["dt2sc"] = pkg
        return
    arqs = sorted(str(p.relative_to(base)) for p in base.rglob("*")
                  if p.is_file() and ".git" not in p.parts)[:80]
    st.error("Não encontrei os arquivos do pacote dt2sc (planta.py, acesso.py ...) no repositório. "
             "Envie a pasta dt2sc inteira, ao lado do app.py. Arquivos encontrados:")
    st.code("\n".join(arqs) or "(nenhum)")
    st.stop()


_garantir_pacote()
from dt2sc import planta as P  # noqa: E402
from dt2sc.dados_artigo import DADOS  # noqa: E402


st.set_page_config(page_title="DT2-SC · Viabilidade", page_icon="🏭", layout="wide")
CEN = {"S0": "S0 Silos (base)", "S1": "S1 Gêmeo, malha aberta", "S2": "S2 Gêmeo, malha fechada (PI)",
       "S3": "S3 Malha fechada + hub de biometano", "S4": "S4 Malha fechada + contrato negociado"}


def _cen(res_cen, prefixo):
    for nome, r in res_cen.items():
        if nome.startswith(prefixo):
            return r
    return None


def _tabela_cenarios(cen):
    linhas = []
    for nome, r in cen.items():
        linhas.append({"Cenário": CEN.get(nome[:2], nome), "SEI": r["sei"]["media"],
                       "CO₂e têxtil (kg/t)": r["co2_tex_kg_t"]["media"], "Água (m³/t)": r["agua_tex_m3_t"]["media"],
                       "Gás fóssil (m³/t)": r.get("gn_fossil_m3_t", {}).get("media", float("nan")),
                       "Cobertura de biometano": r.get("cobertura_bio", {}).get("media", 0.0)})
    return pd.DataFrame(linhas).set_index("Cenário")


# ----------------------------------------------------------------------------- resultados do artigo
def aba_artigo():
    d = DADOS
    st.subheader("Resultados gerados no artigo")
    n_sim = f"{d['n_simulacoes']:,}".replace(",", ".")
    st.caption(f"Gêmeo digital federado da cadeia têxtil de Santa Catarina: {n_sim} simulações Monte Carlo, "
               "parâmetros de literatura e preços públicos (Appel 2019, Falani 2022, Argus, cotações de cavaco). "
               "São o ponto de comparação para a sua empresa.")
    c = d["cenarios"]
    e = d["economia"]
    a, b, c3, d4 = st.columns(4)
    a.metric("Água por tonelada (S2 vs S0)", f"{_cen(c, 'S2')['delta_agua_pct']['media']:.0f} %")
    b.metric("CO₂e têxtil (S3 vs S0)", f"{_cen(c, 'S3')['delta_co2_tex_pct']['media']:.0f} %")
    c3.metric("CO₂e têxtil (S4 vs S0)", f"{_cen(c, 'S4')['delta_co2_tex_pct']['media']:.0f} %")
    d4.metric("Biometano competitivo com taxa de destinação", f"{100 * e['prob_competitivo_com_gate']:.0f} %",
              f"{100 * e['prob_competitivo_sem_gate']:.0f} % sem a taxa", delta_color="off")

    st.markdown("#### Cenários")
    t = _tabela_cenarios(c)
    st.dataframe(t.style.format({"SEI": "{:.3f}", "CO₂e têxtil (kg/t)": "{:.0f}", "Água (m³/t)": "{:.0f}",
                                 "Gás fóssil (m³/t)": "{:.0f}", "Cobertura de biometano": "{:.0%}"}))
    x1, x2 = st.columns(2)
    x1.bar_chart(t[["CO₂e têxtil (kg/t)"]]); x2.bar_chart(t[["Água (m³/t)"]])
    st.caption("O controle em malha fechada reduz a água; o biometano do frigorífico reduz o carbono; o contrato "
               "negociado amplia a cobertura do gás. O SEI (índice de sustentabilidade) sobe de S0 para S1–S4.")

    st.markdown("#### De onde vem o CO₂e (kg/t)")
    dec = pd.DataFrame(d["decomposicao_co2"]).T.rename(columns={"gas": "Gás natural", "electricity": "Eletricidade",
                                                               "fibre": "Fibra"})
    dec.index = [CEN.get(i[:2], i) for i in dec.index]
    st.bar_chart(dec)

    st.markdown("#### Economia do biometano")
    q = lambda x: f"R$ {x['media']:.2f} [{x['p5']:.2f}; {x['p95']:.2f}]"
    st.dataframe(pd.DataFrame({"R$/m³ (média [P5; P95])": {
        "Gás natural (paridade Argus)": q(e["tarifa_gn"]),
        "Preço de equilíbrio do biometano, sem taxa de destinação": q(e["p_eq_sem_gate"]),
        "Preço de equilíbrio do biometano, com taxa de destinação": q(e["p_eq_com_gate"])}}))
    st.write(f"O biometano é competitivo com o gás em **{100 * e['prob_competitivo_sem_gate']:.0f} %** das simulações "
             f"sem a taxa de destinação e em **{100 * e['prob_competitivo_com_gate']:.0f} %** com ela. "
             "A viabilidade depende de o frigorífico repassar ao hub a taxa que hoje paga pela destinação do resíduo.")
    vpl = pd.DataFrame({f"R$ {k}/tCO₂e": {"VPL médio (R$ mi)": v["media"], "P5": v["p5"], "P95": v["p95"],
                                          "Prob. VPL > 0": e["prob_vpl_pos"][k]}
                        for k, v in e["vpl_sistema_mi"].items()})
    st.markdown("**VPL do sistema (hub de referência) por preço do carbono**")
    st.dataframe(vpl)

    st.markdown("#### Biometano contra cavaco")
    cv = d["cavaco"]
    mun = pd.DataFrame(cv["por_municipio"]).T[["preco", "unidade", "m3eq_media", "m3eq_p5", "m3eq_p95"]]
    mun.columns = ["Preço", "Unidade", "R$/m³ eq. (média)", "P5", "P95"]
    st.dataframe(mun)
    st.write(f"O cavaco custa em média **R$ {cv['mix']['media']:.2f}/m³ de gás equivalente**, cerca de "
             f"{cv['razao_gas_cavaco']:.1f} vezes menos que o gás. O biometano supera o cavaco em apenas "
             f"{100 * cv['p_bio_menor_que_cavaco_sem_gate']:.0f} % (sem taxa) e {100 * cv['p_bio_menor_que_cavaco_com_gate']:.0f} % "
             "(com taxa) das simulações: o biometano faz mais sentido para plantas movidas a gás natural.")

    st.markdown("#### Negociação entre as empresas")
    nome_n = {"isolado": "bilateral", "espaco": "espaço de dados", "total": "visibilidade total"}
    neg = pd.DataFrame(d["negociacao"]).T
    neg.index = [f"{nome_n.get(i.split('|')[0], i)} · {'com humano' if i.endswith('humano') else 'autônomo'}" for i in neg.index]
    neg = neg.rename(columns={"taxa_acordo": "Taxa de acordo", "preco_medio": "Preço (R$/m³)", "gate_medio": "Taxa (R$/t)",
                              "volume_medio": "Volume (t/ano)", "rodadas": "Rodadas", "dias": "Dias",
                              "escalados": "Escalados ao humano", "co2_evitado_t_ano": "CO₂e evitado (t/ano)",
                              "excedente_tex_mi": "Ganho têxtil (R$ mi)", "excedente_usina_mi": "Ganho usina (R$ mi)",
                              "excedente_frig_mi": "Ganho frigorífico (R$ mi)"})
    st.dataframe(neg.style.format({"Taxa de acordo": "{:.0%}", "Escalados ao humano": "{:.0%}", "Preço (R$/m³)": "{:.2f}",
                                   "Taxa (R$/t)": "{:.0f}", "Volume (t/ano)": "{:.0f}", "Rodadas": "{:.1f}", "Dias": "{:.1f}",
                                   "CO₂e evitado (t/ano)": "{:.0f}", "Ganho têxtil (R$ mi)": "{:.2f}",
                                   "Ganho usina (R$ mi)": "{:.2f}", "Ganho frigorífico (R$ mi)": "{:.2f}"}))
    st.markdown("#### Sensibilidade a premissas")
    sens = pd.DataFrame(d["sensibilidade"]).T
    sens.columns = ["SEI S0", "CO₂e têxtil S0 (kg/t)", "Δ CO₂e S3 (%)", "Δ CO₂e S4 (%)", "Δ água S2 (%)",
                    "Δ energia S4 (%)", "Cobertura S3", "Cobertura S4"]
    st.dataframe(sens.style.format("{:.2f}"))


# ----------------------------------------------------------------------------- sua empresa
def _parecer(res):
    k, e = res["kpis"], res.get("economia", {})
    L = []
    if "prob_competitivo_sem_gate" in e:
        sem, com = e["prob_competitivo_sem_gate"], e["prob_competitivo_com_gate"]
        eq = e["p_equilibrio_com_gate"]["media"]
        ref = e["paridade_ou_tarifa"]["media"]
        if sem >= 0.5:
            L.append(f"✅ O biometano é competitivo com o gás da empresa (R$ {ref:.2f}/m³) mesmo sem a taxa de destinação "
                     f"({100 * sem:.0f} % das simulações).")
        elif com >= 0.5:
            L.append(f"🟡 O biometano só é competitivo **com a taxa de destinação** do frigorífico: {100 * com:.0f} % das "
                     f"simulações com a taxa e {100 * sem:.0f} % sem. Preço de equilíbrio com a taxa: R$ {eq:.2f}/m³ contra "
                     f"R$ {ref:.2f}/m³ do gás.")
        else:
            L.append(f"🔴 Nas condições informadas o biometano não é competitivo (equilíbrio R$ {eq:.2f}/m³ com taxa, contra "
                     f"R$ {ref:.2f}/m³ do gás). Reveja o preço do gás, a taxa de destinação ou a escala do hub.")
        if "prob_biometano_menor_que_cavaco_com_gate" in e:
            pc = e["prob_biometano_menor_que_cavaco_com_gate"]
            L.append(f"O cavaco local custa R$ {e['cavaco_r_m3eq']:.2f} por m³ de gás equivalente; o biometano o supera em "
                     f"{100 * pc:.0f} % das simulações (com a taxa). " +
                     ("O cavaco tende a ser a opção mais barata, desde que a caldeira possa queimá-lo." if pc < 0.5 else
                      "O biometano é competitivo também contra o cavaco."))
    elif "cavaco_r_m3eq" in e:
        L.append(f"Planta movida a cavaco (R$ {e['cavaco_r_m3eq']:.2f} por m³ de gás equivalente): o biometano não se aplica; "
                 "os ganhos vêm do controle de água e energia (S1 e S2).")
    return L


def mostrar_resultado(res, cal):
    k = res["kpis"]
    st.subheader("Resultado para a sua empresa")
    a, b, c, d = st.columns(4)
    a.metric("Eletricidade (kWh/t)", f"{k['eletr_kwh_t']:.0f}")
    b.metric("Gás natural (m³/t)", f"{k['gn_m3_t']:.0f}")
    c.metric("Água (m³/t)", "—" if k["agua_m3_t"] != k["agua_m3_t"] else f"{k['agua_m3_t']:.0f}")
    d.metric("CO₂e de energia (kg/t)", f"{k['co2e_energia_kg_t']:.0f}")
    for av in res.get("avisos", []):
        st.warning(av)
    for linha in _parecer(res):
        st.markdown(linha)
    t = _tabela_cenarios(res["cenarios"])
    st.dataframe(t.style.format({"SEI": "{:.3f}", "CO₂e têxtil (kg/t)": "{:.0f}", "Água (m³/t)": "{:.0f}",
                                 "Gás fóssil (m³/t)": "{:.0f}", "Cobertura de biometano": "{:.0%}"}))
    x1, x2 = st.columns(2)
    x1.bar_chart(t[["CO₂e têxtil (kg/t)"]]); x2.bar_chart(t[["Água (m³/t)"]])
    s0, s2, s4 = (_cen(res["cenarios"], p) for p in ("S0", "S2", "S4"))
    if s0 and s2:
        st.write(f"Controle em malha fechada: água de {s0['agua_tex_m3_t']['media']:.0f} para "
                 f"{s2['agua_tex_m3_t']['media']:.0f} m³/t ({100 * (s2['agua_tex_m3_t']['media'] / s0['agua_tex_m3_t']['media'] - 1):.0f} %).")
    if s0 and s4:
        st.write(f"Com hub e contrato negociado: CO₂e têxtil de {s0['co2_tex_kg_t']['media']:.0f} para "
                 f"{s4['co2_tex_kg_t']['media']:.0f} kg/t ({100 * (s4['co2_tex_kg_t']['media'] / s0['co2_tex_kg_t']['media'] - 1):.0f} %).")
    e = res.get("economia", {})
    if "vpl_hub_mi" in e:
        st.caption(f"VPL do hub de referência do artigo (não é o investimento da sua empresa): R$ {e['vpl_hub_mi']['media']:.0f} mi "
                   f"[{e['vpl_hub_mi']['p5']:.0f}; {e['vpl_hub_mi']['p95']:.0f}]. A viabilidade acima compara preços, que é o que "
                   "decide a competitividade do biometano para a sua planta.")
    st.download_button("Baixar relatório (Markdown)", P.relatorio_md(cal, res), "dt2sc_viabilidade.md")
    st.caption("Resultado indicativo: usa o modelo e as premissas do artigo. Confirme com medições e cotações reais antes de decidir.")


def aba_empresa():
    st.subheader("Verifique a viabilidade para a sua empresa")
    st.write("Informe os dados da planta (à mão ou por CSV) e os preços locais. O sistema calibra o gêmeo, simula os cenários do "
             "artigo e compara o biometano com o gás natural e o cavaco. **Nada é gravado:** os dados ficam só nesta sessão.")
    modo = st.radio("Como informar os dados da planta", ["Digitar valores", "Enviar CSV do SCADA/historiador"], horizontal=True)
    cal = None
    if modo == "Digitar valores":
        c1, c2, c3 = st.columns(3)
        t_dia = c1.number_input("Produção (t de tecido por dia)", 0.5, 200.0, 10.0, 0.5)
        dias = c1.number_input("Dias de operação por ano", 100, 365, 300, 5)
        ele = c2.number_input("Eletricidade (kWh por tonelada)", 0.0, 5000.0, 808.0, 10.0)
        gas = c2.number_input("Gás natural (m³ por tonelada; 0 se não usa)", 0.0, 5000.0, 1143.0, 10.0)
        agua = c3.number_input("Água (m³ por tonelada)", 0.0, 500.0, 170.0, 5.0)
        cav = c3.number_input("Cavaco (kg por tonelada; 0 se não usa)", 0.0, 5000.0, 0.0, 10.0)
        try:
            cal = P.calibrar_manual(ele, gas, agua, t_dia, dias, cav)
        except ValueError as e:
            st.error(str(e))
    else:
        arq = st.file_uploader("CSV (timestamp, producao_kg_h, eletrica_kw; opcionais: gn_m3_h, agua_m3_h, cavaco_kg_h ...)",
                               type=["csv", "txt"])
        if arq is not None:
            bruto = pd.read_csv(arq, sep=None, engine="python")
            sug = P.detectar_mapa(bruto.columns)
            opc = [None] + list(bruto.columns)
            mapa, fator = {}, {}
            with st.expander("Colunas e unidades (confira)", expanded=False):
                cols = st.columns(3)
                for i, c in enumerate(P.COLUNAS):
                    with cols[i % 3]:
                        mapa[c] = st.selectbox(c, opc, index=opc.index(sug.get(c)) if sug.get(c) in opc else 0, key=f"m_{c}")
                        if c != "timestamp":
                            fator[c] = st.number_input(f"multiplicador {c}", value=1.0, format="%g", key=f"f_{c}")
            try:
                df = P.carregar(bruto, mapa, fator)
                q = P.qualidade(df)
                st.caption(f"{q['linhas']} linhas · {q['dias']:.1f} dias · passo de {q['passo_min']:.0f} min · "
                           f"{q['horas_producao']:.0f} h de produção")
                cal = P.calibrar(df)
            except ValueError as e:
                st.error(str(e))
    st.markdown("**Preços locais** (deixe 0 para usar a referência do artigo)")
    p1, p2, p3, p4 = st.columns(4)
    tarifa = p1.number_input("Preço pago pelo gás (R$/m³)", 0.0, 10.0, 0.0, 0.01)
    cavaco = p2.number_input("Cavaco na região (R$/t)", 0.0, 2000.0, 0.0, 10.0)
    gate = p3.number_input("Taxa de destinação paga hoje pelo frigorífico (R$/t)", 0.0, 1000.0, 0.0, 5.0)
    n = p4.select_slider("Simulações", [500, 1000, 3000, 10000], value=1000)
    if cal is not None and st.button("Verificar viabilidade", type="primary"):
        with st.spinner("Rodando o Monte Carlo..."):
            st.session_state["res_emp"] = (cal, P.avaliar_planta(cal, n, tarifa or None, cavaco or None, gate or None))
    if "res_emp" in st.session_state:
        mostrar_resultado(st.session_state["res_emp"][1], st.session_state["res_emp"][0])


def aba_sobre():
    st.subheader("Como usar")
    st.markdown("""
1. **Veja o que o artigo mostra** na aba *Resultados do artigo*: cenários S0 a S4, economia do biometano, comparação com o cavaco e negociação.
2. Na aba *Sua empresa*, informe a produção, o consumo de energia, gás e água por tonelada (ou envie o CSV do SCADA) e os preços locais.
3. Clique em **Verificar viabilidade**. O sistema calibra o gêmeo com os seus dados, simula os cinco cenários e compara o biometano com o gás e o cavaco.
4. Baixe o relatório e leve a conversa à negociação com o frigorífico e o fornecedor de energia.

**Dados e privacidade.** O aplicativo não tem login e não grava nada: os valores e o CSV existem só na sessão do navegador.

**Limites.** Os parâmetros do modelo vêm de literatura e preços públicos; a sua planta substitui eletricidade, gás, água e escala. O VPL é do hub
de referência do artigo. Valores digitados à mão recebem uma faixa de incerteza de ±15 %. O resultado é indicativo.""")


st.title("🏭 DT2-SC · gêmeo digital da cadeia têxtil")
st.caption("Sustentabilidade da cadeia de suprimentos: água, energia, carbono e troca de resíduo por energia entre empresas.")
t1, t2, t3 = st.tabs(["📄 Resultados do artigo", "🏭 Sua empresa", "ℹ️ Como usar"])
with t1:
    aba_artigo()
with t2:
    aba_empresa()
with t3:
    aba_sobre()
