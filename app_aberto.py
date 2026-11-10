"""Interface Streamlit do DT2-SC (modo planta).  Executar:  streamlit run app.py
Os dados ficam na máquina local; nada é enviado para a internet."""
import io
import json

import pandas as pd
import streamlit as st

from dt2sc import planta as P

st.set_page_config(page_title="DT2-SC - planta", layout="wide")
st.title("DT2-SC · gêmeo digital circular para tinturarias")
st.caption("Carregue o CSV do SCADA/historiador, mapeie as colunas, calibre o gêmeo e compare cenários.")

with st.sidebar:
    st.header("Dados")
    arq = st.file_uploader("CSV da planta", type=["csv", "txt"])
    usar_ex = st.checkbox("Usar dados de exemplo (sintéticos)", value=arq is None)
    st.header("Parâmetros locais")
    tarifa = st.number_input("Preço pago pelo gás (R$/m³), 0 = paridade Argus", 0.0, 10.0, 0.0, 0.01)
    cavaco = st.number_input("Cavaco local (R$/t), 0 = não comparar", 0.0, 2000.0, 0.0, 10.0)
    gate = st.number_input("Taxa de destinação paga hoje (R$/t), 0 = referência", 0.0, 1000.0, 0.0, 5.0)
    n = st.select_slider("Amostras Monte Carlo", [500, 1000, 3000, 10000], value=1000)

if arq is None and not usar_ex:
    st.info("Envie um CSV ou marque a opção de exemplo.")
    st.stop()

if arq is not None:
    bruto = pd.read_csv(arq, sep=None, engine="python")
else:
    buf = io.StringIO()
    P.exemplo_csv("/tmp/_dt2sc_exemplo.csv", 14)
    bruto = pd.read_csv("/tmp/_dt2sc_exemplo.csv")

st.subheader("1. Mapeamento de colunas e unidades")
sug = P.detectar_mapa(bruto.columns)
opcoes = [None] + list(bruto.columns)
cols = st.columns(3)
mapa, fator = {}, {}
for i, c in enumerate(P.COLUNAS):
    with cols[i % 3]:
        pad = sug.get(c)
        mapa[c] = st.selectbox(c + (" *" if c in P.OBRIGATORIAS else ""), opcoes,
                               index=opcoes.index(pad) if pad in opcoes else 0, key=f"m_{c}")
        if c != "timestamp":
            fator[c] = st.number_input(f"multiplicador {c}", value=1.0, format="%g", key=f"f_{c}")

try:
    df = P.carregar(bruto, mapa, fator)
except ValueError as e:
    st.error(str(e)); st.stop()

q = P.qualidade(df)
st.subheader("2. Qualidade dos dados")
a, b, c, d = st.columns(4)
a.metric("Linhas", q["linhas"]); b.metric("Dias", f"{q['dias']:.1f}")
c.metric("Passo (min)", f"{q['passo_min']:.0f}"); d.metric("Horas de produção", f"{q['horas_producao']:.0f}")
st.dataframe(pd.DataFrame(q["por_coluna"]).T)

cal = P.calibrar(df)
k = cal["kpis"]
st.subheader("3. Intensidades medidas")
a, b, c, d = st.columns(4)
a.metric("Eletricidade (kWh/t)", f"{k['eletr_kwh_t']:.0f}")
b.metric("Gás natural (m³/t)", f"{k['gn_m3_t']:.0f}")
c.metric("Água (m³/t)", f"{k['agua_m3_t']:.1f}")
d.metric("CO₂e energia (kg/t)", f"{k['co2e_energia_kg_t']:.0f}")
for aviso in cal["avisos"]:
    st.warning(aviso)
dia = P.intensidades_diarias(df)
if len(dia):
    st.line_chart(dia[["eletr_kwh_t"]])
    st.line_chart(dia[["agua_m3_t"]])

st.subheader("4. Anomalias")
an = P.anomalias(df)
st.write(f"{len(an)} eventos")
st.dataframe(an)

st.subheader("5. Cenários e economia (gêmeo calibrado com a planta)")
if st.button("Rodar simulação"):
    with st.spinner("Monte Carlo..."):
        res = P.avaliar_planta(cal, n, tarifa or None, cavaco or None, gate or None)
    linhas = [{"Cenário": nome, "SEI": r["sei"]["media"], "CO₂e (kg/t)": r["co2_tex_kg_t"]["media"],
               "Água (m³/t)": r["agua_tex_m3_t"]["media"]} for nome, r in res["cenarios"].items()]
    st.dataframe(pd.DataFrame(linhas).set_index("Cenário"))
    st.bar_chart(pd.DataFrame(linhas).set_index("Cenário")[["CO₂e (kg/t)"]])
    if "economia" in res:
        st.json(res["economia"])
    rel = P.relatorio_md(cal, res, an, q)
    st.download_button("Baixar relatório (Markdown)", rel, "dt2sc_relatorio.md")
    st.download_button("Baixar resultados (JSON)", json.dumps(res, indent=2, ensure_ascii=False, default=str),
                       "dt2sc_resultados.json")
