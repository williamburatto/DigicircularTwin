"""Plataforma DT2-SC (acesso fechado): cada indústria entra com login próprio, envia os dados da planta
e vê diagnóstico, calibração do gêmeo e cenários. Executar:  streamlit run app.py
Variáveis: DT2SC_DADOS (pasta de dados), DT2SC_ADMIN_USER / DT2SC_ADMIN_PASS (criação do 1º administrador),
ou o mesmo em .streamlit/secrets.toml (chaves admin_user, admin_pass)."""
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
from dt2sc.acesso import MAX_UPLOAD_MB, Plataforma  # noqa: E402

TIMEOUT_S = 3600
st.set_page_config(page_title="DT2-SC · Plataforma industrial", page_icon="🏭", layout="wide")


@st.cache_resource
def plataforma():
    return Plataforma()


plat = plataforma()


def _segredo(chave, env):
    try:
        return st.secrets.get(chave) or os.environ.get(env)
    except Exception:
        return os.environ.get(env)


def _demo():
    """Modo demonstração (secrets: demo_user, demo_pass): empresa fictícia com dados sintéticos."""
    du, dp = _segredo("demo_user", "DT2SC_DEMO_USER"), _segredo("demo_pass", "DT2SC_DEMO_PASS")
    if du and dp and "demo" not in plat.empresas():
        plat.criar_empresa("demo", "Empresa Demonstração (dados sintéticos)")
        plat.criar_usuario(du, dp, "demo")
    if du and dp and "demo" in plat.empresas() and not plat.listar_uploads("demo"):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            P.exemplo_csv(f"{d}/ex.csv", 14)
            plat.salvar_upload("demo", "dados_sinteticos.csv", open(f"{d}/ex.csv", "rb").read(), "sistema")


def _bootstrap():
    if plat.usuarios():
        _demo()
        return True
    u, s = _segredo("admin_user", "DT2SC_ADMIN_USER"), _segredo("admin_pass", "DT2SC_ADMIN_PASS")
    if u and s:
        plat.criar_usuario(u, s, None, "admin")
        _demo()
        return True
    st.error("Nenhum usuário cadastrado. Defina DT2SC_ADMIN_USER e DT2SC_ADMIN_PASS (ou admin_user/admin_pass em "
             "secrets.toml) para criar o primeiro administrador e reinicie.")
    return False


def _login():
    st.title("🏭 DT2-SC · Plataforma industrial")
    st.caption("Acesso restrito a empresas cadastradas. Os dados de cada empresa são isolados dos demais.")
    with st.form("login"):
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        enviar = st.form_submit_button("Entrar")
    if enviar:
        ate = plat.bloqueado_ate(usuario)
        if ate > time.time():
            st.error(f"Muitas tentativas. Tente novamente em {int(ate - time.time())} s.")
            return
        sessao = plat.autenticar(usuario, senha)
        if sessao:
            st.session_state["sessao"] = sessao
            st.session_state["ultimo"] = time.time()
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")


def _expirada():
    s = st.session_state
    if "sessao" in s and time.time() - s.get("ultimo", 0) > TIMEOUT_S:
        s.clear()
        st.warning("Sessão expirada por inatividade. Entre novamente.")
        return True
    s["ultimo"] = time.time()
    return False


def _dados_empresa(emp, cfg, nomes):
    """Concatena os arquivos escolhidos (mesmo mapeamento) e devolve o DataFrame padronizado."""
    brutos = [pd.read_csv(plat.ler_upload(emp, n), sep=None, engine="python") for n in nomes]
    bruto = pd.concat(brutos, ignore_index=True)
    return bruto, P.carregar(bruto, cfg.get("mapa") or None, cfg.get("fator") or None)


