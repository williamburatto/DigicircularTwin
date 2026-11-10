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
from dt2sc import modulos as M  # noqa: E402
from dt2sc import planta as P  # noqa: E402
from dt2sc.dados_artigo import DADOS  # noqa: E402
from dt2sc import ui_coleta  # noqa: E402
from dt2sc import ui_programacao  # noqa: E402


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
    with st.expander("O que significa cada indicador?"):
        glossario()


MODELO_CSV = ("timestamp,producao_kg_h,eletrica_kw,gn_m3_h,agua_m3_h,cavaco_kg_h,vapor_kg_h,temp_efluente_c,ph\n"
              "2026-03-02 06:00,420,310,480,52,0,,34,7.2\n2026-03-02 07:00,455,335,510,55,0,,35,7.0\n"
              "2026-03-02 08:00,440,325,495,54,0,,34,7.1\n")


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


# ----------------------------------------------------------------------------- explicações
def glossario():
    st.markdown("""
**Cenários (S0 a S4)**
- **S0 · Silos:** cada empresa decide sozinha, sem trocar informação. É a situação de partida.
- **S1 · Gêmeo em malha aberta:** o gêmeo digital recomenda ajustes, mas ninguém confere se deram resultado.
- **S2 · Malha fechada (PI):** a recomendação é conferida contra o que foi medido e corrigida continuamente.
- **S3 · Hub de biometano:** soma o gás produzido a partir do resíduo do frigorífico.
- **S4 · Contrato negociado:** as empresas negociam preço e volume e o biometano cobre a maior parte do gás.

**Indicadores**
- **kWh/t, m³ de gás/t, m³ de água/t:** consumo por tonelada de tecido. Quanto menor, melhor.
- **CO₂e (kg/t):** emissões de gases de efeito estufa equivalentes por tonelada de tecido (energia e fibra). O cavaco e o biometano
  contam como biogênicos, sem emissão fóssil.
- **SEI (índice de sustentabilidade):** nota de 0 a 1 que combina água, energia, carbono e circularidade. Serve para comparar cenários, não é uma certificação.
- **Cobertura de biometano:** fatia do gás da tinturaria que o biometano substitui.
- **Média [P5; P95]:** o valor médio das simulações e a faixa em que caem 90 % delas. Faixa larga significa mais incerteza.

**Economia**
- **Paridade (preço do gás):** quanto a empresa paga hoje pelo gás natural. O biometano só vale a pena se custar menos que isso.
- **Preço de equilíbrio do biometano:** preço mínimo para o hub não ter prejuízo.
- **Taxa de destinação:** quanto o frigorífico paga hoje para descartar o resíduo. Se ela for repassada ao hub, o biometano fica mais barato.
- **Probabilidade de ser competitivo:** em quantas simulações o preço de equilíbrio ficou abaixo do gás (ou do cavaco).
- **VPL:** valor presente líquido do hub de referência do artigo. Positivo significa que o investimento se paga.
""")


COMO_PREPARAR = """
**Passo a passo para importar o Excel**
1. **Baixe a planilha-modelo** (botão abaixo). Ela traz um dia de exemplo e uma aba de instruções.
2. **Cole os seus dados** na aba *Dados*, a partir da linha 2: uma linha por intervalo de tempo (15 min, 1 h...), em ordem de data.
   Os dados saem do SCADA, do historiador ou das planilhas de leitura dos medidores.
3. **Mantenha só o que tem.** As colunas laranja são obrigatórias (data e hora, produção, eletricidade). As cinzas são opcionais.
4. **Salve como .xlsx** (ou CSV) e envie na etapa 2. Se a planilha for sua e tiver outros nomes de coluna, tudo bem: você escolhe qual coluna é qual.
5. **Escolha a unidade** de cada coluna (kW ou W, kg/h ou t/h, e assim por diante). Se a planilha traz o consumo *somado* em cada intervalo
   (por exemplo, kWh a cada hora), escolha a opção *no intervalo*.

Quantidade ideal: **4 semanas ou mais** (o ideal são 12 meses). Com menos, o sistema funciona, mas a incerteza aumenta.
"""


