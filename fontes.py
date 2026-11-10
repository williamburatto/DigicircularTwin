"""Registro de proveniência dos dados de calibração (dados públicos de SC/Brasil).

Cada parâmetro tem: valor, unidade, faixa de incerteza (para Monte Carlo), fonte,
ano de referência e TIPO:
  R = dado real público de SC ou do SIN (aplicável a SC)
  L = proxy de literatura (estudo de caso, outra região ou internacional)
  H = hipótese de modelagem (a substituir por dado de licença/planta)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dado:
    chave: str
    valor: float
    unidade: str
    lo: float
    hi: float
    tipo: str          # R | L | H
    fonte: str
    ano: str
    ref: str           # chave bibliográfica do artigo


D = [
    # ---------------- Energia / rede (substitui o BEN-SC, sem edição atual publicada)
    Dado("ef_sin_2023", 38.5, "kgCO2/MWh", 38.5, 38.5, "R", "MCTI - fator médio anual do SIN", "2023", "mcti2024"),
    Dado("ef_sin_2025_min", 21.5, "kgCO2/MWh", 21.5, 21.5, "R", "MCTI/SIRENE - fator médio mensal mar/2025", "2025", "mcti2025"),
    Dado("ef_sin_2025_max", 28.9, "kgCO2/MWh", 28.9, 28.9, "R", "MCTI/SIRENE - fator médio mensal abr/2025", "2025", "mcti2025"),
    Dado("ef_sin_2022", 61.7, "kgCO2/MWh", 61.7, 61.7, "R", "MCTI - fator médio anual do SIN", "2022", "canalsolar2024"),
    Dado("celesc_consumo_2024", 22282, "GWh/ano", 22282, 22282, "R", "Celesc Distribuição - energia faturada 2024", "2024", "celesc2025"),
    Dado("industria_share_eletr_sc", 0.45, "-", 0.42, 0.45, "R", "FIESC - participação da indústria no consumo elétrico de SC", "2015", "fiesc_manual"),
    Dado("scgas_vol_2024", 1.6e6, "m3/dia", 1.6e6, 1.6e6, "R", "SCGÁS - consumo médio do mercado local", "2024", "eixos2024"),
    Dado("scgas_recorde_2021", 2.273313e6, "m3/dia", 2.273313e6, 2.273313e6, "R", "SCGÁS - média diária ago/2021 (recorde)", "2021", "tbpetroleum2021"),
    Dado("pci_gn", 8800, "kcal/m3", 8800, 8800, "R", "BEN/EPE - PCI do gás natural", "-", "epe_ben"),
    Dado("ef_gn_tj", 56.1, "tCO2/TJ", 56.1, 56.1, "R", "IPCC 2006 - fator padrão gás natural", "2006", "ipcc2006"),
    # ---------------- Resíduos (IMA/MTR, SINIR/SEMAE, ABIPET)
    Dado("mtr_geracao_min", 7.765e6, "t/ano", 7.765e6, 7.765e6, "R", "IMA - Boletim anual MTR (2021-2023)", "2021-23", "ima2023"),
    Dado("mtr_geracao_max", 9.681e6, "t/ano", 9.681e6, 9.681e6, "R", "IMA - Boletim anual MTR (2021-2023)", "2021-23", "ima2023"),
    Dado("mtr_geradores", 91930, "cadastros", 91930, 91930, "R", "IMA - Boletim anual MTR 2023", "2023", "ima2023"),
    Dado("rsu_sc", 2050579, "t/ano", 2050579, 2050579, "R", "SEMAE/SC (via SNIS) - RSU coletado", "2024", "alesc2024"),
    Dado("coleta_seletiva_sc", 140868, "t/ano", 140868, 140868, "R", "SEMAE/SC (via SNIS) - coleta seletiva", "2024", "alesc2024"),
    Dado("pet_reciclado_br", 410e3, "t/ano", 410e3, 410e3, "R", "ABIPET - 13º Censo da Reciclagem do PET", "2024", "abipet2025"),
    Dado("pet_reciclado_textil_share", 0.24, "-", 0.24, 0.24, "R", "ABIPET - destino têxtil da resina reciclada", "2024", "abipet2025"),
    # ---------------- Agroindústria do Oeste
    Dado("abate_suinos_sc", 16.6e6, "cabeças/ano", 16.6e6, 16.6e6, "R", "IBGE - Estatística da Produção Pecuária", "2024", "ibge2025"),
    Dado("abate_frangos_sc", 886.7e6, "cabeças/ano", 886.7e6, 886.7e6, "R", "Cidasc / Epagri-Cepa - Síntese Anual", "2024", "epagri2025"),
    Dado("planta_ref_suinos_dia", 2600, "suínos/dia", 2600, 2600, "R", "Frigorífico de referência em Chapecó (GEF Biogás)", "2021", "agrolink_gef"),
    Dado("agua_por_suino", 850, "L/suíno", 765, 935, "L", "Embrapa Suínos e Aves (Brasil, 1995)", "1995", "embrapa_flotado"),
    Dado("agua_por_frango", 30, "L/frango", 27, 33, "L", "Embrapa Suínos e Aves (Brasil, 1999)", "1999", "embrapa_flotado"),
    Dado("gordura_por_suino", 3.3, "kg/carcaça", 2.74, 3.86, "L", "Estudo de caso frigorífico (RS), média ± 2 dp", "2011", "ufpel2011"),
    Dado("gordura_por_frango", 0.0459, "kg/carcaça", 0.0359, 0.0559, "L", "Estudo de caso frigorífico (RS), média ± 2 dp", "2011", "ufpel2011"),
    Dado("biometano_por_t", 25000 / 350, "m3/t", 0.85 * 25000 / 350, 1.15 * 25000 / 350, "R",
         "Planta AGRIC (Embrapa/(re)energisa): 25.000 m3/d de 350 t/d", "2024", "agric2024"),
    # ---------------- Têxtil do Vale do Itajaí
    # --- v0.3: dados reais de SC extraídos de trabalhos do repositório UFSC (Appel 2019, Falani 2022, Twardokus 2004, Justo 2021)
    Dado("agua_textil_br", 80, "m3/t", 80, 80, "L", "UFSC - ~80 L de água por kg de tecido (limite inferior)", "2010", "curi2010"),
    Dado("agua_textil_sc", 170, "m3/t", 170, 170, "L", "UFSC (Twardokus) - relação água/material têxtil de 170 L/kg, empresa de grande porte de SC", "2004", "twardokus2004"),
    Dado("agua_textil_ue", 230, "m3/t", 230, 230, "L", "Beneficiamento (tinturaria) - estudo de caso", "2021", "ferreira2021"),
    Dado("eletr_textil", 808, "kWh/t", 727, 889, "R", "UFSC (Appel) - tinturaria/acabamento do Vale do Itajaí: 11,9 GWh/ano para 14.733 t de tecido (faixa +-10 % = H)", "2019", "appel2019"),
    Dado("eletr_textil_proxy", 1991, "kWh/t", 1792, 2190, "L", "Beneficiamento (tinturaria) - estudo de caso (valor do v0.2, usado só em sensibilidade)", "2021", "ferreira2021"),
    Dado("gn_textil", 1143, "Nm3/t", 1029, 1257, "L", "Tinturaria a gás - estudo de caso (a planta de Appel usa cavaco; GN segue como proxy)", "2021", "ferreira2021"),
    Dado("cavaco_textil", 51.7, "kg/t", 51.7, 51.7, "R", "UFSC (Appel) - 762 t/ano de cavaco nas caldeiras / 14.733 t de tecido (vapor não contabilizado pela planta)", "2019", "appel2019"),
    Dado("perda_massa_malha", 0.07, "-", 0.07, 0.07, "R", "UFSC (Appel) - perda de massa na malha de algodão (11 % para o conjunto)", "2019", "appel2019"),
    Dado("residuo_textil_vendido", 0.084, "-", 0.084, 0.084, "R", "UFSC (Appel) - 1.243 t de resíduo têxtil/ano vendido / 14.733 t processadas (204 t não recicladas)", "2019", "appel2019"),
    Dado("prealv_temp", 96, "C", 95, 98, "R", "UFSC (Falani) - pré-alvejamento de 4 empresas de SC: temperatura média (95-98 C)", "2022", "falani2022"),
    Dado("prealv_tempo", 61, "min", 20, 90, "R", "UFSC (Falani) - pré-alvejamento de 4 empresas de SC: tempo médio (20-90 min)", "2022", "falani2022"),
    Dado("prealv_enz_dT", -10, "C", -10, -10, "R", "UFSC (Falani) - pré-alvejamento enzimático em banho único: 95 -> 85 C, 3 volumes de água -> 1, -25 % de H2O2/NaOH (escala de laboratório)", "2022", "falani2022"),
    Dado("tinturaria_pequena_t_mes", 60, "t/mes", 60, 60, "R", "UFSC (Justo) - tinturaria do Vale do Itajaí: capacidade de 60 t/mês", "2021", "justo2021"),
    Dado("tinturaria_grande_t_ano", 14733, "t/ano", 14733, 14733, "R", "UFSC (Appel) - tinturaria do Vale do Itajaí: entrada de tecido (~40 t/dia)", "2019", "appel2019"),
    Dado("reuso_agua_max", 0.40, "-", 0.40, 0.40, "L", "Reúso típico em lavanderias têxteis", "2014", "cbens2014"),
    Dado("ef_pes_virgem", 4.36, "kgCO2e/kg", 3.96, 4.76, "L", "Textile Exchange/SCS - fibra de poliéster virgem", "2026", "te2026"),
    Dado("ef_pes_rpet", 3.04, "kgCO2e/kg", 2.74, 3.34, "L", "Textile Exchange/SCS - fibra rPET termomecânica", "2026", "te2026"),
    # ---------------- Aterro (IPCC defaults) e limites de licença (CONAMA 430/2011)
    Dado("aterro_tco2e_t", 1.26, "tCO2e/t", 0.88, 1.64, "L",
         "IPCC 2006 Vol.5 (DOC 0,15; DOCf 0,5; MCF 1; F 0,5; OX 0,1) × GWP100 CH4=28", "2006", "ipcc2006"),
    Dado("lim_temp_efluente", 40.0, "°C", 40, 40, "R", "CONAMA 430/2011 art. 16", "2011", "conama430"),
    Dado("lim_og_animal", 50.0, "mg/L", 50, 50, "R", "CONAMA 430/2011 art. 16 (óleos e graxas animais/vegetais)", "2011", "conama430"),
    Dado("lim_ph_min", 5.0, "-", 5, 5, "R", "CONAMA 430/2011 art. 16", "2011", "conama430"),
    Dado("lim_ph_max", 9.0, "-", 9, 9, "R", "CONAMA 430/2011 art. 16", "2011", "conama430"),
    # ---------------- Economia: tarifas reguladas e custos (camada econômica)
    Dado("celesc_a4v_ponta", 1.55304, "R$/kWh", 1.55304, 1.55304, "R", "Celesc A4 Verde, ponta, sem tributos (ANEEL REH 3.511/2025)", "2025", "celesc_tarifas"),
    Dado("celesc_a4v_fponta", 0.44558, "R$/kWh", 0.44558, 0.44558, "R", "Celesc A4 Verde, fora de ponta, sem tributos (ANEEL REH 3.511/2025)", "2025", "celesc_tarifas"),
    Dado("celesc_a4v_demanda", 18.09, "R$/kW", 18.09, 18.09, "R", "Celesc A4 Verde, demanda (ANEEL REH 3.511/2025)", "2025", "celesc_tarifas"),
    Dado("aresc_pv_gas", 2.3021, "R$/m3", 2.3021, 2.3021, "R", "ARESC Res. 287/2024: preço do gás + transporte + recuperação", "2024", "aresc287"),
    Dado("scgas_comercial_c_trib", 4.2962, "R$/m3", 4.2962, 4.2962, "R", "SCGÁS: tarifa comercial >2.100 m3/mês c/ tributos (vigência 01/07/2026)", "2026", "scgas_tarifas"),
    Dado("tarifa_gn_ind_v02", 3.00, "R$/m3", 2.80, 3.17, "H",
         "Hipótese do v0.2: tarifa industrial TG1 s/ tributos entre PV ARESC + margem e a tarifa comercial s/ tributos (usada só em sensibilidade)", "2026", "-"),
    # v0.3: preço de paridade do biometano com o gás de rede (substitui a hipótese de tarifa industrial)
    Dado("tarifa_gn_ind", 2.61, "R$/m3", 2.43, 2.79, "R",
         "Argus - preço de paridade do biometano com o gás natural (SP e RJ, 23/02/2024): R$ 2,43-2,79/m3, ponto médio como moda", "2024", "argus2024"),
    Dado("argus_fob_planta_2026", 3.28, "R$/m3", 3.28, 3.28, "R", "Argus - preço do biometano fob planta em 01/01/2026 (só sensibilidade)", "2026", "argus2026"),
    # Preços de cavaco anunciados em SC (MF Rural; preços de oferta, não de transação)
    Dado("cavaco_imbituba", 100, "R$/t", 100, 100, "R", "MF Rural - Imbituba: cavaco de eucalipto/pinus", "2026", "mfrural"),
    Dado("cavaco_sao_miguel_oeste", 250, "R$/t", 250, 250, "R", "MF Rural - São Miguel do Oeste: cavaco de eucalipto/pinus para biomassa", "2026", "mfrural"),
    Dado("cavaco_mafra", 400, "R$/t", 400, 400, "R", "MF Rural - Mafra: cavaco de madeira para energia ou indústria", "2026", "mfrural"),
    Dado("cavaco_porto_belo", 200, "R$/m3", 200, 200, "R", "MF Rural - Porto Belo: pedido mínimo de 35 m3", "2026", "mfrural"),
    Dado("cavaco_joinville", 45, "R$/m3", 45, 45, "R", "MF Rural - Joinville: cavaco para caldeira", "2026", "mfrural"),
    Dado("cavaco_garuva", 70, "R$/m3", 70, 70, "R", "MF Rural - Garuva: cavaco de eucalipto/pinus personalizado", "2026", "mfrural"),
    Dado("cavaco_palhoca", 40, "R$/m3", 40, 40, "R", "MF Rural - Palhoça: cavaco para construção civil (não energético; fora da análise)", "2026", "mfrural"),
    Dado("cavaco_pci", 3.0, "MWh/t", 2.5, 3.5, "H", "Hipótese: poder calorífico inferior do cavaco com 30-40 % de umidade", "-", "-"),
    Dado("cavaco_densidade", 300, "kg/m3", 250, 350, "H", "Hipótese: densidade a granel do cavaco úmido", "-", "-"),
    Dado("eficiencia_caldeira_cavaco", 0.80, "-", 0.75, 0.85, "H", "Hipótese: eficiência de caldeira a cavaco", "-", "-"),
    Dado("eficiencia_caldeira_gas", 0.90, "-", 0.88, 0.92, "H", "Hipótese: eficiência de caldeira a gás", "-", "-"),
    Dado("capex_hub_min", 80e6, "R$", 80e6, 80e6, "R", "AGRIC/(re)energisa: R$ 80 mi para 25.000 m3/d", "2024", "nsc_agric"),
    Dado("capex_hub_max", 150e6, "R$", 150e6, 150e6, "R", "Cocal: R$ 150 mi para planta de 25.000 m3/d", "2022", "cocal2022"),
    Dado("hub_capacidade", 25000, "m3/dia", 25000, 25000, "R", "AGRIC: capacidade de projeto", "2024", "nsc_agric"),
    Dado("hub_residuos", 350, "t/dia", 350, 350, "R", "AGRIC: resíduos tratados", "2024", "nsc_agric"),
    Dado("hub_digestato", 3500, "m3/mês", 3500, 3500, "R", "AGRIC: biofertilizante", "2024", "nsc_agric"),
    Dado("teto_bio_arsal", 2.9454, "R$/m3", 2.9454, 2.9454, "R", "ARSAL Res. 185/2024: preço-teto do biometano (AL, 2025)", "2024", "arsal185"),
    Dado("gate_fee_ref", 144.92, "R$/t", 100, 145, "L", "Edital municipal (RS): valor de referência de destinação por tonelada", "2026", "cacapava2026"),
    Dado("opex_frac", 0.08, "1/ano", 0.06, 0.10, "H", "Hipótese: O&M anual como fração do CAPEX", "-", "-"),
    Dado("kwh_upgrading", 0.30, "kWh/m3", 0.25, 0.35, "H", "Hipótese: eletricidade de digestão + purificação", "-", "-"),
    Dado("fator_capacidade", 0.90, "-", 0.85, 0.95, "H", "Hipótese: disponibilidade anual do hub", "-", "-"),
    Dado("preco_digestato", 20, "R$/m3", 0, 40, "H", "Hipótese: preço do biofertilizante", "-", "-"),
    Dado("wacc", 0.10, "1/ano", 0.08, 0.12, "H", "Hipótese: custo de capital real (sensibilidade 5 %, deck DT2)", "-", "-"),
    Dado("vida_util", 15, "anos", 15, 15, "H", "Hipótese: horizonte econômico do hub", "-", "-"),
    # ---------------- Hipóteses (calibrar com licença/planta)
    Dado("dias_operacao", 300, "dias/ano", 290, 310, "H", "Hipótese: 6 dias/semana", "-", "-"),
    Dado("textil_t_dia", 10, "t/dia", 2, 40.4, "H", "Hipótese: porte intermediário entre duas tinturarias reais do Vale do Itajaí (2 t/dia, Justo; 40 t/dia, Appel)", "-", "-"),
    Dado("share_poliester", 0.30, "-", 0.25, 0.35, "H", "Hipótese: fração de poliéster no mix de fibras", "-", "-"),
    Dado("rpet_base", 0.10, "-", 0.10, 0.10, "H", "Hipótese: teor reciclado atual", "-", "-"),
    Dado("rpet_max", 0.50, "-", 0.50, 0.50, "H", "Hipótese: teto de qualidade do fio", "-", "-"),
    Dado("aceite_biodigestor", 0.85, "-", 0.80, 0.90, "H", "Hipótese: fração aceita (contaminação/logística)", "-", "-"),
    Dado("fracao_termica_agua", 0.55, "-", 0.45, 0.65, "H", "Hipótese: fração do calor que aquece água de processo", "-", "-"),
    Dado("hub_contratado", 3000, "m3/dia", 3000, 3000, "H", "Hipótese: contrato da tinturaria com hub regional de biometano", "-", "-"),
]

# Destinação de resíduos industriais em SC (IMA/MTR): três conjuntos anuais 2021-2023
# (o boletim não associa inequivocamente cada conjunto a um ano; usados como cenários).
DESTINACAO_MTR = [
    {"reciclagem": .529, "rec_energetica": .181, "aterro": .128, "efluentes": .071, "outro": .061, "coprocess": .030},
    {"reciclagem": .394, "rec_energetica": .245, "aterro": .156, "efluentes": .091, "outro": .072, "coprocess": .043},
    {"reciclagem": .413, "rec_energetica": .260, "aterro": .134, "efluentes": .082, "outro": .064, "coprocess": .047},
]

IDX = {d.chave: d for d in D}


def v(chave):
    return IDX[chave].valor


def tabela_latex(caminho):
    """Gera a tabela de proveniência para o artigo."""
    linhas = []
    sel = ["ef_sin_2023", "ef_sin_2025_min", "ef_sin_2025_max", "celesc_consumo_2024", "scgas_vol_2024",
           "mtr_geracao_min", "mtr_geracao_max", "coleta_seletiva_sc", "pet_reciclado_br",
           "abate_suinos_sc", "abate_frangos_sc", "planta_ref_suinos_dia", "agua_por_suino",
           "gordura_por_suino", "biometano_por_t", "agua_textil_sc", "eletr_textil", "gn_textil",
           "ef_pes_virgem", "ef_pes_rpet", "aterro_tco2e_t", "lim_temp_efluente", "lim_og_animal",
           "celesc_a4v_ponta", "celesc_a4v_fponta", "aresc_pv_gas", "scgas_comercial_c_trib", "capex_hub_min",
           "capex_hub_max", "teto_bio_arsal", "gate_fee_ref"]
    nomes_en = {
        "ef_sin_2023": "Grid emission factor (SIN, annual)", "ef_sin_2025_min": "Grid factor, monthly min.",
        "ef_sin_2025_max": "Grid factor, monthly max.", "celesc_consumo_2024": "Celesc billed electricity",
        "scgas_vol_2024": "SCG\\'AS natural-gas sales", "mtr_geracao_min": "Industrial waste (MTR), min.",
        "mtr_geracao_max": "Industrial waste (MTR), max.", "coleta_seletiva_sc": "Selective collection (SC)",
        "pet_reciclado_br": "Post-consumer PET recycled (BR)", "abate_suinos_sc": "Pig slaughter (SC)",
        "abate_frangos_sc": "Broiler slaughter (SC)", "planta_ref_suinos_dia": "Reference plant, Chapec\\'o",
        "agua_por_suino": "Water per pig slaughtered", "gordura_por_suino": "Residual fat per pig",
        "biometano_por_t": "Biomethane yield (AGRIC)", "agua_textil_sc": "Textile water (SC)",
        "eletr_textil": "Dyehouse electricity", "gn_textil": "Dyehouse natural gas",
        "ef_pes_virgem": "Virgin polyester fibre", "ef_pes_rpet": "rPET staple fibre",
        "aterro_tco2e_t": "Landfilled organic residue", "lim_temp_efluente": "Effluent temperature limit",
        "lim_og_animal": "Oils \\& greases limit",
        "celesc_a4v_ponta": "Celesc A4 Green, peak", "celesc_a4v_fponta": "Celesc A4 Green, off-peak",
        "aresc_pv_gas": "SCG\\'AS gas + transport (ARESC)", "scgas_comercial_c_trib": "SCG\\'AS commercial tariff (taxed)",
        "capex_hub_min": "Hub CAPEX, AGRIC (25k m$^3$/d)", "capex_hub_max": "Hub CAPEX, Cocal (25k m$^3$/d)",
        "teto_bio_arsal": "Biomethane price cap (ARSAL, AL)", "gate_fee_ref": "Waste destination fee (proxy)",
    }
    for k in sel:
        d = IDX[k]
        val = (f"{d.valor/1e6:,.0f}\\,M" if d.valor >= 1e7 and d.unidade == "R$" else
               f"{d.valor:,.0f}" if d.valor >= 1000 else f"{d.valor:.5g}")
        un = d.unidade
        for a, b in (("cabeças/ano", "head/yr"), ("suínos/dia", "pigs/day"), ("L/suíno", "L/pig"),
                     ("kg/carcaça", "kg/carcass"), ("/ano", "/yr"), ("/dia", "/day"), ("CO2", "CO$_2$"),
                     ("m3", "m$^3$"), ("°", "\\textdegree "), ("R$", "R\\$")):
            un = un.replace(a, b)
        linhas.append(f"{nomes_en[k]} & {val} & {un} & {d.tipo} & {d.ano} & \\cite{{{d.ref}}}\\\\")
    from pathlib import Path
    Path(caminho).write_text("\n".join(linhas), encoding="utf-8")