# ------------------------------------------------------------------ páginas da empresa
def pag_enviar(emp, usuario):
    st.header("Enviar dados da planta")
    st.write(f"CSV do SCADA/historiador (até {MAX_UPLOAD_MB} MB por arquivo). Obrigatórias: **timestamp**, "
             "**producao_kg_h**, **eletrica_kw**. Opcionais: gn_m3_h, agua_m3_h, cavaco_kg_h, vapor_kg_h, "
             "temp_efluente_c, ph.")
    arqs = st.file_uploader("Selecione um ou mais CSV", type=["csv", "txt"], accept_multiple_files=True)
    if arqs and st.button("Salvar na plataforma"):
        for a in arqs:
            try:
                st.success(f"Salvo: {plat.salvar_upload(emp, a.name, a.getvalue(), usuario)}")
            except ValueError as e:
                st.error(f"{a.name}: {e}")
    ups = plat.listar_uploads(emp)
    st.subheader("Arquivos da empresa")
    if not ups:
        st.info("Nenhum arquivo enviado ainda.")
        return
    st.dataframe(pd.DataFrame(ups))
    apagar = st.selectbox("Apagar arquivo", [None] + [u["nome"] for u in ups])
    if apagar and st.button("Confirmar exclusão"):
        plat.apagar_upload(emp, apagar, usuario)
        st.rerun()


def pag_config(emp, usuario):
    st.header("Colunas, unidades e parâmetros locais")
    ups = plat.listar_uploads(emp)
    if not ups:
        st.info("Envie um arquivo primeiro.")
        return
    cfg = plat.config(emp)
    nome = st.selectbox("Arquivo de referência para o mapeamento", [u["nome"] for u in ups])
    bruto = pd.read_csv(plat.ler_upload(emp, nome), sep=None, engine="python", nrows=2000)
    sug = {**P.detectar_mapa(bruto.columns), **{k: x for k, x in cfg["mapa"].items() if x in bruto.columns}}
    opc = [None] + list(bruto.columns)
    cols = st.columns(3)
    mapa, fator = {}, {}
    for i, c in enumerate(P.COLUNAS):
        with cols[i % 3]:
            pad = sug.get(c)
            mapa[c] = st.selectbox(c + (" *" if c in P.OBRIGATORIAS else ""), opc,
                                   index=opc.index(pad) if pad in opc else 0, key=f"m_{c}")
            if c != "timestamp":
                fator[c] = st.number_input(f"multiplicador {c}", value=float(cfg["fator"].get(c, 1.0)),
                                           format="%g", key=f"f_{c}")
    st.subheader("Parâmetros locais (opcionais; 0 = usar referência pública)")
    a, b, c = st.columns(3)
    tarifa = a.number_input("Preço pago pelo gás (R$/m³)", 0.0, 10.0, float(cfg["tarifa_gas"]), 0.01)
    cavaco = b.number_input("Cavaco local (R$/t)", 0.0, 2000.0, float(cfg["cavaco_r_t"]), 10.0)
    gate = c.number_input("Taxa de destinação paga hoje (R$/t)", 0.0, 1000.0, float(cfg["gate_fee"]), 5.0)
    if st.button("Salvar configuração"):
        plat.salvar_config(emp, {"mapa": {k: x for k, x in mapa.items() if x}, "fator": fator,
                                 "tarifa_gas": tarifa, "cavaco_r_t": cavaco, "gate_fee": gate}, usuario)
        st.success("Configuração salva.")


