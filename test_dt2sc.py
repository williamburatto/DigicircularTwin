import numpy as np

from dt2sc.avaliacao import avaliar
from dt2sc.federacao import EF_GN_KG_M3, KWH_POR_M3_GN, Politica, amostrar, calibrar_maximos, simular
from dt2sc.fontes import D, DESTINACAO_MTR
from dt2sc.telemetria import alarmes, gerar, verificar_calibracao


def test_constantes_fisicas():
    assert 10.0 < KWH_POR_M3_GN < 10.5          # 8.800 kcal/m3
    assert 2.0 < EF_GN_KG_M3 < 2.1              # 56,1 tCO2/TJ


def test_proveniencia_completa():
    assert all(d.tipo in "RLH" for d in D)
    assert all(d.lo <= d.valor <= d.hi for d in D)
    for s in DESTINACAO_MTR:
        assert abs(sum(s.values()) - 1) < 0.02


def test_baseline_reproduz_intensidades_publicas():
    p = amostrar(500)
    b = simular(Politica("b"), p)
    assert abs(np.mean(b["agua_agro_l_suino"]) - 850) / 850 < 0.03
    energia_esperada = 808 + 1143 * KWH_POR_M3_GN
    assert abs(np.mean(b["energia_kwh_t"]) - energia_esperada) / energia_esperada < 0.03


def test_dt2_reduz_co2_e_aumenta_sei():
    av = avaliar(n=500)
    c = av["cenarios"]
    nomes = list(c)
    assert c[nomes[3]]["co2_tex_kg_t"]["media"] < c[nomes[0]]["co2_tex_kg_t"]["media"]
    assert c[nomes[2]]["sei"]["media"] > c[nomes[0]]["sei"]["media"]


def test_telemetria_calibrada():
    t, s = gerar(14)
    cal = verificar_calibracao(s)
    assert abs(cal["eletr_kwh_t"] - 808) / 808 < 0.15
    assert abs(cal["agua_l_suino"] - 850) / 850 < 0.15
    assert isinstance(alarmes(s), dict)


def test_economia_tarifas_e_equilibrio():
    from dt2sc.economia import avaliar_economia, tarifa_eletrica_media
    assert 0.44 < tarifa_eletrica_media() < 0.60          # Celesc A4 Verde (REH 3.511/2025)
    ec = avaliar_economia(2000)
    assert np.mean(ec["p_equilibrio_com_gate"]) < np.mean(ec["p_equilibrio_sem_gate"])


def test_negociacao_espaco_de_dados_e_humano():
    from dt2sc.negociacao import Conector, resumir, simular_negociacao
    iso = resumir(simular_negociacao("isolado", 800, humano=False))
    esp = resumir(simular_negociacao("espaco", 800, humano=False))
    hum = resumir(simular_negociacao("espaco", 800, humano=True))
    assert esp["volume_medio"] > iso["volume_medio"]
    assert esp["co2_evitado_t_ano"] > iso["co2_evitado_t_ano"]
    assert hum["escalados"] > 0 and hum["dias"] > esp["dias"]
    c = Conector("frigorifico")
    assert c.consultar("previsao_residuos", "usina", "negociacao_DT2", "espaco")
    assert not c.consultar("previsao_residuos", "tinturaria", "negociacao_DT2", "espaco")
    assert not c.consultar("previsao_residuos", "usina", "marketing", "espaco")
    assert not c.consultar("previsao_residuos", "usina", "negociacao_DT2", "isolado")


# ---------------------------------------------------------------- modo planta
def test_planta_recupera_intensidades(tmp_path):
    from dt2sc import planta as P
    df0 = P.exemplo_csv(tmp_path / "p.csv", 10)
    df = P.carregar(tmp_path / "p.csv")
    k = P.kpis(df)
    assert 700 < k["eletr_kwh_t"] < 1000 and 900 < k["gn_m3_t"] < 1400


def test_planta_unidades_e_mapa(tmp_path):
    from dt2sc import planta as P
    P.exemplo_csv(tmp_path / "p.csv", 5)
    import pandas as pd
    b = pd.read_csv(tmp_path / "p.csv").rename(columns={"eletrica_kw": "P_W", "producao_kg_h": "kg"})
    b["P_W"] *= 1000
    k = P.kpis(P.carregar(b, {"timestamp": "timestamp", "producao_kg_h": "kg", "eletrica_kw": "P_W"},
                          {"eletrica_kw": 0.001}))
    assert 700 < k["eletr_kwh_t"] < 1000


def test_planta_coluna_obrigatoria():
    import pytest, pandas as pd
    from dt2sc import planta as P
    with pytest.raises(ValueError):
        P.carregar(pd.DataFrame({"timestamp": ["2026-01-01"], "x": [1]}))


def test_planta_calibracao_restaura_registro(tmp_path):
    from dt2sc import planta as P, fontes
    P.exemplo_csv(tmp_path / "p.csv", 8)
    cal = P.calibrar(P.carregar(tmp_path / "p.csv"))
    antes = fontes.IDX["eletr_textil"].valor
    with P.aplicar(cal):
        assert fontes.IDX["eletr_textil"].valor != antes
    assert fontes.IDX["eletr_textil"].valor == antes


def test_planta_a_cavaco_sem_cenarios_biometano(tmp_path):
    from dt2sc import planta as P
    import pandas as pd
    P.exemplo_csv(tmp_path / "p.csv", 8)
    b = pd.read_csv(tmp_path / "p.csv"); b["cavaco_kg_h"] = b["gn_m3_h"] * 0.4; b["gn_m3_h"] = 0.0
    cal = P.calibrar(P.carregar(b))
    res = P.avaliar_planta(cal, n=300, preco_cavaco_r_t=250)
    assert cal["kpis"]["combustivel"] == "cavaco" and len(res["cenarios"]) == 3 and "cavaco_r_m3eq" in res["economia"]
