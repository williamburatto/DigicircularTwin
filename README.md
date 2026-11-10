# Gêmeo digital federado DigiCircular calibrado com dados públicos de Santa Catarina

Telemetria real de chão de fábrica (OPC UA/MQTT) é sigilosa. O DT2-SC calibra baselines e limites com
**dados públicos** (MCTI/SIN, Celesc, SCGÁS, IMA/MTR, SEMAE/SNIS, ABIPET, IBGE, Epagri/Cidasc, Embrapa, CONAMA 430)
e gera **séries temporais sintéticas** com variação estocástica realista, para avaliar uma simbiose
agroindústria do Oeste → têxtil do Vale do Itajaí.

## Uso
```bash
pip install numpy matplotlib
python -m dt2sc fontes     --saida saida      # registro de proveniência (45 parâmetros: 25 R, 12 L, 8 H)
python -m dt2sc telemetria --saida saida      # JSONL MQTT Sparkplug-B + NodeIds OPC UA + CSV + alarmes CONAMA 430
python -m dt2sc avaliar    --n 10000          # Monte Carlo 10.000 anos, 4 cenários, figuras, resultados.json
python -m pytest tests
```
Tipos de dado: **R** = público real · **L** = proxy de literatura · **H** = hipótese (substituir por licença/planta).

## Novidades v0.3b (paridade Argus e cavaco)
- Preço de referência do biometano = paridade Argus com o gás (R$ 2,43-2,79/m3, SP/RJ, 23/02/2024), no lugar da tarifa hipotética de R$ 2,80-3,17. A hipótese antiga ficou como `tarifa_gn_ind_v02`.
- Cavaco: seis ofertas de SC (MF Rural) convertidas para R$/m3 de gás equivalente (`economia.avaliar_cavaco`; PCI, densidade e eficiências são hipóteses).
- Resultado: competitividade sem taxa de destinação 27 % (era 48 %); com taxa 98,8 %; VPL do sistema R$ 81 mi. Biometano só vence o cavaco em 4 % das amostras.
- `Parametros.java`/`Lancador.java` usam 2,61; o traço JADE do artigo foi gerado com 3,00 e não foi regenerado.

## Novidades v0.3 (dados reais de tinturarias de SC, repositório UFSC)
- `fontes.py`: 74 parâmetros (45 R, 14 L, 15 H). Eletricidade da tinturaria 808 kWh/t (Appel 2019, 11,9 GWh/ano para 14.733 t); água com moda 170 m3/t (Twardokus 2004); porte 2-40 t/dia (Justo 2021; Appel 2019); receita de pré-alvejamento (Falani 2022).
- O gás natural (1.143 Nm3/t) segue como proxy: a planta de Appel queima cavaco e não mediu vapor.
- `python -m dt2sc sensibilidade --n 4000` reavalia o gêmeo com eletricidade antiga, porte 2 e 40 t/dia, gás -50 % e água 80 m3/t (gera `saida/sensibilidade_v03.json`).
- Resultado central: S3 -24,9 % e S4 -58,5 % de CO2e na tinturaria; S4 cai para -21,8 % em uma tinturaria de 40 t/dia.
- Pendente: referência completa de Justo (2021) e handles UFSC de Appel e Falani.

## Novidades v0.2 (escopo IET CIM: colaboração entre empresas)
- `economia.py` – custo nivelado do biometano (preço de equilíbrio), VPL do sistema e custo evitado, com tarifas
  **Celesc A4 Verde (ANEEL REH 3.511/2025)** e componente de gás **ARESC Res. 287/2024**; CAPEX AGRIC/Cocal.
  ⚠️ A tarifa industrial TG1 da SCGÁS não foi publicada em formato extraível: está delimitada (R$ 2,80–3,17/m3)
  em `fontes.py` (`tarifa_gn_ind`) — substitua pelo valor da tabela vigente.
- `negociacao.py` – agentes frigorífico–usina–tinturaria (barganha FIPA-ACL, táticas de Faratin),
  **espaço de dados** (conectores com políticas de uso no estilo ODRL/IDS, auditoria) e **humano no laço**
  (autonomia limitada, aprovação de prêmio ESG e do conselho).
- `java/` – os mesmos agentes em **JADE (Java 11)** para o laboratório (IntelliJ). Ver `java/README.md`.

