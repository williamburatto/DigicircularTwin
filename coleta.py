"""Coleta multiempresa de dados reais para substituir as hipóteses do modelo.

Ideia central: o próprio registro de parâmetros do modelo (fontes.py) diz o que falta medir. Cada item do esquema abaixo
aponta o parâmetro do registro que ele substitui. Cada empresa gera um *pacote de contribuição* (JSON) com consentimento e
selo de integridade, sem armazenar nada no servidor; a equipe de pesquisa agrega os pacotes, só publica estatísticas com
n >= K_MIN empresas, troca as hipóteses pelos valores medidos e roda de novo todas as análises do artigo.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import secrets
from contextlib import contextmanager
from datetime import datetime

import numpy as np

from . import fontes

VERSAO_ESQUEMA = "1.0"
K_MIN = 3                 # mínimo de empresas para publicar uma estatística (anonimato por agregação)
N_FAIXA_PERCENTIL = 10    # com menos empresas, a faixa é min-max; com mais, P5-P95

EVID = {"MED": "Medição própria (SCADA ou medidor)", "FAT": "Fatura ou nota fiscal", "LAU": "Laudo ou ensaio de laboratório",
        "CON": "Contrato, proposta ou orçamento", "PUB": "Base pública citada", "EST": "Estimativa (não entra na publicação)"}
PUBLICAVEL = ("MED", "FAT", "LAU", "CON", "PUB")
TIPOS = {"tinturaria": "Tinturaria / beneficiamento têxtil", "frigorifico": "Frigorífico / agroindústria",
         "usina": "Usina ou hub de biometano"}
CONSENTIMENTO_V1 = ("Autorizo o uso dos valores deste pacote em pesquisa científica e a publicação de estatísticas agregadas "
                    "(mediana e faixa), sem identificar a empresa. Estou ciente de que só serão divulgados resultados "
                    f"calculados com pelo menos {K_MIN} empresas e de que posso retirar o pacote antes da publicação.")


@dataclasses.dataclass(frozen=True)
class Item:
    id: str
    tipos: tuple
    bloco: str
    rotulo: str
    unidade: str
    ajuda: str
    reg: str | None = None            # parâmetro do registro que este item substitui
    lim: tuple = (0.0, 1e9)           # intervalo plausível
    pct: bool = False                 # informado em %, o registro guarda fração
    evid: tuple = ("MED", "FAT", "LAU", "CON", "PUB", "EST")
    obrig: bool = True
    modulo: str | None = None         # módulo de contribuição que usa o item
    auto: str | None = None           # chave de preenchimento automático a partir da planilha


def _I(*a, **k):
    return Item(*a, **k)


T, F, U = ("tinturaria",), ("frigorifico",), ("usina",)
ESQUEMA: list[Item] = [
    # ------------------------------------------------------------------ tinturaria
    _I("t_dia", T, "Perfil e escala", "Produção média nos dias de operação", "t/dia",
       "Toneladas de tecido processadas por dia de operação. Fonte: relatório de produção ou PCP.", "textil_t_dia", (0.5, 200), evid=("MED", "FAT"), auto="t_dia"),
    _I("dias_op", T, "Perfil e escala", "Dias de operação por ano", "dias/ano", "Dias em que a planta produziu nos últimos 12 meses.",
       "dias_operacao", (100, 365), evid=("MED",), auto="dias"),
    _I("sh_pes", T, "Perfil e escala", "Fração de poliéster no mix de fibras", "%", "Percentual em massa de poliéster (puro ou em mistura) no tecido processado.",
       "share_poliester", (0, 100), True, ("MED", "FAT")),
    _I("rpet_base", T, "Perfil e escala", "Teor médio atual de fibra reciclada", "%", "Percentual de fibra reciclada nos artigos atuais.",
       "rpet_base", (0, 100), True, ("MED", "FAT", "LAU")),
    _I("rpet_max", T, "Perfil e escala", "Máximo de fibra reciclada que seus produtos aceitam", "%", "Limite de qualidade do fio ou exigência do cliente (ficha técnica).",
       "rpet_max", (0, 100), True, ("LAU", "CON")),
    _I("eletr", T, "Consumo por tonelada", "Eletricidade", "kWh/t", "Energia elétrica do mês dividida pelas toneladas processadas.",
       "eletr_textil", (100, 4000), evid=("MED", "FAT"), auto="eletr"),
    _I("gn", T, "Consumo por tonelada", "Gás natural", "Nm³/t", "Gás do mês dividido pelas toneladas. Informe 0 se a caldeira usa só cavaco.",
       "gn_textil", (0, 4500), evid=("MED", "FAT"), auto="gas"),
    _I("agua", T, "Consumo por tonelada", "Água", "m³/t", "Água captada no mês dividida pelas toneladas.",
       "agua_textil_sc", (10, 500), evid=("MED", "FAT"), auto="agua"),
    _I("reuso", T, "Consumo por tonelada", "Água reutilizada hoje", "%", "Parcela da água do processo que volta ao processo.",
       "reuso_agua_max", (0, 90), True, ("MED",)),
    _I("f_term", T, "Consumo por tonelada", "Fração do calor que aquece água de processo", "%", "Do calor total usado, quanto serve para aquecer a água dos banhos (balanço de energia).",
       "fracao_termica_agua", (5, 95), True, ("MED", "LAU")),
    _I("ef_gas", T, "Caldeira e combustível", "Eficiência da caldeira a gás", "%", "Medida por análise de combustão ou balanço de energia.",
       "eficiencia_caldeira_gas", (50, 100), True, ("MED", "LAU"), obrig=False),
    _I("ef_cav", T, "Caldeira e combustível", "Eficiência da caldeira a cavaco", "%", "Medida por análise de combustão ou balanço de energia.",
       "eficiencia_caldeira_cavaco", (50, 100), True, ("MED", "LAU"), obrig=False),
    _I("cav_pci", T, "Caldeira e combustível", "Poder calorífico do cavaco", "MWh/t", "Laudo de laboratório do cavaco como recebido (com umidade).",
       "cavaco_pci", (1.5, 5.0), evid=("LAU",), obrig=False),
    _I("cav_dens", T, "Caldeira e combustível", "Densidade a granel do cavaco", "kg/m³", "Pesagem de um volume conhecido de cavaco.",
       "cavaco_densidade", (100, 500), evid=("MED", "LAU"), obrig=False),
    _I("tar_gn", T, "Preços", "Preço do gás natural pago", "R$/m³", "Valor da fatura sem tributos recuperáveis dividido pelo volume. Informe 0 se não usa gás.",
       "tarifa_gn_ind", (0.0, 10), evid=("FAT",), obrig=False),
    # ------------------------------------------------------------------ frigorífico
    _I("ag_suino", F, "Frigorífico", "Água por suíno abatido", "L/suíno", "Consumo total de água dividido pelos animais abatidos (se abate suínos).",
       "agua_por_suino", (100, 3000), evid=("MED", "FAT"), obrig=False),
    _I("ag_frango", F, "Frigorífico", "Água por frango abatido", "L/frango", "Consumo total de água dividido pelas aves abatidas (se abate aves).",
       "agua_por_frango", (5, 100), evid=("MED", "FAT"), obrig=False),
    _I("gord_suino", F, "Frigorífico", "Gordura recuperada por carcaça de suíno", "kg/carcaça", "Massa de gordura e sebo gerada por carcaça.",
       "gordura_por_suino", (0.3, 10), evid=("MED",), obrig=False),
    _I("gord_frango", F, "Frigorífico", "Gordura recuperada por carcaça de frango", "kg/carcaça", "Massa de gordura gerada por carcaça de ave.",
       "gordura_por_frango", (0.005, 0.3), evid=("MED",), obrig=False),
    _I("gate", F, "Frigorífico", "Taxa de destinação paga hoje", "R$/t", "Valor pago por tonelada de resíduo orgânico descartado (nota fiscal ou contrato).",
       "gate_fee_ref", (0, 2000), evid=("FAT", "CON")),
    _I("res_t", F, "Frigorífico", "Resíduo orgânico disponível", "t/dia", "Massa de resíduo que poderia ir ao digestor.", None, (0.1, 5000), evid=("MED", "FAT")),
    # ------------------------------------------------------------------ usina / hub de biometano
    _I("hub_m3", U, "Usina de biometano", "Biometano contratado ou ofertado", "m³/dia", "Volume do contrato de venda de biometano.",
       "hub_contratado", (100, 60000), evid=("CON",)),
    _I("fc", U, "Usina de biometano", "Disponibilidade anual da usina", "%", "Horas produzindo no ano divididas pelas horas do ano.",
       "fator_capacidade", (50, 100), True, ("MED",)),
    _I("opex", U, "Usina de biometano", "O&M anual em relação ao investimento", "% do capex/ano", "Custo anual de operação e manutenção dividido pelo investimento.",
       "opex_frac", (1, 25), True, ("FAT", "CON")),
    _I("upg", U, "Usina de biometano", "Eletricidade da digestão e purificação", "kWh/m³", "Energia elétrica da planta por m³ de biometano.",
       "kwh_upgrading", (0.05, 1.0), evid=("MED",)),
    _I("dig", U, "Usina de biometano", "Preço do digestato (biofertilizante)", "R$/m³", "Receita por m³ vendido, ou 0 se não é vendido.",
       "preco_digestato", (0, 200), evid=("FAT", "CON")),
    _I("wacc", U, "Usina de biometano", "Custo de capital do projeto", "% ao ano", "Taxa do financiamento ou taxa mínima de atratividade usada.",
       "wacc", (2, 30), True, ("CON",)),
    _I("vida", U, "Usina de biometano", "Horizonte econômico do projeto", "anos", "Prazo de análise do projeto ou do financiamento.",
       "vida_util", (5, 40), evid=("CON",)),
    _I("aceite", U, "Usina de biometano", "Fração do resíduo aceita pelo digestor", "%", "Parcela que atende às especificações (contaminação e logística).",
       "aceite_biodigestor", (30, 100), True, ("MED", "LAU")),
    # ------------------------------------------------------------------ módulos (tinturaria)
    _I("m_vazao", T, "Módulo: recuperação de calor", "Vazão de efluente", "m³/dia", "Medidor de vazão na saída do processo.", None, (1, 20000), evid=("MED",), obrig=False, modulo="calor"),
    _I("m_tef", T, "Módulo: recuperação de calor", "Temperatura média do efluente", "°C", "Medida na saída, antes da ETE.", None, (20, 100), evid=("MED",), obrig=False, modulo="calor"),
    _I("m_tin", T, "Módulo: recuperação de calor", "Temperatura da água que entra", "°C", "Medida na captação.", None, (0, 45), evid=("MED",), obrig=False, modulo="calor"),
    _I("m_etroc", T, "Módulo: recuperação de calor", "Eficiência do trocador proposta", "%", "Folha de dados ou proposta do fornecedor.", None, (10, 95), True, ("CON", "LAU"), obrig=False, modulo="calor"),
    _I("m_ctroc", T, "Módulo: recuperação de calor", "Investimento no trocador", "R$", "Orçamento com instalação.", None, (0, 1e8), evid=("CON",), obrig=False, modulo="calor"),
    _I("m_kwdesl", T, "Módulo: programação por tarifa", "Carga deslocável na ponta", "kW", "Levantamento de cargas que podem sair do horário de ponta.", None, (0, 20000), evid=("MED",), obrig=False, modulo="tarifa"),
    _I("m_pini", T, "Módulo: programação por tarifa", "Início da ponta", "hora", "Conforme a distribuidora (fatura).", None, (0, 23), evid=("FAT", "PUB"), obrig=False, modulo="tarifa"),
    _I("m_pfim", T, "Módulo: programação por tarifa", "Fim da ponta", "hora", "Conforme a distribuidora (fatura).", None, (1, 24), evid=("FAT", "PUB"), obrig=False, modulo="tarifa"),
    _I("m_tp", T, "Módulo: programação por tarifa", "Tarifa de ponta", "R$/kWh", "Fatura de energia.", None, (0, 5), evid=("FAT",), obrig=False, modulo="tarifa"),
    _I("m_tfp", T, "Módulo: programação por tarifa", "Tarifa fora de ponta", "R$/kWh", "Fatura de energia.", None, (0, 5), evid=("FAT",), obrig=False, modulo="tarifa"),
    _I("m_ctar", T, "Módulo: programação por tarifa", "Investimento em automação", "R$", "Orçamento (0 se não houver).", None, (0, 1e8), evid=("CON",), obrig=False, modulo="tarifa"),
    _I("m_gprop", T, "Módulo: compra coletiva de gás", "Preço de gás proposto pela distribuidora para o grupo", "R$/m³", "Proposta formal da distribuidora.", None, (0.1, 10), evid=("CON",), obrig=False, modulo="coletiva"),
    _I("m_gvol", T, "Módulo: compra coletiva de gás", "Volume do grupo na proposta", "m³/dia", "Volume somado considerado na proposta.", None, (100, 500000), evid=("CON",), obrig=False, modulo="coletiva"),
    _I("m_lodo", T, "Módulo: lodo da ETE em biogás", "Lodo gerado", "t de matéria seca/dia", "Pesagem do lodo e teor de sólidos.", None, (0.01, 200), evid=("MED",), obrig=False, modulo="lodo"),
    _I("m_sv", T, "Módulo: lodo da ETE em biogás", "Sólidos voláteis do lodo", "%", "Laudo laboratorial (SV/ST).", None, (10, 95), True, ("LAU",), obrig=False, modulo="lodo"),
    _I("m_ch4", T, "Módulo: lodo da ETE em biogás", "Potencial de metano do lodo (ensaio BMP)", "m³ CH₄/kg SV", "Ensaio de potencial bioquímico de metano.", None, (0.01, 0.8), evid=("LAU",), obrig=False, modulo="lodo"),
    _I("m_cdig", T, "Módulo: lodo da ETE em biogás", "Consumo próprio do digestor", "%", "Folha de dados ou proposta (aquecimento e bombas).", None, (0, 80), True, ("CON", "MED"), obrig=False, modulo="lodo"),
    _I("m_clodo", T, "Módulo: lodo da ETE em biogás", "Investimento no digestor", "R$", "Orçamento com instalação.", None, (0, 2e8), evid=("CON",), obrig=False, modulo="lodo"),
    _I("m_irr", T, "Módulo: energia solar", "Irradiação média diária no local", "kWh/m²/dia", "Atlas Brasileiro de Energia Solar ou estação meteorológica (cite a fonte).", None, (2, 7), evid=("MED", "PUB"), obrig=False, modulo="solar"),
    _I("m_kwp", T, "Módulo: energia solar", "Potência fotovoltaica proposta", "kWp", "Projeto ou proposta do integrador.", None, (1, 50000), evid=("CON",), obrig=False, modulo="solar"),
    _I("m_pr", T, "Módulo: energia solar", "Desempenho global (PR) do projeto", "%", "Simulação do integrador (por exemplo PVsyst).", None, (50, 95), True, ("CON", "LAU"), obrig=False, modulo="solar"),
    _I("m_auto", T, "Módulo: energia solar", "Parte da geração consumida no local", "%", "Simulação com o perfil de carga.", None, (10, 100), True, ("CON", "LAU"), obrig=False, modulo="solar"),
    _I("m_cfv", T, "Módulo: energia solar", "Investimento fotovoltaico", "R$", "Orçamento completo.", None, (0, 2e8), evid=("CON",), obrig=False, modulo="solar"),
    _I("m_tar_e", T, "Módulo: energia solar", "Tarifa de energia evitada", "R$/kWh", "Fatura de energia (média ponderada).", None, (0.05, 3), evid=("FAT",), obrig=False, modulo="solar"),
    _I("m_area", T, "Módulo: energia solar", "Área de coletores solares térmicos", "m²", "Projeto ou proposta (opcional).", None, (1, 50000), evid=("CON",), obrig=False, modulo="solar_t"),
    _I("m_ecol", T, "Módulo: energia solar", "Eficiência média do coletor", "%", "Ensaio ou etiqueta do equipamento.", None, (10, 90), True, ("LAU", "CON"), obrig=False, modulo="solar_t"),
    _I("m_cst", T, "Módulo: energia solar", "Investimento em solar térmica", "R$", "Orçamento completo.", None, (0, 2e8), evid=("CON",), obrig=False, modulo="solar_t"),
    _I("m_perda", T, "Módulo: circularidade", "Perda de tecido (aparas e refugo)", "% da produção", "Pesagem de aparas e refugo dividida pela produção.", None, (0.1, 30), evid=("MED",), obrig=False, modulo="circular"),
    _I("m_rec", T, "Módulo: circularidade", "Parcela das perdas que é reciclável", "%", "Aparas limpas e separadas por fibra e cor (laudo ou comprador).", None, (0, 100), True, ("MED", "LAU", "CON"), obrig=False, modulo="circular"),
    _I("m_vapara", T, "Módulo: circularidade", "Preço de venda das aparas", "R$/t", "Cotação ou nota fiscal de venda.", None, (0, 20000), evid=("FAT", "CON"), obrig=False, modulo="circular"),
    _I("m_dest", T, "Módulo: circularidade", "Custo de destinação hoje", "R$/t", "Nota fiscal da destinação.", None, (0, 5000), evid=("FAT",), obrig=False, modulo="circular"),
    _I("m_subst", T, "Módulo: circularidade", "Substituição de fibra virgem pela reciclada", "%", "Ficha técnica do fio reciclado (equivalência).", None, (10, 100), True, ("LAU", "CON"), obrig=False, modulo="circular"),
    _I("m_efv", T, "Módulo: circularidade", "Emissão da fibra virgem", "kgCO₂e/kg", "Declaração ambiental do fornecedor (EPD).", None, (0.1, 50), evid=("CON", "PUB"), obrig=False, modulo="circular"),
    _I("m_efr", T, "Módulo: circularidade", "Emissão da fibra reciclada", "kgCO₂e/kg", "Declaração ambiental do fornecedor (EPD).", None, (0.1, 50), evid=("CON", "PUB"), obrig=False, modulo="circular"),
]
POR_ID = {i.id: i for i in ESQUEMA}
BLOCOS_ORDEM = ["Perfil e escala", "Consumo por tonelada", "Caldeira e combustível", "Preços", "Frigorífico", "Usina de biometano"]


def itens_do_tipo(tipo, com_modulos=True):
    return [i for i in ESQUEMA if tipo in i.tipos and (com_modulos or not i.modulo)]


def blocos_do_tipo(tipo, com_modulos=True):
    out = {}
    for i in itens_do_tipo(tipo, com_modulos):
        out.setdefault(i.bloco, []).append(i)
    return out


# ------------------------------------------------------------------------------------------------ validação e pacote
def validar_item(it: Item, reg: dict):
    """reg: {'valor','evidencia','periodo_dias','obs'}. Devolve lista de (nivel, texto)."""
    msgs = []
    x = reg.get("valor")
    if x is None:
        return msgs
    if not it.lim[0] <= x <= it.lim[1]:
        msgs.append(("aviso", f"{it.rotulo}: {x:g} {it.unidade} está fora do intervalo usual ({it.lim[0]:g} a {it.lim[1]:g}). "
                              "Confira a unidade e descreva o motivo em observações."))
    if reg.get("evidencia") not in EVID:
        msgs.append(("erro", f"{it.rotulo}: escolha de onde vem o dado."))
    elif reg["evidencia"] == "EST":
        msgs.append(("aviso", f"{it.rotulo}: estimativa não entra nas estatísticas publicadas. Prefira medição, fatura, laudo ou orçamento."))
    elif reg["evidencia"] not in it.evid:
        msgs.append(("aviso", f"{it.rotulo}: a evidência escolhida não é a usual para este item."))
    return msgs


def completude(tipo, itens: dict):
    """Fração dos itens obrigatórios com valor e evidência publicável, e lista do que falta."""
    obrig = [i for i in itens_do_tipo(tipo, com_modulos=False) if i.obrig]
    ok, falta = 0, []
    for i in obrig:
        r = itens.get(i.id)
        if r and r.get("valor") is not None and r.get("evidencia") in PUBLICAVEL:
            ok += 1
        else:
            falta.append(i)
    return (ok / len(obrig) if obrig else 1.0), falta


def _selo(p):
    q = {k: x for k, x in p.items() if k != "selo_sha256"}
    return hashlib.sha256(json.dumps(q, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def novo_pacote(tipo, itens: dict, consentimento: bool, publicar_dados: bool = False, regiao: str = ""):
    if not consentimento:
        raise ValueError("é necessário aceitar o termo de consentimento")
    limpo = {}
    for k, r in itens.items():
        if k in POR_ID and r.get("valor") is not None:
            limpo[k] = {"valor": float(r["valor"]), "unidade": POR_ID[k].unidade, "evidencia": r.get("evidencia", "EST"),
                        "periodo_dias": r.get("periodo_dias"), "lo": r.get("lo"), "hi": r.get("hi"), "obs": r.get("obs", "")}
    if not limpo:
        raise ValueError("nenhum valor informado")
    p = {"versao_esquema": VERSAO_ESQUEMA, "id_anonimo": secrets.token_hex(4), "tipo_empresa": tipo, "regiao": regiao,
         "criado_em": datetime.now().isoformat(timespec="seconds"),
         "consentimento": {"texto": CONSENTIMENTO_V1, "aceito": True, "publicar_dados_anonimizados": bool(publicar_dados)},
         "itens": limpo}
    p["selo_sha256"] = _selo(p)
    return p


def verificar_pacote(p):
    """Devolve (ok, mensagens)."""
    m = []
    if p.get("versao_esquema") != VERSAO_ESQUEMA:
        m.append("versão do esquema diferente")
    if p.get("selo_sha256") != _selo(p):
        m.append("selo de integridade inválido: o arquivo foi alterado")
    if not p.get("consentimento", {}).get("aceito"):
        m.append("sem consentimento")
    if p.get("tipo_empresa") not in TIPOS:
        m.append("tipo de empresa desconhecido")
    desconhecidos = [k for k in p.get("itens", {}) if k not in POR_ID]
    if desconhecidos:
        m.append("itens desconhecidos: " + ", ".join(desconhecidos))
    return (not m), m


# ------------------------------------------------------------------------------------------------ agregação
def agregar(pacotes, k_min=K_MIN):
    """Estatísticas por item, apenas com evidência publicável. Um pacote por id_anonimo (o mais recente)."""
    ult = {}
    for p in pacotes:
        if verificar_pacote(p)[0] and (p["id_anonimo"] not in ult or p["criado_em"] > ult[p["id_anonimo"]]["criado_em"]):
            ult[p["id_anonimo"]] = p
    agg = {}
    for it in ESQUEMA:
        vals, est = [], 0
        for p in ult.values():
            r = p["itens"].get(it.id)
            if not r:
                continue
            if r["evidencia"] in PUBLICAVEL:
                vals.append(r["valor"])
            else:
                est += 1
        if not vals and not est:
            continue
        a = {"id": it.id, "rotulo": it.rotulo, "unidade": it.unidade, "reg": it.reg, "n": len(vals), "n_estimativas": est,
             "publicavel": len(vals) >= k_min}
        if vals:
            x = np.array(vals)
            usa_perc = len(x) >= N_FAIXA_PERCENTIL
            a.update({"mediana": float(np.median(x)), "media": float(x.mean()),
                      "lo": float(np.percentile(x, 5) if usa_perc else x.min()),
                      "hi": float(np.percentile(x, 95) if usa_perc else x.max()),
                      "faixa": "P5-P95" if usa_perc else "mín-máx"})
        agg[it.id] = a
    return agg, ult


def painel_lacunas(agg, k_min=K_MIN):
    """Para cada parâmetro de registro ainda como hipótese (H) ou literatura (L): quantas empresas já mediram."""
    ids_por_reg = {}
    for it in ESQUEMA:
        if it.reg:
            ids_por_reg.setdefault(it.reg, []).append(it.id)
    linhas = []
    for d in fontes.D:
        if d.tipo in ("H", "L") and d.chave in ids_por_reg:
            n = max((agg.get(i, {}).get("n", 0) for i in ids_por_reg[d.chave]), default=0)
            linhas.append({"parametro": d.chave, "unidade": d.unidade, "valor_atual": d.valor, "origem_atual": d.tipo,
                           "fonte_atual": d.fonte, "empresas_com_medicao": n,
                           "situacao": "substituível" if n >= k_min else f"faltam {k_min - n} empresa(s)"})
    return linhas


def _escala(it, x):
    return x / 100.0 if it.pct else x


@contextmanager
def aplicar_agregado(agg, k_min=K_MIN):
    """Troca no registro as hipóteses pelos valores medidos (mediana e faixa) dos itens publicáveis."""
    orig, trocados = {}, []
    try:
        for a in agg.values():
            it = POR_ID[a["id"]]
            if not it.reg or not a["publicavel"]:
                continue
            val, lo, hi = (_escala(it, a[c]) for c in ("mediana", "lo", "hi"))
            lo, hi = min(lo, val), max(hi, val)
            chaves = [it.reg]
            if it.reg == "agua_textil_sc":            # a distribuição triangular da água usa três chaves
                if hi <= lo:
                    lo, hi = val * 0.99, val * 1.01
                chaves = ["agua_textil_br", "agua_textil_sc", "agua_textil_ue"]
                alvo = {"agua_textil_br": (lo, lo, lo), "agua_textil_sc": (val, lo, hi), "agua_textil_ue": (hi, hi, hi)}
            else:
                alvo = {it.reg: (val, lo, hi)}
            for c in chaves:
                orig.setdefault(c, fontes.IDX[c])
                vv, l, h = alvo[c]
                fontes.IDX[c] = dataclasses.replace(fontes.IDX[c], valor=vv, lo=l, hi=h, tipo="R",
                                                    fonte=f"Coleta multiempresa (n={a['n']})")
                trocados.append(c)
        yield sorted(set(trocados))
    finally:
        fontes.IDX.update(orig)


def reavaliar(agg, n=2000, k_min=K_MIN):
    """Roda os cenários e a economia do artigo antes e depois de trocar as hipóteses por dados medidos."""
    from .avaliacao import avaliar
    from .economia import avaliar_economia

    def rodar():
        av = avaliar(n)
        ec = avaliar_economia(n)
        out = {nome: {"sei": r["sei"]["media"], "co2_tex_kg_t": r["co2_tex_kg_t"]["media"], "agua_tex_m3_t": r["agua_tex_m3_t"]["media"]}
               for nome, r in av["cenarios"].items()}
        tg = ec["amostras"]["tarifa_gn"]
        out["economia"] = {"p_eq_sem_gate": float(np.mean(ec["p_equilibrio_sem_gate"])), "p_eq_com_gate": float(np.mean(ec["p_equilibrio_com_gate"])),
                           "prob_competitivo_sem_gate": float(np.mean(ec["p_equilibrio_sem_gate"] <= tg)),
                           "prob_competitivo_com_gate": float(np.mean(ec["p_equilibrio_com_gate"] <= tg))}
        return out
    antes = rodar()
    with aplicar_agregado(agg, k_min) as trocados:
        depois = rodar()
    return {"antes": antes, "depois": depois, "parametros_trocados": trocados}


# ------------------------------------------------------------------------------------------------ exportações
def tabela_parametros(agg):
    """Tabela para o artigo: parâmetro, valor anterior, mediana medida, faixa, n."""
    linhas = []
    for a in agg.values():
        it = POR_ID[a["id"]]
        ant = fontes.IDX.get(it.reg) if it.reg else None
        linhas.append({"item": a["rotulo"], "unidade": a["unidade"], "registro": it.reg or "", "origem_anterior": ant.tipo if ant else "",
                       "valor_anterior": ant.valor if ant else "", "n": a["n"], "mediana": a.get("mediana", ""),
                       "faixa": f"{a['lo']:.4g} a {a['hi']:.4g} ({a['faixa']})" if "lo" in a else "",
                       "publicavel": "sim" if a["publicavel"] else f"não (n<{K_MIN})"})
    return linhas


def tabela_latex(agg):
    esc = lambda s: str(s).replace("_", r"\_").replace("%", r"\%").replace("&", r"\&").replace("#", r"\#")
    L = [r"\begin{table}[t]", r"\caption{Parameters measured in the multi-company data collection (median and observed range).}",
         r"\begin{tabular}{@{}p{4.2cm}lrrl@{}}", r"\toprule", r"Parameter & Unit & $n$ & Median & Range \\ \midrule"]
    for r in tabela_parametros(agg):
        if r["publicavel"] == "sim":
            L.append(f"{esc(r['item'])} & {esc(r['unidade'])} & {r['n']} & {r['mediana']:.4g} & {esc(r['faixa'])} \\\\")
    L += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    return "\n".join(L)


def dataset_anonimizado(ult):
    """Linhas (id_anonimo, tipo, item, valor, unidade, evidência, período) dos pacotes que autorizaram a publicação dos dados."""
    linhas = []
    for p in ult.values():
        if not p["consentimento"].get("publicar_dados_anonimizados"):
            continue
        for k, r in p["itens"].items():
            if r["evidencia"] in PUBLICAVEL:
                linhas.append({"id_anonimo": p["id_anonimo"], "tipo_empresa": p["tipo_empresa"], "item": k, "valor": r["valor"],
                               "unidade": r["unidade"], "evidencia": r["evidencia"], "periodo_dias": r.get("periodo_dias")})
    return linhas


# ------------------------------------------------------------------------------------------------ módulos só com dados medidos
MODULOS_REQ = {
    "Recuperação de calor do efluente": ("calor", ["m_vazao", "m_tef", "m_tin", "m_etroc", "m_ctroc", "tar_gn", "ef_gas", "dias_op"]),
    "Programação da produção por tarifa": ("tarifa", ["m_kwdesl", "m_pini", "m_pfim", "m_tp", "m_tfp", "m_ctar", "dias_op", "eletr", "t_dia"]),
    "Compra coletiva de gás": ("coletiva", ["tar_gn", "m_gprop", "m_gvol", "gn", "t_dia", "dias_op"]),
    "Lodo da ETE em biogás": ("lodo", ["m_lodo", "m_sv", "m_ch4", "m_cdig", "m_clodo", "tar_gn", "dias_op", "gn", "t_dia"]),
    "Solar fotovoltaica": ("solar", ["m_irr", "m_kwp", "m_pr", "m_auto", "m_cfv", "m_tar_e"]),
    "Solar térmica": ("solar_t", ["m_irr", "m_area", "m_ecol", "m_cst", "tar_gn", "ef_gas", "dias_op"]),
    "Circularidade têxtil": ("circular", ["t_dia", "dias_op", "m_perda", "m_rec", "m_vapara", "m_dest", "m_subst", "m_efv", "m_efr"]),
}


def valores_publicaveis(itens):
    return {k: r["valor"] for k, r in itens.items() if r.get("valor") is not None and r.get("evidencia") in PUBLICAVEL}


def modulos_com_dados(itens):
    """Calcula cada módulo somente se todos os dados necessários foram informados com evidência publicável. Nada é preenchido por hipótese."""
    from . import modulos as M
    x = valores_publicaveis(itens)
    out = {}
    for nome, (cod, req) in MODULOS_REQ.items():
        falta = [POR_ID[i].rotulo for i in req if i not in x]
        if cod == "calor" and "tar_gn" in x and x["tar_gn"] <= 0:
            falta.append("Preço do gás natural pago (maior que zero)")
        if falta:
            out[nome] = {"ok": False, "faltam": falta}
            continue
        d = x["dias_op"] if "dias_op" in x else 0
        if cod == "calor":
            r = M.recuperacao_calor(x["m_vazao"], x["m_tef"], x["m_tin"], x["m_etroc"] / 100, d, x["tar_gn"], x["m_ctroc"],
                                    eficiencia_caldeira=x["ef_gas"] / 100)
        elif cod == "tarifa":
            kwh = x["m_kwdesl"] * max(0.0, x["m_pfim"] - x["m_pini"]) * d
            r = M.programacao_tarifa(kwh, x["eletr"] * x["t_dia"] * d, 1.0, x["m_tp"], x["m_tfp"], x["m_ctar"])
        elif cod == "coletiva":
            r = M.compra_coletiva_proposta(x["gn"] * x["t_dia"], x["tar_gn"], x["m_gprop"], d)
        elif cod == "lodo":
            r = M.biogas_lodo(x["m_lodo"], x["m_sv"] / 100, x["m_ch4"], x["m_cdig"] / 100, d, x["tar_gn"],
                              x["gn"] * x["t_dia"] * d, x["m_clodo"])
        elif cod == "solar":
            r = M.fotovoltaica(x["m_kwp"], x["m_irr"], x["m_pr"] / 100, x["m_auto"] / 100, x["m_tar_e"], x["m_cfv"] / x["m_kwp"])
        elif cod == "solar_t":
            r = M.solar_termica(x["m_area"], x["m_irr"], x["m_ecol"] / 100, d, x["tar_gn"], x["m_cst"] / x["m_area"],
                                eficiencia_caldeira=x["ef_gas"] / 100)
        else:
            r = M.circularidade(x["t_dia"] * d, x["m_perda"], x["m_rec"], x["m_vapara"], x["m_dest"], x["m_subst"] / 100,
                                x["m_efv"], x["m_efr"])
        # premissas: só físicas/referência do código + os dados da empresa com a evidência de cada um
        fixas = [p for p in r["premissas"] if p["Origem"] in ("Física", "Referência pública", "Literatura")]
        proprias = [{"Premissa": POR_ID[i].rotulo, "Valor": x[i], "Unidade": POR_ID[i].unidade,
                     "Origem": EVID[itens[i]["evidencia"]]} for i in req if i in x]
        r["premissas"] = fixas + proprias
        r.pop("nota", None) if cod in ("calor", "solar", "solar_t") else None
        out[nome] = {"ok": True, "resultado": r}
    return out