def pag_diagnostico(emp, usuario):
    st.header("Diagnóstico da planta")
    ups = plat.listar_uploads(emp)
    if not ups:
        st.info("Envie arquivos primeiro.")
        return
    nomes = st.multiselect("Arquivos a analisar", [u["nome"] for u in ups], default=[u["nome"] for u in ups][-1:])
    if not nomes:
        return
    cfg = plat.config(emp)
    try:
        _, df = _dados_empresa(emp, cfg, nomes)
        q, cal = P.qualidade(df), None
        cal = P.calibrar(df)
    except ValueError as e:
        st.error(str(e)); return
    a, b, c, d = st.columns(4)
    a.metric("Linhas", q["linhas"]); b.metric("Dias", f"{q['dias']:.1f}")
    c.metric("Passo (min)", f"{q['passo_min']:.0f}"); d.metric("Horas de produção", f"{q['horas_producao']:.0f}")
    st.dataframe(pd.DataFrame(q["por_coluna"]).T)
    k = cal["kpis"]
    a, b, c, d = st.columns(4)
    a.metric("Eletricidade (kWh/t)", f"{k['eletr_kwh_t']:.0f}")
    b.metric("Gás natural (m³/t)", f"{k['gn_m3_t']:.0f}")
    c.metric("Água (m³/t)", f"{k['agua_m3_t']:.1f}")
    d.metric("CO₂e energia (kg/t)", f"{k['co2e_energia_kg_t']:.0f}")
    for av in cal["avisos"]:
        st.warning(av)
    dia = P.intensidades_diarias(df)
    if len(dia):
        st.line_chart(dia[["eletr_kwh_t", "agua_m3_t"]])
    an = P.anomalias(df)
    st.subheader(f"Anomalias ({len(an)})")
    st.dataframe(an)


def pag_cenarios(emp, usuario):
    st.header("Cenários e economia")
    ups = plat.listar_uploads(emp)
    if not ups:
        st.info("Envie arquivos primeiro.")
        return
    nomes = st.multiselect("Arquivos", [u["nome"] for u in ups], default=[u["nome"] for u in ups][-1:])
    n = st.select_slider("Amostras Monte Carlo", [500, 1000, 3000, 10000], value=1000)
    if nomes and st.button("Rodar simulação"):
        cfg = plat.config(emp)
        try:
            _, df = _dados_empresa(emp, cfg, nomes)
            cal = P.calibrar(df)
            with st.spinner("Monte Carlo..."):
                res = P.avaliar_planta(cal, n, cfg["tarifa_gas"] or None, cfg["cavaco_r_t"] or None,
                                       cfg["gate_fee"] or None)
        except ValueError as e:
            st.error(str(e)); return
        res["relatorio_md"] = P.relatorio_md(cal, res, P.anomalias(df), P.qualidade(df))
        res["arquivos"] = nomes
        nome = plat.salvar_resultado(emp, res, usuario)
        st.success(f"Resultado salvo no histórico ({nome}).")
        _mostrar(res)


def _mostrar(res):
    linhas = [{"Cenário": c, "SEI": r["sei"]["media"], "CO₂e (kg/t)": r["co2_tex_kg_t"]["media"],
               "Água (m³/t)": r["agua_tex_m3_t"]["media"]} for c, r in res["cenarios"].items()]
    t = pd.DataFrame(linhas).set_index("Cenário")
    st.dataframe(t)
    st.bar_chart(t[["CO₂e (kg/t)"]])
    if "economia" in res:
        st.json(res["economia"])
    st.download_button("Baixar relatório (Markdown)", res.get("relatorio_md", ""), "dt2sc_relatorio.md")


def pag_historico(emp, usuario):
    st.header("Histórico de simulações")
    L = plat.listar_resultados(emp)
    if not L:
        st.info("Nenhuma simulação salva.")
        return
    esc = st.selectbox("Simulação", L)
    _mostrar(plat.ler_resultado(emp, esc))


def pag_conta(emp, usuario):
    st.header("Minha conta")
    with st.form("senha"):
        nova = st.text_input("Nova senha (mín. 10 caracteres)", type="password")
        ok = st.form_submit_button("Alterar senha")
    if ok:
        try:
            plat.alterar_senha(usuario, nova)
            st.success("Senha alterada.")
        except ValueError as e:
            st.error(str(e))
    st.subheader("Atividade recente da empresa")
    st.dataframe(pd.DataFrame(plat.ler_auditoria(100, emp) if emp else plat.ler_auditoria(100)))