def mostrar_resultado(res, cal):
    k = res["kpis"]
    st.markdown("### Etapa 5 · Resultado")
    a, b, c, d = st.columns(4)
    a.metric("Eletricidade (kWh/t)", f"{k['eletr_kwh_t']:.0f}", help="Energia elétrica gasta para cada tonelada de tecido processada.")
    b.metric("Gás natural (m³/t)", f"{k['gn_m3_t']:.0f}", help="Gás usado na caldeira e nos processos térmicos por tonelada.")
    c.metric("Água (m³/t)", "—" if k["agua_m3_t"] != k["agua_m3_t"] else f"{k['agua_m3_t']:.0f}",
             help="Água usada por tonelada. Referências de SC: 80 a 230 m³/t.")
    d.metric("CO₂e de energia (kg/t)", f"{k['co2e_energia_kg_t']:.0f}",
             help="Emissões do gás e da eletricidade por tonelada, sem contar a fibra. Cavaco e biometano contam como zero fóssil.")
    for av in res.get("avisos", []):
        st.warning(av)

    st.markdown("#### O que isso quer dizer para a sua empresa")
    for linha in _parecer(res):
        st.markdown(linha)
    s0, s2, s4 = (_cen(res["cenarios"], p) for p in ("S0", "S2", "S4"))
    if s0 and s2:
        st.write(f"💧 **Água:** o controle em malha fechada leva o consumo de {s0['agua_tex_m3_t']['media']:.0f} para "
                 f"{s2['agua_tex_m3_t']['media']:.0f} m³/t ({100 * (s2['agua_tex_m3_t']['media'] / s0['agua_tex_m3_t']['media'] - 1):.0f} %).")
    if s0 and s4:
        st.write(f"🌱 **Carbono:** com hub e contrato negociado, o CO₂e têxtil vai de {s0['co2_tex_kg_t']['media']:.0f} para "
                 f"{s4['co2_tex_kg_t']['media']:.0f} kg/t ({100 * (s4['co2_tex_kg_t']['media'] / s0['co2_tex_kg_t']['media'] - 1):.0f} %).")

    st.markdown("#### Os cinco cenários lado a lado")
    t = _tabela_cenarios(res["cenarios"])
    st.dataframe(t.style.format({"SEI": "{:.3f}", "CO₂e têxtil (kg/t)": "{:.0f}", "Água (m³/t)": "{:.0f}",
                                 "Gás fóssil (m³/t)": "{:.0f}", "Cobertura de biometano": "{:.0%}"}))
    x1, x2 = st.columns(2)
    x1.bar_chart(t[["CO₂e têxtil (kg/t)"]]); x2.bar_chart(t[["Água (m³/t)"]])
    st.caption("Leia cada linha como 'o que aconteceria se a empresa operasse assim'. S0 é a situação atual; quanto mais abaixo, "
               "mais integrada é a cadeia. Barras menores são melhores.")
    e = res.get("economia", {})
    if "p_equilibrio_sem_gate" in e:
        st.markdown("#### Economia do biometano")
        q = lambda x: f"R$ {x['media']:.2f} [{x['p5']:.2f}; {x['p95']:.2f}]"
        st.dataframe(pd.DataFrame({"R$/m³ (média [P5; P95])": {
            "Preço do gás para a sua empresa": q(e["paridade_ou_tarifa"]),
            "Preço de equilíbrio do biometano, sem taxa de destinação": q(e["p_equilibrio_sem_gate"]),
            "Preço de equilíbrio do biometano, com taxa de destinação": q(e["p_equilibrio_com_gate"])}}))
        st.caption("Se o preço de equilíbrio do biometano ficar abaixo do preço do gás, ele compensa. Veja que a taxa de destinação "
                   "do frigorífico costuma ser o que vira o jogo.")
        if "vpl_hub_mi" in e:
            st.caption(f"VPL do hub de referência do artigo (não é o investimento da sua empresa): R$ {e['vpl_hub_mi']['media']:.0f} mi "
                       f"[{e['vpl_hub_mi']['p5']:.0f}; {e['vpl_hub_mi']['p95']:.0f}].")
    with st.expander("O que significa cada resultado?"):
        glossario()
    st.download_button("Baixar relatório (Markdown)", P.relatorio_md(cal, res), "dt2sc_viabilidade.md")
    st.caption("Resultado indicativo: usa o modelo e as premissas do artigo. Confirme com medições e cotações reais antes de decidir.")


