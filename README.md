# Qaip-Hardware-Ranking

# Calibration-Aware Hardware Ranking for Quantum Circuits

A self-contained Qollab notebook that shows how to pick the right quantum backend for your circuit using live calibration data — not just qubit counts or static specs.

MIT-licensed. Runs one-click on [qollab.xyz](https://qollab.xyz).

---

## What this notebook teaches

Different quantum backends have different calibration states every day. Readout fidelity, gate error, and coherence times all vary — and picking the wrong backend costs you fidelity before compilation even starts.

This notebook walks through one complete idea end to end:

1. **Load calibration data** from IQM, IBM, and IonQ backends using a provider-agnostic adapter pattern
2. **Compute per-qubit health scores** from readout fidelity, gate fidelity, and coherence metrics
3. **Score and rank backends** for a given circuit using a transparent scoring formula
4. **Visualize** the hardware topology with per-qubit health as color
5. **Explain the ranking** in plain language — which backend won and why
6. **Run the top-ranked circuit** on real IonQ hardware through the Qollab playground

Three worked circuits (Bell, GHZ(5), QFT(4)) and a bring-your-own-circuit section are included.

---

## Repository structure

```
qaip-hardware-ranking/
├── notebook.ipynb              # Qollab notebook — one-click runnable
├── utils.py                    # self-contained implementation (~600 lines)
├── requirements.txt
├── data/
│   ├── iqm_sirius.json         # real IQM Sirius SSRO calibration
│   ├── ibm_kolkata_fake.json   # synthetic IBM 27q calibration
│   ├── ionq_aria_1.json        # real IonQ Aria 1 calibration
│   ├── ionq_aria_2.json        # real IonQ Aria 2 calibration
│   └── ionq_forte_1.json       # real IonQ Forte 1 calibration
├── scripts/
│   └── fetch_ionq_calibration.py   # pulls fresh IonQ calibration from API
├── LICENSE
└── README.md
```

## Running locally

```bash
pip install -r requirements.txt
jupyter notebook notebook.ipynb
```

No credentials needed for ranking and visualization cells. The hardware run cell uses your Qollab account.

---

## Quickstart

```python
from utils import IQMAdapter, IBMAdapter, IonQAdapter
from utils import rank_backends, print_ranking_table, explain_ranking
from qiskit import QuantumCircuit

# Load calibration snapshots
iqm   = IQMAdapter.load("data/iqm_sirius.json")
ibm   = IBMAdapter.load("data/ibm_kolkata_fake.json")
aria2 = IonQAdapter.load("data/ionq_aria_2.json")

# Define your circuit
qc = QuantumCircuit(4)
qc.h(0)
qc.cx(0, 1)
qc.cx(1, 2)
qc.cx(2, 3)
qc.measure_all()

# Rank and explain
results = rank_backends([iqm, ibm, aria2], qc)
print_ranking_table(results)
print(explain_ranking(results))
```

---

## The scoring function

```
score = 0.70 × readout_quality
      + 0.20 × coherence_margin
      + 0.10 × capacity_fit
```

**readout_quality** — mean health of the N best qubits (N = circuit width). For IQM: derived from SSRO fidelity. For IBM: readout error + T1/T2. For IonQ: composite of SPAM, 1Q gate fidelity, and 2Q gate fidelity.

**coherence_margin** — T1 relative to estimated circuit runtime. Backends with longer coherence times score higher for deeper circuits.

**capacity_fit** — 1.0 if the backend has enough qubits; 0.0 if not. Hard fail.

Weights are named constants (`DEFAULT_WEIGHTS` in `utils.py`) — easy to adjust. No learned parameters.

---

## About QAIP

This notebook is part of a larger project, [QAIP](https://github.com/[your-org]/QAIP), which builds on top of this ranking primitive to also handle qubit mapping, routing, and full execution planning. If you find this useful, check it out.

---

## License

MIT. See `LICENSE`.
