"""Figuras (PDF/PNG) para o artigo e relatório."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .fontes import v  # noqa: E402

CORES = ["#8a8f98", "#2b6cb0", "#2f855a", "#c05621", "#6b46c1"]
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.25, "figure.dpi": 150})
CURTO = ["S0", "S1", "S2", "S3", "S4"]


def _salvar(fig, pasta, nome):
    pasta = Path(pasta); pasta.mkdir(parents=True, exist_ok=True)
    fig.savefig(pasta / f"{nome}.pdf", bbox_inches="tight")
    fig.savefig(pasta / f"{nome}.png", bbox_inches="tight")
    plt.close(fig)


def fig_telemetria(t, s, pasta):
    h = np.arange(len(t)) / 24
    fig, axs = plt.subplots(3, 1, figsize=(7.2, 4.6), sharex=True)
    axs[0].plot(h, s["agro.abate.suinos_h"], lw=0.6, color=CORES[2], label="Pigs slaughtered (head/h)")
    ax2 = axs[0].twinx(); ax2.grid(False)
    ax2.plot(h, s["textil.caldeira.gn_m3_h"], lw=0.6, color=CORES[3], label="Dyehouse gas (Nm$^3$/h)")
    axs[0].set_ylabel("head/h"); ax2.set_ylabel("Nm$^3$/h")
    axs[0].legend(loc="upper left", fontsize=6, frameon=False); ax2.legend(loc="upper right", fontsize=6, frameon=False)
    axs[1].plot(h, s["agro.ete.og_mg_l"], lw=0.6, color=CORES[1], label="Agro effluent O&G (mg/L)")
    axs[1].axhline(v("lim_og_animal"), color="crimson", ls="--", lw=0.8, label="CONAMA 430 limit")
    axs[1].legend(fontsize=6, frameon=False, ncol=2); axs[1].set_ylabel("mg/L")
    axs[2].plot(h, s["agro.ete.temp_efluente_c"], lw=0.6, color=CORES[2], label="Agro effluent T")
    axs[2].plot(h, s["textil.ete.temp_efluente_c"], lw=0.6, color=CORES[3], label="Textile effluent T")
    axs[2].axhline(v("lim_temp_efluente"), color="crimson", ls="--", lw=0.8, label="CONAMA 430 limit")
    axs[2].set_ylabel("°C"); axs[2].set_xlabel("Day"); axs[2].legend(fontsize=6, frameon=False, ncol=3)
    fig.tight_layout(); _salvar(fig, pasta, "fig_telemetry")


def fig_cenarios(av, pasta):
    nomes = list(av["cenarios"])
    chaves = [("sei", "Federated SEI (–)"), ("co2_tex_kg_t", "Dyehouse CO$_2$e (kg/t)"),
              ("agua_tex_m3_t", "Dyehouse water (m$^3$/t)"), ("circ_agro", "Agro residue circularity (–)"),
              ("cobertura_bio", "Biomethane share of gas (–)"), ("dias_abaixo_sp", "Days below target (d/yr)")]
    fig, axs = plt.subplots(2, 3, figsize=(7.2, 4.0))
    for ax, (k, rot) in zip(axs.flat, chaves):
        r = [av["cenarios"][n][k] for n in nomes]
        m = [x["media"] for x in r]
        k_ = len(nomes)
        ax.bar(range(k_), m, yerr=[[m[i] - r[i]["p5"] for i in range(k_)], [r[i]["p95"] - m[i] for i in range(k_)]],
               color=CORES[:k_], capsize=2, width=0.65)
        ax.set_xticks(range(k_), CURTO[:k_]); ax.set_title(rot)
    fig.tight_layout(); _salvar(fig, pasta, "fig_scenarios")


def fig_co2(dec, pasta):
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    nomes = list(dec)
    base = np.zeros(len(nomes))
    for k, cor, rot in (("gas", "#c05621", "Fossil natural gas"), ("fibre", "#4a5568", "Polyester fibre"),
                        ("electricity", "#2b6cb0", "Grid electricity (SIN)")):
        val = np.array([dec[n][k] for n in nomes])
        ax.bar(range(len(nomes)), val, bottom=base, color=cor, label=rot, width=0.55)
        base += val
    ax.set_xticks(range(len(nomes)), ["S0 Silos", "S3 hub 3k", "S4 negotiated"][:len(nomes)])
    ax.set_ylabel("kg CO$_2$e / t dyed fabric"); ax.legend(fontsize=6, frameon=False)
    fig.tight_layout(); _salvar(fig, pasta, "fig_co2_breakdown")


def fig_controle(series, pasta):
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    for (nome, sr), cor in zip(series.items(), CORES):
        if nome.startswith("S0"):
            continue
        sr = np.array(sr)
        d = np.arange(len(sr))
        ax.plot(d, sr[:, 0], color=cor, lw=1, label=nome)
        ax.fill_between(d, sr[:, 1], sr[:, 2], color=cor, alpha=0.12)
    ax.axvspan(150, 180, color="crimson", alpha=0.08, label="Digester/hub outage")
    ax.set_xlabel("Day of year"); ax.set_ylabel("Daily federated SEI")
    ax.legend(fontsize=6, frameon=False, ncol=4, loc="lower right")
    fig.tight_layout(); _salvar(fig, pasta, "fig_control")


def fig_escala(av, pasta):
    e = av["estadual"]
    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    vals = [e["bio_m3_dia"]["media"] / 1e3, 25.0, v("scgas_vol_2024") / 1e3]
    rot = ["Divertible residual\nfat, all SC plants", "One regional hub\n(AGRIC design)", "SCGÁS sales\n(2024)"]
    ax.bar(range(3), vals, color=["#2f855a", "#2b6cb0", "#8a8f98"], width=0.6)
    ax.set_yscale("log"); ax.set_ylabel("thousand m$^3$/day")
    ax.set_xticks(range(3), rot, fontsize=6)
    for i, x in enumerate(vals):
        ax.text(i, x * 1.15, f"{x:,.1f}", ha="center", fontsize=6)
    fig.tight_layout(); _salvar(fig, pasta, "fig_state_scale")


def fig_economia(ec, pasta):
    import numpy as np
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 2.6))
    tg = ec["amostras"]["tarifa_gn"]
    for x, cor, rot in ((ec["p_equilibrio_sem_gate"], "#c05621", "Hub without gate fee"),
                        (ec["p_equilibrio_com_gate"], "#2f855a", "Hub with gate fee from slaughterhouses")):
        axs[0].hist(x, bins=60, color=cor, alpha=0.55, label=rot, density=True)
    axs[0].axvspan(tg.min(), tg.max(), color="#2b6cb0", alpha=0.15, label="Industrial gas tariff band")
    axs[0].axvline(v("teto_bio_arsal"), color="k", ls=":", lw=0.8, label="ARSAL price cap (AL)")
    axs[0].set_xlabel("Break-even biomethane price (R\\$/m$^3$)"); axs[0].set_ylabel("density")
    axs[0].legend(fontsize=5.5, frameon=False)
    cs = sorted(ec["vpl_sistema"])
    m = [np.mean(ec["vpl_sistema"][c]) / 1e6 for c in cs]
    lo = [m[i] - np.percentile(ec["vpl_sistema"][c], 5) / 1e6 for i, c in enumerate(cs)]
    hi = [np.percentile(ec["vpl_sistema"][c], 95) / 1e6 - m[i] for i, c in enumerate(cs)]
    axs[1].bar(range(len(cs)), m, yerr=[lo, hi], color="#2b6cb0", capsize=2, width=0.6)
    axs[1].set_xticks(range(len(cs)), [f"{c}" for c in cs]); axs[1].set_xlabel("Carbon price (R\\$/tCO$_2$e)")
    axs[1].set_ylabel("System NPV, 15 yr (R\\$ million)")
    fig.tight_layout(); _salvar(fig, pasta, "fig_economics")


def fig_negociacao(neg, pasta):
    import numpy as np
    regs = ["isolado", "espaco", "total"]
    rot = ["Isolated", "Data space", "Full transparency"]
    met = [("taxa_acordo", "Agreement rate"), ("volume_medio", "Contracted volume (m$^3$/day)"),
           ("co2_evitado_t_ano", "Expected CO$_2$ avoided (t/yr)"), ("dias", "Time to contract (days)")]
    fig, axs = plt.subplots(1, 4, figsize=(7.2, 2.3))
    x = np.arange(3)
    for ax, (k, t) in zip(axs, met):
        a = [neg[f"{r}|autonomo"][k] for r in regs]
        h = [neg[f"{r}|humano"][k] for r in regs]
        ax.bar(x - 0.18, a, 0.36, color="#2b6cb0", label="Autonomous agents")
        ax.bar(x + 0.18, h, 0.36, color="#c05621", label="Human-in-the-loop")
        ax.set_xticks(x, rot, rotation=30, ha="right", fontsize=6); ax.set_title(t, fontsize=7)
    axs[0].legend(fontsize=5.5, frameon=False, loc="lower left")
    fig.tight_layout(); _salvar(fig, pasta, "fig_negotiation")