## Módulos
- `fontes.py` – registro de proveniência e perfis de destinação do MTR/IMA
- `telemetria.py` – gerador OPC UA/MQTT (turnos, AR(1), outliers, faltantes, deriva) + teste de fechamento de calibração
- `federacao.py` – LDT agro e LDT têxtil, fluxos resíduo→biometano→rede de gás, rPET, reúso de água, controle PI do SEI
- `avaliacao.py` – cenários S0–S3, Monte Carlo, escala estadual
- `figuras.py`

## Lacunas de dados declaradas
- Não há BEN-SC atual publicado (último localizado: 1983–1996) → fator do SIN (MCTI) usado no lugar.
- FIESC não publica kWh/t por segmento → intensidades da tinturaria vêm de estudo de caso (proxy L).
- MTR-Online: base bruta exige acesso; usados os agregados do Boletim Anual IMA 2021–2023.
- Camada econômica (tarifas, CAPEX, VPL) não incluída: requer tarifas por planta.

## v0.4 - modo planta (uso industrial)

Entrada: CSV do SCADA/historiador (timestamp, producao_kg_h, eletrica_kw obrigatórias; gn_m3_h, agua_m3_h,
cavaco_kg_h, vapor_kg_h, temp_efluente_c, ph opcionais). Detecta colunas por nome, aceita mapa e fatores de unidade.

    python -m dt2sc exemplo --saida saida/                       # CSV sintético no formato esperado
    python -m dt2sc planta planta.csv --saida saida/ --cavaco-r-t 250 --tarifa-gas 3.1 --gate-fee 60
    streamlit run app.py                                         # interface web local
    docker build -t dt2sc . && docker run -p 8501:8501 dt2sc
    # Colab: DT2-SC_planta_colab.ipynb (envie o ZIP e rode as células)

Saídas: qualidade dos dados, intensidades (kWh/t, m³ gás/t, água, CO2e), anomalias (kWh/t robusto e limites
CONAMA 430), calibração do gêmeo (parâmetros R sobrescritos pela planta, faixa = P5-P95 diário), cenários S0-S4,
preço de equilíbrio do biometano, comparação com cavaco local, relatório Markdown.

Testado: módulo `planta`, CLI, app (com stub do Streamlit), células do notebook (com stub do Colab), 12 testes.
NÃO testado: Streamlit real, Colab real, Docker, coletores MQTT/OPC UA contra servidores reais (use o CSV exportado
do historiador). Poucos dias de dados => faixas de incerteza assumidas em ±15 %.

## v0.5 - plataforma fechada (`app.py`)

Cada empresa tem login próprio, envia seus CSV dentro da plataforma e vê diagnóstico, calibração e cenários.
Empresas não enxergam dados umas das outras; o administrador gerencia empresas/usuários e vê a auditoria, mas não há
tela para ler os dados das empresas. (`app_aberto.py` é a versão sem login, só para uso local.)

    export DT2SC_ADMIN_USER=admin DT2SC_ADMIN_PASS='senha-longa-aqui'   # cria o 1º admin
    streamlit run app.py
    python -m dt2sc acesso criar-empresa --empresa tinturaria-alfa --nome "Tinturaria Alfa"
    python -m dt2sc acesso criar-usuario --usuario ana --empresa tinturaria-alfa     # pede a senha
    docker compose up -d     # dados persistem em ./dados_plataforma

Segurança implementada: hash PBKDF2-SHA256 com sal, senha mínima de 10 caracteres, bloqueio de 5 min após 5 erros,
sessão expira em 60 min de inatividade, isolamento por pasta, validação de nome/tamanho/tipo de upload, trilha de
auditoria. NÃO implementado: criptografia em repouso, HTTPS (use proxy reverso com TLS), 2FA, recuperação de senha
por e-mail (o admin redefine).

Hospedagem: o Streamlit Community Cloud NÃO é adequado para dados industriais: o disco é efêmero (arquivos somem ao
reiniciar) e os dados ficam em servidor de terceiros. Prefira um servidor da UniSENAI/SENAI com HTTPS e volume com
backup. Testes: 19 testes (acesso, isolamento, bloqueio, upload) e fluxo completo do app com stub do Streamlit.