# ------------------------------------------------------------------ guia passo a passo
MODELO_CSV = ("timestamp,producao_kg_h,eletrica_kw,gn_m3_h,agua_m3_h,cavaco_kg_h,vapor_kg_h,temp_efluente_c,ph\n"
              "2026-03-02 06:00,420,310,480,52,0,,34,7.2\n2026-03-02 07:00,455,335,510,55,0,,35,7.0\n"
              "2026-03-02 08:00,440,325,495,54,0,,34,7.1\n")


def _ult(res, prefixo, grupo, metrica="media"):
    for nome, r in res["cenarios"].items():
        if nome.startswith(prefixo):
            return r[grupo][metrica]
    return None


def pag_guia(emp, usuario):
    st.header("Guia passo a passo: do dado da planta à cadeia mais sustentável")
    st.write("Este guia mostra o que a empresa precisa inserir e como cada resultado se liga às contribuições do "
             "artigo (IET Collaborative Intelligent Manufacturing): gêmeo digital federado, controle em malha fechada, "
             "troca de resíduo por energia entre empresas e negociação com decisão humana.")
    ups = plat.listar_uploads(emp)
    cfg = plat.config(emp)
    res_l = plat.listar_resultados(emp)
    feitos = [bool(ups), bool(cfg.get("mapa")), bool(ups), bool(res_l)]
    st.progress(sum(feitos) / 4, text=f"Progresso da empresa: {sum(feitos)} de 4 etapas concluídas")

    with st.expander(("✅ " if feitos[0] else "1️⃣ ") + "Passo 1 · Reunir e enviar os dados (menu: Enviar dados)", expanded=not feitos[0]):
        st.markdown("""
| O que inserir | Onde a empresa encontra | Para quê |
|---|---|---|
| **Produção (kg/h)**, **energia elétrica (kW)**, **gás natural (m³/h)**, **água (m³/h)** | SCADA, historiador, medidores | Mede kWh/t, m³ de gás/t e água/t reais |
| **Temperatura e pH do efluente** | Estação de tratamento | Checa os limites legais (CONAMA 430) |
| **Cavaco (kg/h)** e **vapor (kg/h)** | Caldeira | Compara combustíveis |
| Mínimo de **4 semanas**; o ideal é **12 meses**, em passo de 15 a 60 min | | Quanto mais dados, menor a incerteza |

Obrigatórias: `timestamp`, `producao_kg_h`, `eletrica_kw`. As demais melhoram o resultado, mas são opcionais.""")
        st.download_button("Baixar modelo de CSV", MODELO_CSV, "modelo_planta.csv")
    with st.expander(("✅ " if feitos[1] else "2️⃣ ") + "Passo 2 · Conferir colunas, unidades e preços locais (menu: Colunas e parâmetros)", expanded=feitos[0] and not feitos[1]):
        st.markdown("""
- Confirme se cada coluna do seu arquivo foi reconhecida; se os valores estiverem em W em vez de kW, informe o multiplicador `0,001`.
- Informe o **preço que a empresa paga pelo gás** (R$/m³), o **preço do cavaco** na região (R$/t) e, se o frigorífico parceiro paga **taxa de destinação** de resíduos (R$/t), informe também.
- Campos em 0 usam a referência pública do artigo (paridade do biometano Argus e cotações regionais de cavaco).""")
    with st.expander(("✅ " if feitos[2] else "3️⃣ ") + "Passo 3 · Ler o diagnóstico (menu: Diagnóstico)", expanded=feitos[1] and not res_l):
        st.markdown("""
Veja a **qualidade dos dados** (lacunas e faltantes), as **intensidades da planta** (kWh/t, m³ de gás/t, água/t, CO₂e/t) e as
**anomalias** (consumo fora do padrão e efluente acima dos limites). Esse é o ponto de partida de cada ação de melhoria.
Com poucos dias de dados, o sistema avisa e usa uma faixa de incerteza de ±15 %.""")
    with st.expander(("✅ " if feitos[3] else "4️⃣ ") + "Passo 4 · Comparar cenários (menu: Cenários e economia)", expanded=feitos[2] and not feitos[3]):
        st.markdown("""
O gêmeo é calibrado com os dados da planta e compara cinco situações:

| Cenário | O que representa |
|---|---|
| **S0** | Cada empresa decide sozinha (base) |
| **S1** | Gêmeo digital recomenda, sem realimentação |
| **S2** | Controle em malha fechada (PI): a operação se ajusta sozinha ao desvio medido |
| **S3** | S2 + hub de biometano com resíduo do frigorífico |
| **S4** | S3 + contrato de fornecimento negociado entre as empresas |

Cada indicador vem com a média e a faixa entre o percentil 5 e o 95 (10 mil simulações no padrão do artigo).""")
    with st.expander("5️⃣ Passo 5 · Transformar o resultado em decisão"):
        st.markdown("""
- **Decida com a equipe.** O sistema recomenda, e a decisão é humana (princípio *human-in-the-loop* do artigo).
- **Compare o biometano com o cavaco.** O preço de equilíbrio do biometano é comparado ao gás natural (paridade) e ao cavaco local.
  Se a planta queima só cavaco, a opção de biometano não se aplica.
- **Leve o resultado para a negociação** com o frigorífico e o fornecedor de energia, com volume e faixa de preço respaldados por dados.
- **Repita a cada trimestre** com dados novos e acompanhe o histórico.""")

    st.subheader("Como isso melhora a sustentabilidade da cadeia de suprimentos")
    c1, c2, c3 = st.columns(3)
    c1.markdown("**💧 Água**\n\nO controle em malha fechada ajusta o uso de água ao desvio medido, e o reúso entra como meta rastreável por tonelada de tecido.")
    c2.markdown("**🔥 Energia e carbono**\n\nTrocar parte do gás natural por biometano de resíduo do frigorífico reduz o CO₂e fóssil; o cavaco (biogênico) é a alternativa onde já existe caldeira a biomassa.")
    c3.markdown("**♻️ Circularidade**\n\nO resíduo orgânico do frigorífico vira energia da tinturaria. A cadeia deixa de pagar destinação e passa a ter um contrato de fornecimento.")
    st.caption("Resultados do artigo são valores do modelo com dados de literatura. Os da sua empresa aparecem abaixo quando houver simulação.")

    if res_l:
        res = plat.ler_resultado(emp, res_l[0])
        st.subheader("Resultados da sua empresa (última simulação)")
        a_s0, a_s2 = _ult(res, "S0", "agua_tex_m3_t"), _ult(res, "S2", "agua_tex_m3_t")
        c_s0, c_s2, c_s4 = (_ult(res, p, "co2_tex_kg_t") for p in ("S0", "S2", "S4"))
        a, b, c = st.columns(3)
        if a_s0 and a_s2:
            a.metric("Água por tonelada, S0 → S2", f"{a_s2:.0f} m³/t", f"{100 * (a_s2 - a_s0) / a_s0:.0f} %", delta_color="inverse")
        if c_s0 and c_s4:
            b.metric("CO₂e por tonelada, S0 → S4", f"{c_s4:.0f} kg/t", f"{100 * (c_s4 - c_s0) / c_s0:.0f} %", delta_color="inverse")
        elif c_s0 and c_s2:
            b.metric("CO₂e por tonelada, S0 → S2", f"{c_s2:.0f} kg/t", f"{100 * (c_s2 - c_s0) / c_s0:.0f} %", delta_color="inverse")
        e = res.get("economia", {})
        if "prob_competitivo_com_gate" in e:
            c.metric("Biometano competitivo (com taxa de destinação)", f"{100 * e['prob_competitivo_com_gate']:.0f} %")
            st.info(f"Sem a taxa de destinação, o biometano é competitivo em {100 * e['prob_competitivo_sem_gate']:.0f} % das simulações. "
                    "A economia da troca de resíduo por energia depende de quem paga a destinação.")
    else:
        st.info("Complete os passos 1 a 4 para ver aqui a redução de água e de CO₂e da sua planta.")