# ----------------------------------------------------------------------------- sua empresa
def aba_empresa():
    st.subheader("Verifique a viabilidade para a sua empresa")
    st.markdown("### Etapa 1 · Prepare os dados")
    with st.expander("Como preparar e importar a planilha do Excel", expanded=True):
        st.markdown(COMO_PREPARAR)
        c1, c2 = st.columns(2)
        try:
            c1.download_button("⬇️ Baixar planilha-modelo (.xlsx)", P.modelo_excel(), "modelo_dt2sc.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception:
            st.info("Não foi possível gerar o modelo em Excel; use o CSV ao lado.")
        c2.download_button("⬇️ Baixar modelo em CSV", MODELO_CSV, "modelo_dt2sc.csv")

    st.markdown("### Etapa 2 · Importe os dados")
    modo = st.radio("Como informar os dados da planta",
                    ["Tenho uma planilha (Excel ou CSV)", "Não tenho planilha, vou digitar valores médios"], horizontal=True)
    cal, qual = None, None
    if modo.startswith("Não"):
        st.caption("Use valores médios da sua planta. Onde encontrar: eletricidade, gás e água por tonelada vêm da divisão do consumo do mês "
                   "(fatura ou medidor) pela produção do mês em toneladas.")
        c1, c2, c3 = st.columns(3)
        t_dia = c1.number_input("Produção (t de tecido por dia)", 0.5, 200.0, 10.0, 0.5, help="Produção média dos dias em que a planta opera.")
        dias = c1.number_input("Dias de operação por ano", 100, 365, 300, 5)
        ele = c2.number_input("Eletricidade (kWh por tonelada)", 0.0, 5000.0, 808.0, 10.0, help="kWh do mês dividido pelas toneladas do mês.")
        gas = c2.number_input("Gás natural (m³ por tonelada; 0 se não usa)", 0.0, 5000.0, 1143.0, 10.0, help="m³ de gás do mês dividido pelas toneladas.")
        agua = c3.number_input("Água (m³ por tonelada)", 0.0, 500.0, 170.0, 5.0, help="m³ de água captada dividido pelas toneladas.")
        cav = c3.number_input("Cavaco (kg por tonelada; 0 se não usa)", 0.0, 5000.0, 0.0, 10.0)
        try:
            cal = P.calibrar_manual(ele, gas, agua, t_dia, dias, cav)
        except ValueError as e:
            st.error(str(e))
    else:
        arq = st.file_uploader("Envie o arquivo (.xlsx ou .csv)", type=["xlsx", "xlsm", "csv", "txt"])
        if arq is None:
            st.info("Envie a planilha para continuar. Ainda não tem? Baixe o modelo na etapa 1.")
        else:
            conteudo = arq.getvalue()
            try:
                abas = P.listar_abas(conteudo, arq.name)
            except Exception as e:
                st.error(f"Não consegui abrir o arquivo: {e}"); abas = []
            c1, c2 = st.columns(2)
            aba = c1.selectbox("Aba da planilha que tem os dados", abas, index=0) if abas else None
            lin = c2.number_input("Em que linha estão os nomes das colunas?", 1, 50, 1, 1,
                                  help="Se a planilha tem títulos antes da tabela, informe a linha do cabeçalho.")
            try:
                raw = P.ler_tabela(conteudo, arq.name, aba, lin)
            except Exception as e:
                st.error(f"Não consegui ler a tabela: {e}"); raw = None
            if raw is not None:
                st.markdown("**Prévia do que foi lido** (confira se a primeira linha são os nomes das colunas)")
                st.dataframe(raw.head(8))
                st.markdown("**Diga qual coluna é qual e a unidade de cada uma**")
                sug = P.detectar_mapa(list(raw.columns))
                opc = [None] + list(raw.columns)
                mapa, unid = {}, {}
                h1, h2, h3 = st.columns([2, 3, 2])
                h1.caption("O que é"); h2.caption("Coluna da sua planilha"); h3.caption("Unidade")
                for c in P.COLUNAS:
                    a, b, u = st.columns([2, 3, 2])
                    a.markdown(f"**{P.NOMES_AMIGAVEIS[c]}**" + (" · obrigatório" if c in P.OBRIGATORIAS else " · opcional"))
                    pad = sug.get(c)
                    mapa[c] = b.selectbox(f"Coluna para {P.NOMES_AMIGAVEIS[c]}", opc, index=opc.index(pad) if pad in opc else 0,
                                          key=f"m_{c}", label_visibility="collapsed")
                    if c != "timestamp":
                        ops = list(P.UNIDADES[c])
                        ini = P.sugerir_unidade(c, mapa[c]) if mapa[c] else ops[0]
                        unid[c] = u.selectbox(f"Unidade de {P.NOMES_AMIGAVEIS[c]}", ops, index=ops.index(ini) if ini in ops else 0,
                                              key=f"u_{c}", label_visibility="collapsed")
                faltam = [P.NOMES_AMIGAVEIS[c] for c in P.OBRIGATORIAS if not mapa.get(c)]
                if faltam:
                    st.error("Escolha a coluna de: " + ", ".join(faltam) + ".")
                else:
                    try:
                        df = P.carregar(raw, mapa, None)
                        df = P.converter_unidades(df, unid)
                        qual = P.qualidade(df)
                        cal = P.calibrar(df)
                        st.session_state["df_emp"] = df
                    except ValueError as e:
                        st.error(str(e))
    if cal is not None:
        k = cal["kpis"]
        st.markdown("### Etapa 3 · Confira se os dados fazem sentido")
        if qual:
            a, b, c, d = st.columns(4)
            a.metric("Linhas lidas", qual["linhas"]); b.metric("Dias de dados", f"{qual['dias']:.1f}")
            c.metric("Intervalo entre linhas", f"{qual['passo_min']:.0f} min"); d.metric("Horas de produção", f"{qual['horas_producao']:.0f}")
        for nivel, texto in P.checagens(k, qual):
            {"ok": st.success, "aviso": st.warning, "erro": st.error}[nivel](texto)
        ref = P.comparar_referencia(k)
        if len(ref):
            st.markdown("**Sua planta comparada com a referência de SC usada no artigo**")
            st.dataframe(ref.style.format({"Sua planta": "{:.0f}", "Referência SC (artigo)": "{:.0f}"}))
            st.caption("Diferenças grandes não são erro, mas vale entender o motivo: tipo de tecido, tamanho da planta, tecnologia das máquinas ou unidade errada.")
        if qual and "df_emp" in st.session_state:
            dia = P.intensidades_diarias(st.session_state["df_emp"])
            if len(dia):
                st.markdown("**Consumo por tonelada em cada dia** (picos podem indicar lote difícil, vazamento ou falha)")
                x1, x2 = st.columns(2)
                x1.line_chart(dia[["eletr_kwh_t"]]); x2.line_chart(dia[["agua_m3_t"]])

        st.markdown("### Etapa 4 · Preços locais")
        st.caption("Deixe 0 para usar a referência do artigo.")
        p1, p2, p3, p4 = st.columns(4)
        tarifa = p1.number_input("Preço pago pelo gás (R$/m³)", 0.0, 10.0, 0.0, 0.01, help="Valor da fatura de gás dividido pelo volume em m³.")
        cavaco = p2.number_input("Cavaco na região (R$/t)", 0.0, 2000.0, 0.0, 10.0, help="Cotação do fornecedor de cavaco mais próximo.")
        gate = p3.number_input("Taxa de destinação paga hoje pelo frigorífico (R$/t)", 0.0, 1000.0, 0.0, 5.0,
                               help="O que o frigorífico parceiro paga hoje para descartar o resíduo orgânico (referência do artigo: R$ 145/t).")
        n = p4.select_slider("Simulações", [500, 1000, 3000, 10000], value=1000, help="Mais simulações dão resultado mais estável, porém mais lento.")
        if st.button("Verificar viabilidade", type="primary"):
            with st.spinner("Rodando o Monte Carlo..."):
                st.session_state["res_emp"] = (cal, P.avaliar_planta(cal, n, tarifa or None, cavaco or None, gate or None))
    if "res_emp" in st.session_state:
        mostrar_resultado(st.session_state["res_emp"][1], st.session_state["res_emp"][0])


# ----------------------------------------------------------------------------- comece aqui
def aba_inicio():
    st.subheader("Bem-vindo")
    st.markdown("""
Este aplicativo mostra **quanto água, energia e carbono uma tinturaria pode economizar** e se vale a pena **trocar parte do gás natural por
biometano** feito com o resíduo de um frigorífico vizinho. Ele usa os mesmos cálculos do artigo e os **dados da sua planta**.

**Em 3 passos**
1. **Prepare** uma planilha com os dados da planta (modelo pronto na aba *Sua empresa*).
2. **Importe** o arquivo e confira se os números fazem sentido.
3. **Veja o resultado**: consumo, cenários, preço do biometano contra gás e cavaco, e um parecer em linguagem simples.

**Quem usa**
- **Operador ou engenheiro de processo:** exporta os dados do SCADA ou das planilhas de leitura e confere os números.
- **Gestor:** lê o parecer, as probabilidades e o relatório para decidir sobre combustível, contratos e investimentos.

**Seus dados ficam só no seu navegador.** Nada é gravado nem enviado para outro lugar.
""")
    with st.expander("O que significa cada indicador?"):
        glossario()


# ----------------------------------------------------------------------------- gêmeo digital
def aba_gemeo():
    st.subheader("Por que isto é um gêmeo digital?")
    st.markdown("""
Um **gêmeo digital** é uma representação digital de um sistema físico, alimentada por dados desse sistema e usada para simular e apoiar decisões.
Aqui o sistema físico é a **cadeia tinturaria + frigorífico + produtor de biometano**. O gêmeo é um modelo da cadeia **calibrado com os dados
da própria planta**, no qual é possível testar mudanças (controle de água, troca de combustível, contrato) sem mexer na fábrica.
""")
    tab = pd.DataFrame([
        ["Sistema físico", "A planta têxtil e os parceiros da cadeia", "Existe"],
        ["Dados vindos da planta", "Planilha ou CSV do SCADA, medidores e faturas", "Parcial: envio manual, sem tempo real"],
        ["Modelo calibrado", "Os parâmetros da literatura são trocados pelos valores medidos da sua planta", "Implementado"],
        ["Simulação de cenários (e se...?)", "Cinco cenários, com 10 mil simulações Monte Carlo e faixa de incerteza", "Implementado"],
        ["Controle em malha fechada", "Controlador PI simulado que corrige o consumo com base no desvio medido", "Implementado na simulação"],
        ["Agentes e negociação", "Tinturaria, frigorífico e usina negociam preço, volume e taxa; o humano aprova", "Implementado em simulação (protótipo JADE)"],
        ["Atualização contínua (tempo real)", "Leitura automática do SCADA por OPC UA ou MQTT", "Previsto, ainda não testado em planta"],
        ["Atuação no processo", "Enviar o ajuste ao controle da fábrica, com aprovação humana", "Não implementado: o sistema recomenda e a pessoa decide"],
    ], columns=["Componente de um gêmeo", "Neste sistema", "Situação"])
    st.dataframe(tab.set_index("Componente de um gêmeo"))
    st.markdown("""
**Onde estamos na classificação.** A literatura (por exemplo, Kritzinger e colegas, 2018, e a norma ISO 23247 de manufatura) distingue três níveis:
*modelo digital* (sem troca automática de dados), *sombra digital* (os dados fluem do físico para o digital automaticamente) e *gêmeo digital*
(fluxo nos dois sentidos). Esta versão web é um **gêmeo digital de decisão em nível de modelo calibrado**: o físico alimenta o digital por planilha,
e o resultado volta como recomendação que a equipe aplica. Para chegar à **sombra digital** falta ligar o SCADA; para o **gêmeo completo**, os ajustes
precisariam voltar ao controle com aprovação humana. Isso é o caminho de evolução descrito no artigo.

**Por que isso é útil para a cadeia.** Cada empresa mantém os seus dados e o gêmeo mostra o efeito de decisões conjuntas, como o contrato de biometano,
antes de se comprometer. No artigo, a negociação entre os agentes mostra como compartilhar apenas o necessário (espaço de dados) amplia o acordo e o carbono evitado.
""")


# ----------------------------------------------------------------------------- outras contribuições
def aba_contribuicoes():
    st.subheader("Outras formas de contribuir com a cadeia têxtil")
    st.write("O que o sistema já cobre e o que pode ser acrescentado, usando os mesmos dados da planta.")
    t = pd.DataFrame([
        ["Controle e reúso de água", "Menos captação e menos efluente por tonelada", "Água, produção, efluente", "✅ No modelo (S1 e S2)"],
        ["Combustível mais limpo: biometano ou cavaco", "Menos CO₂e fóssil e menos custo de energia térmica", "Gás, cavaco, preços", "✅ No modelo (S3, S4 e comparação com cavaco)"],
        ["Resíduo do frigorífico vira energia", "Fecha o ciclo e reduz o custo de destinação", "Resíduos, taxa de destinação", "✅ No modelo (hub e negociação)"],
        ["Contratos e negociação entre empresas", "Preço e volume acordados com base em dados", "Demanda, preços, limites", "✅ Em simulação; falta teste com empresas reais"],
        ["Detecção de anomalias de consumo", "Acha vazamentos, lotes fora do padrão e falhas", "Série de kWh/t e água/t", "🟡 Parcial (alerta de kWh/t e de efluente na análise do CSV)"],
        ["Pegada de carbono por pedido para as marcas", "Atende a exigências de clientes e relatórios de emissões", "Energia por lote, fibra, química", "🟡 Parcial (CO₂e por tonelada; falta por pedido)"],
        ["Passaporte digital e rastreabilidade do produto", "Prova de origem e de impacto ao longo da cadeia", "Pegada, insumos, fornecedores", "🧩 Módulo disponível (pré-viabilidade)"],
        ["Recuperação de calor do efluente e do vapor", "Menos gás para aquecer banhos", "Temperatura e vazão do efluente, vapor", "🧩 Módulo disponível (pré-viabilidade)"],
        ["Programação da produção por tarifa e emissão", "Concentra o consumo em horários mais baratos ou limpos", "Tarifa horária, ordens de produção", "🧩 Módulo disponível (pré-viabilidade)"],
        ["Compra coletiva de gás e energia", "Maior poder de negociação das pequenas e médias", "Demanda de várias empresas", "🧩 Módulo disponível (pré-viabilidade)"],
        ["Lodo da estação de tratamento em biogás", "Nova fonte de energia no próprio local", "Volume e composição do lodo", "🧩 Módulo disponível (pré-viabilidade)"],
        ["Energia solar térmica ou fotovoltaica", "Reduz gás e eletricidade da rede", "Perfil de consumo, área disponível", "🧩 Módulo disponível (pré-viabilidade)"],
        ["Circularidade têxtil (retalhos e fibra reciclada)", "Menos descarte e menos fibra virgem", "Resíduos têxteis, destinos", "🧩 Módulo disponível (pré-viabilidade)"],
    ], columns=["Contribuição", "O que muda na cadeia", "Dados necessários", "Situação"])
    st.dataframe(t.set_index("Contribuição"))
    st.caption("✅ implementado no modelo · 🧩 módulo de pré-viabilidade (aba Novos módulos) · 🟡 parcial · ⏳ proposta para as próximas versões do sistema e do artigo. "
               "Os itens de passaporte digital seguem a tendência regulatória europeia de ecodesign; confirme as exigências "
               "aplicáveis aos seus clientes antes de investir.")


# ----------------------------------------------------------------------------- novos módulos
def _base_planta():
    """Valores da empresa (se já importou dados na aba Sua empresa) ou da referência do artigo."""
    if "res_emp" in st.session_state:
        cal, res = st.session_state["res_emp"]
        k, par = res["kpis"], cal["parametros"]
        return {"origem": "dados da sua empresa", "eletr": k["eletr_kwh_t"], "gas": k["gn_m3_t"],
                "agua": 0.0 if k["agua_m3_t"] != k["agua_m3_t"] else k["agua_m3_t"],
                "t_dia": par["textil_t_dia"][0], "dias": par.get("dias_operacao", (300.0,))[0], "kpis": k}
    ref = {"eletr_kwh_t": 808.0, "gn_m3_t": 1143.0, "agua_m3_t": 170.0}
    return {"origem": "referência de SC do artigo (importe seus dados na aba Sua empresa para personalizar)",
            "eletr": 808.0, "gas": 1143.0, "agua": 170.0, "t_dia": 10.0, "dias": 300.0, "kpis": ref}


def _mostrar_modulo(nome, r, unidade_extra=None):
    st.session_state.setdefault("mods", {})[nome] = r
    a, b, c, d = st.columns(4)
    a.metric("Economia", f"R$ {r['economia_r_ano']:,.0f}/ano".replace(",", "."), help="Dinheiro que deixa de ser gasto por ano.")
    b.metric("CO₂e evitado", f"{r['co2e_evitado_t_ano']:,.0f} t/ano".replace(",", "."), help="Emissões que deixam de ocorrer por ano.")
    c.metric("Investimento", f"R$ {r['capex_r']:,.0f}".replace(",", "."), help="Valor digitado por você (hipótese).")
    d.metric("Retorno simples", "—" if r["payback_anos"] != r["payback_anos"] else f"{r['payback_anos']:.1f} anos",
             help="Investimento dividido pela economia anual, sem juros nem impostos.")
    with st.expander("Premissas e de onde vêm (edite as entradas acima para testar)"):
        st.dataframe(pd.DataFrame(r["premissas"]).set_index("Premissa"))
        st.caption("Referência pública = registro do projeto; Hipótese = valor a confirmar com medição, orçamento ou fornecedor.")
    if r.get("nota"):
        st.info(r["nota"])


def mod_calor(b):
    st.markdown("**Recuperação de calor do efluente.** Usa o calor do efluente quente para pré-aquecer a água que entra e reduzir o gás da caldeira.")
    c1, c2, c3 = st.columns(3)
    vazao = c1.number_input("Vazão de efluente (m³/dia)", 1.0, 20000.0, min(max(float(round(b["agua"] * b["t_dia"] * 0.9)), 1.0), 20000.0), 10.0,
                            help="Por padrão, 90 % da água usada por dia.")
    t_ef = c2.number_input("Temperatura do efluente na saída (°C)", 25.0, 95.0, 45.0, 1.0, help="Medida antes da estação de tratamento.")
    t_in = c2.number_input("Temperatura da água que entra (°C)", 5.0, 40.0, 22.0, 1.0)
    efi = c3.number_input("Eficiência do trocador (0 a 1)", 0.1, 0.9, 0.5, 0.05, help="Trocadores com incrustação rendem menos.")
    preco = c3.number_input("Preço do gás (R$/m³)", 0.5, 10.0, 2.61, 0.01)
    capex = c1.number_input("Investimento (R$)", 0.0, 50_000_000.0, 400_000.0, 10_000.0, help="Orçamento do trocador e da tubulação.")
    r = M.recuperacao_calor(vazao, t_ef, t_in, efi, b["dias"], preco, capex)
    gas_ano = b["gas"] * b["t_dia"] * b["dias"]
    if gas_ano > 0:
        part = r["gas_evitado_m3_ano"] / gas_ano
        st.metric("Parcela do gás da planta que seria evitada", f"{100 * part:.0f} %")
        if part > 0.4:
            st.warning("Economia acima de 40 % do gás da planta: confira a temperatura do efluente e a vazão. Valores altos costumam vir de efluente quente demais ou de vazão superestimada.")
    _mostrar_modulo("Recuperação de calor", r)


def mod_tarifa(b):
    st.markdown("**Programação da produção por tarifa.** Desloca parte da carga elétrica do horário de ponta (caro) para o fora de ponta.")
    c1, c2, c3 = st.columns(3)
    ini = c1.number_input("Início da ponta (hora)", 0, 23, 18, 1, help="Confirme o horário de ponta com a sua distribuidora.")
    fim = c1.number_input("Fim da ponta (hora)", 1, 24, 21, 1)
    tp = c2.number_input("Tarifa de ponta (R$/kWh)", 0.0, 5.0, float(M.v("celesc_a4v_ponta")), 0.01, help="Referência: Celesc A4 Verde, sem tributos.")
    tf = c2.number_input("Tarifa fora de ponta (R$/kWh)", 0.0, 5.0, float(M.v("celesc_a4v_fponta")), 0.01)
    frac = c3.slider("Parte da carga de ponta que pode ser deslocada", 0.0, 1.0, 0.3, 0.05,
                     help="Exemplos: lotes que podem começar antes ou depois da ponta, bombas e compressores com reserva.")
    capex = c3.number_input("Investimento (R$)", 0.0, 10_000_000.0, 0.0, 5_000.0, help="Normalmente baixo (automação e reorganização de turnos).")
    df = st.session_state.get("df_emp")
    if df is not None:
        kp, kt, nd = M.energia_por_janela(df, int(ini), int(fim))
        ano = b["dias"] / max(nd, 1)
        kp_ano, kt_ano = kp * ano, kt * ano
        st.caption(f"Perfil horário lido do seu arquivo: {nd} dias de produção; {100 * kp / kt:.0f} % da energia cai na ponta.")
    else:
        kt_ano = b["eletr"] * b["t_dia"] * b["dias"]
        kp_ano = kt_ano * max(0.0, (fim - ini)) / 16.0
        st.caption("Sem perfil horário (nenhum arquivo importado): admiti produção em 16 h por dia para estimar a parcela na ponta.")
    r = M.programacao_tarifa(kp_ano, kt_ano, frac, tp, tf, capex)
    st.metric("Energia que cai na ponta", f"{kp_ano:,.0f} kWh/ano".replace(",", "."))
    _mostrar_modulo("Programação por tarifa", r)


def mod_coletiva(b):
    st.markdown("**Compra coletiva de gás.** Várias empresas contratam juntas e, com mais volume, conseguem preço menor; se o grupo comprar biometano do hub, há também ganho de carbono.")
    gas_dia = b["gas"] * b["t_dia"]
    txt = st.text_area("Empresas e demanda de gás (uma por linha: nome; m³/dia)",
                       f"Sua empresa; {gas_dia:.0f}\nEmpresa B (exemplo); 4000\nEmpresa C (exemplo); 7000", height=110)
    dem = {}
    for linha in txt.splitlines():
        if ";" in linha:
            n, q = linha.rsplit(";", 1)
            try:
                dem[n.strip()] = float(q.strip().replace(",", "."))
            except ValueError:
                st.warning(f"Não entendi a linha: {linha}")
    c1, c2, c3 = st.columns(3)
    pb = c1.number_input("Preço do gás sem desconto (R$/m³)", 0.5, 10.0, 2.61, 0.01)
    dmax = c2.slider("Desconto máximo por volume", 0.0, 0.3, 0.08, 0.01, help="Hipótese: peça a tabela real à distribuidora.")
    vsat = c2.number_input("Volume que dá o desconto máximo (m³/dia)", 1000.0, 200_000.0, 20_000.0, 1000.0)
    hub = c3.number_input("Biometano do hub contratado pelo grupo (m³/dia)", 0.0, 100_000.0, 0.0, 500.0, help="O artigo usa um hub de cerca de 10.000 m³/dia.")
    if not dem:
        st.info("Informe pelo menos uma empresa."); return
    r = M.compra_coletiva(dem, pb, dmax, vsat, b["dias"], hub)
    st.dataframe(pd.DataFrame(r["tabela"]).set_index("Empresa").style.format(
        {"Demanda (m³/dia)": "{:.0f}", "Preço sozinha (R$/m³)": "{:.2f}", "Preço no grupo (R$/m³)": "{:.2f}", "Economia (R$/ano)": "{:,.0f}"}))
    st.caption(f"Demanda total do grupo: {r['demanda_total_m3_dia']:,.0f} m³/dia; cobertura pelo hub: {100 * r['cobertura_hub']:.0f} %.".replace(",", "."))
    _mostrar_modulo("Compra coletiva de gás", r)


def mod_lodo(b):
    st.markdown("**Lodo da ETE em biogás.** Digestão anaeróbia do lodo da estação de tratamento para gerar energia térmica no local.")
    c1, c2, c3 = st.columns(3)
    lodo = c1.number_input("Lodo gerado (t de matéria seca por dia)", 0.0, 100.0, 0.5, 0.1, help="Informe o valor medido na ETE.")
    sv = c1.slider("Fração de sólidos voláteis", 0.2, 0.9, 0.6, 0.05)
    rend = c2.number_input("Rendimento de metano (m³ CH₄ por kg de sólido volátil)", 0.05, 0.6, 0.2, 0.01, help="Só o ensaio BMP confirma.")
    prop = c2.slider("Consumo próprio do digestor", 0.0, 0.6, 0.25, 0.05)
    preco = c3.number_input("Preço do gás substituído (R$/m³)", 0.5, 10.0, 2.61, 0.01)
    capex = c3.number_input("Investimento (R$)", 0.0, 50_000_000.0, 500_000.0, 10_000.0)
    r = M.biogas_lodo(lodo, sv, rend, prop, b["dias"], preco, b["gas"] * b["t_dia"] * b["dias"], capex)
    st.metric("Parcela do gás da planta substituída", f"{100 * r['cobertura_gas']:.1f} %")
    _mostrar_modulo("Lodo da ETE em biogás", r)


def mod_solar(b):
    st.markdown("**Energia solar.** Painéis fotovoltaicos reduzem a eletricidade da rede; coletores solares térmicos reduzem o gás do aquecimento de água.")
    hsp = st.number_input("Irradiação média diária no local (kWh/m²/dia)", 2.0, 7.0, 4.5, 0.1, help="Consulte o Atlas Brasileiro de Energia Solar ou o SunData para o seu município.")
    t1, t2 = st.tabs(["Painéis fotovoltaicos", "Solar térmica"])
    with t1:
        c1, c2, c3 = st.columns(3)
        ele_ano = b["eletr"] * b["t_dia"] * b["dias"]
        cob = c1.slider("Meta de cobertura da eletricidade", 0.05, 1.0, 0.3, 0.05)
        pr = c1.slider("Desempenho global (PR)", 0.6, 0.9, 0.78, 0.01)
        kwp0 = M.kwp_para_cobrir(ele_ano, cob, hsp, pr)
        kwp = c2.number_input("Potência instalada (kWp)", 1.0, 20000.0, min(float(round(max(kwp0, 1.0))), 20000.0), 10.0, help="Sugerida a partir da meta de cobertura.")
        auto = c2.slider("Parte da geração consumida no local", 0.3, 1.0, 0.9, 0.05)
        tar = c3.number_input("Tarifa de energia evitada (R$/kWh)", 0.1, 3.0, 0.58, 0.01)
        cx = c3.number_input("Custo instalado (R$/kWp)", 1000.0, 10000.0, 4000.0, 100.0, help="Peça orçamento a integradores.")
        _mostrar_modulo("Solar fotovoltaica", M.fotovoltaica(kwp, hsp, pr, auto, tar, cx))
    with t2:
        c1, c2, c3 = st.columns(3)
        area = c1.number_input("Área de coletores (m²)", 5.0, 20000.0, 400.0, 10.0)
        efi = c2.slider("Eficiência média do coletor", 0.2, 0.7, 0.5, 0.05)
        preco = c2.number_input("Preço do gás (R$/m³)", 0.5, 10.0, 2.61, 0.01, key="sol_gas")
        cx = c3.number_input("Custo instalado (R$/m²)", 300.0, 5000.0, 1500.0, 50.0)
        _mostrar_modulo("Solar térmica", M.solar_termica(area, hsp, efi, b["dias"], preco, cx))


def mod_circular(b):
    st.markdown("**Circularidade têxtil.** Retalhos e refugo viram fibra reciclada em vez de resíduo, gerando receita e evitando emissões de fibra virgem.")
    c1, c2, c3 = st.columns(3)
    prod = c1.number_input("Produção (t/ano)", 10.0, 200_000.0, min(max(float(round(b["t_dia"] * b["dias"])), 10.0), 200_000.0), 50.0)
    perda = c1.slider("Perda de tecido (aparas e refugo, %)", 0.5, 15.0, 3.0, 0.5)
    rec = c2.slider("Parcela reciclável (%)", 0, 100, 60, 5, help="Aparas limpas e separadas por fibra e cor.")
    subst = c2.slider("Quanto da fibra reciclada substitui fibra virgem", 0.2, 1.0, 0.8, 0.05)
    venda = c3.number_input("Preço de venda das aparas (R$/t)", 0.0, 5000.0, 300.0, 50.0)
    dest = c3.number_input("Custo de destinação evitado (R$/t)", 0.0, 2000.0, 200.0, 25.0)
    _mostrar_modulo("Circularidade têxtil", M.circularidade(prod, perda, rec, venda, dest, subst))


def mod_passaporte(b):
    st.markdown("**Passaporte digital do produto.** Gera um documento por lote com a pegada de energia, água e carbono, com selo de integridade (SHA-256) para detectar adulteração.")
    c1, c2, c3 = st.columns(3)
    lote = c1.text_input("Número do lote", "L-2026-0001")
    cliente = c1.text_input("Cliente", "")
    artigo = c2.text_input("Artigo (tipo de tecido)", "Malha")
    comp = c2.text_input("Composição", "100% poliéster")
    massa = c3.number_input("Massa do lote (t)", 0.01, 500.0, 2.0, 0.1)
    fibra = c3.selectbox("Fibra principal", ["Poliéster virgem", "Poliéster reciclado (rPET)", "Outra (informar fator)"])
    ef = {"Poliéster virgem": float(M.v("ef_pes_virgem")), "Poliéster reciclado (rPET)": float(M.v("ef_pes_rpet"))}.get(fibra)
    if ef is None:
        ef = st.number_input("Fator de emissão da fibra (kgCO₂e/kg)", 0.0, 50.0, 0.0, 0.1, help="Peça ao fornecedor da fibra.")
    p = M.passaporte({"id": lote, "cliente": cliente, "artigo": artigo, "composicao": comp, "massa_t": massa}, b["kpis"], ef,
                     f"médias de {b['origem']}")
    g = p["pegada_do_lote"]
    a, bb, c = st.columns(3)
    a.metric("CO₂e do lote", f"{g['co2e_total_kg']:,.0f} kg".replace(",", "."))
    bb.metric("CO₂e por kg de tecido", f"{g['co2e_kg_por_kg_tecido']:.2f} kg")
    c.metric("Água do lote", "—" if g["agua_m3"] is None else f"{g['agua_m3']:.0f} m³")
    st.caption(f"Selo de integridade (SHA-256): {p['selo_integridade_sha256'][:24]}...")
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ Baixar passaporte (JSON)", json.dumps(p, indent=2, ensure_ascii=False), f"passaporte_{lote}.json")
    d2.download_button("⬇️ Baixar passaporte (Markdown)", M.passaporte_markdown(p), f"passaporte_{lote}.md")
    st.info("Modelo de demonstração, não oficial. Os valores por lote vêm de intensidades médias da planta; para auditoria, meça por lote. "
            "Fatores da fibra: Textile Exchange/SCS (poliéster). Confirme os requisitos dos seus clientes e a regulamentação aplicável.")


MODULOS = {"Passaporte digital do produto": mod_passaporte, "Recuperação de calor do efluente": mod_calor,
           "Programação da produção por tarifa": mod_tarifa, "Compra coletiva de gás": mod_coletiva,
           "Lodo da ETE em biogás": mod_lodo, "Energia solar": mod_solar, "Circularidade têxtil": mod_circular}


def aba_modulos():
    st.subheader("Módulos exploratórios")
    st.warning("Esta aba usa premissas de hipótese e serve só para pré-viabilidade interna. **Não use estes números em publicação.** Para resultados citáveis, use a aba Contribuir com dados.")
    b = _base_planta()
    st.caption(f"Base de cálculo: {b['origem']}. Eletricidade {b['eletr']:.0f} kWh/t, gás {b['gas']:.0f} m³/t, "
               f"{b['t_dia']:.1f} t/dia, {b['dias']:.0f} dias por ano.")
    st.write("Cada módulo é uma **estimativa de pré-viabilidade** com premissas visíveis e editáveis. Os valores marcados como hipótese "
             "precisam de medição, orçamento ou confirmação do fornecedor antes de qualquer decisão.")
    nome = st.selectbox("Escolha o módulo", list(MODULOS))
    MODULOS[nome](b)
    mods = st.session_state.get("mods", {})
    if mods:
        st.markdown("### Resumo dos módulos que você já calculou")
        tab = pd.DataFrame({n: {"Economia (R$/ano)": r["economia_r_ano"], "CO₂e evitado (t/ano)": r["co2e_evitado_t_ano"],
                                "Investimento (R$)": r["capex_r"],
                                "Retorno (anos)": r["payback_anos"]} for n, r in mods.items()}).T
        st.dataframe(tab.style.format({"Economia (R$/ano)": "{:,.0f}", "CO₂e evitado (t/ano)": "{:,.0f}",
                                       "Investimento (R$)": "{:,.0f}", "Retorno (anos)": "{:.1f}"}))
        st.caption("Atenção: recuperação de calor, solar térmica, lodo em biogás e biometano substituem o mesmo gás. "
                   "Os ganhos não são somáveis sem verificar se o total evitado cabe no consumo de gás da planta.")


st.title("🏭 DT2-SC · gêmeo digital da cadeia têxtil")
st.caption("Sustentabilidade da cadeia de suprimentos: água, energia, carbono e troca de resíduo por energia entre empresas.")
t0, t2, t1, t8, t6, t7, t5, t3, t4 = st.tabs(["🏁 Comece aqui", "🏭 Sua empresa", "📄 Resultados do artigo", "📅 Programação colaborativa", "📥 Contribuir com dados", "🔬 Painel do pesquisador", "🧩 Módulos (exploratório)", "🧠 Gêmeo digital", "🌱 Outras contribuições"])
with t0:
    aba_inicio()
with t2:
    aba_empresa()
with t1:
    aba_artigo()
with t8:
    ui_programacao.aba_programacao()
with t6:
    ui_coleta.aba_contribuir()
with t7:
    ui_coleta.aba_pesquisador()
with t5:
    aba_modulos()
with t3:
    aba_gemeo()
with t4:
    aba_contribuicoes()