# ------------------------------------------------------------------ administração
def pag_admin(usuario):
    st.header("Administração")
    st.caption("O administrador gerencia empresas e usuários; não há tela para ler os dados das empresas.")
    t1, t2, t3 = st.tabs(["Empresas", "Usuários", "Auditoria"])
    with t1:
        st.dataframe(pd.DataFrame(plat.empresas()).T)
        with st.form("nova_emp"):
            eid = st.text_input("Identificador (ex.: tinturaria-alfa)")
            nome = st.text_input("Nome da empresa")
            if st.form_submit_button("Criar empresa"):
                try:
                    plat.criar_empresa(eid, nome, usuario); st.success("Empresa criada."); st.rerun()
                except ValueError as e:
                    st.error(str(e))
    with t2:
        u = {k: {x: y for x, y in v.items() if x != "hash"} for k, v in plat.usuarios().items()}
        st.dataframe(pd.DataFrame(u).T)
        with st.form("novo_usr"):
            nu = st.text_input("Usuário")
            ns = st.text_input("Senha inicial (mín. 10 caracteres)", type="password")
            ne = st.selectbox("Empresa", list(plat.empresas()) or [None])
            npap = st.selectbox("Papel", ["empresa", "admin"])
            if st.form_submit_button("Criar usuário"):
                try:
                    plat.criar_usuario(nu, ns, ne, npap, usuario); st.success("Usuário criado."); st.rerun()
                except ValueError as e:
                    st.error(str(e))
        alvo = st.selectbox("Redefinir senha / ativar / desativar", [None] + [k for k in plat.usuarios() if k != usuario])
        if alvo:
            ns2 = st.text_input("Nova senha", type="password", key="rs")
            a, b, c = st.columns(3)
            if a.button("Redefinir senha"):
                try:
                    plat.alterar_senha(alvo, ns2, usuario); st.success("Senha redefinida.")
                except ValueError as e:
                    st.error(str(e))
            if b.button("Desativar"):
                plat.definir_ativo(alvo, False, usuario); st.rerun()
            if c.button("Ativar"):
                plat.definir_ativo(alvo, True, usuario); st.rerun()
    with t3:
        st.dataframe(pd.DataFrame(plat.ler_auditoria(500)))


# ------------------------------------------------------------------ roteamento
if not _bootstrap():
    st.stop()
if "sessao" not in st.session_state or _expirada():
    _login()
    st.stop()

sess = st.session_state["sessao"]
with st.sidebar:
    nome_emp = plat.empresas().get(sess["empresa"], {}).get("nome", "Administração")
    st.markdown(f"**{nome_emp}**")
    st.caption(f"Usuário: {sess['usuario']}")
    if sess["papel"] == "admin":
        pagina = st.radio("Menu", ["Administração", "Minha conta"])
    else:
        pagina = st.radio("Menu", ["Guia passo a passo", "Enviar dados", "Colunas e parâmetros", "Diagnóstico", "Cenários e economia",
                                   "Histórico", "Minha conta"])
    if st.button("Sair"):
        plat.auditar(sess["usuario"], "logout", "")
        st.session_state.clear()
        st.rerun()

emp, usr = sess["empresa"], sess["usuario"]
if pagina == "Administração":
    pag_admin(usr)
elif pagina == "Minha conta":
    pag_conta(emp, usr)
else:
    {"Guia passo a passo": pag_guia, "Enviar dados": pag_enviar, "Colunas e parâmetros": pag_config, "Diagnóstico": pag_diagnostico,
     "Cenários e economia": pag_cenarios, "Histórico": pag_historico}[pagina](emp, usr)
