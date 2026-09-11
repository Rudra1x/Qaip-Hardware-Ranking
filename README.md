# QAIP Hardware Ranking

Calibration-aware backend ranking for quantum circuits. A Qollab Track 1 project.

MIT-licensed · [Live on Qollab](https://qollab.xyz)

---

## What this does

Different quantum backends have different calibration states every day. Readout fidelity, gate error, and coherence times all vary, and picking the wrong backend costs you fidelity before compilation even starts.

QAIP analyzes your circuit, classifies what it demands from hardware, and recommends the best backend using real calibration data from IQM and IonQ hardware APIs.

Five steps, end to end:

1. **Circuit intelligence**: fingerprint the circuit, classify its primary hardware sensitivity, adapt scoring weights accordingly
2. **Calibration scan**: load real IQM, IonQ, and IBM calibration; compute per-qubit health and topology fit per backend
3. **QAIP recommendation**: rank all backends using four-component adaptive scoring; output confidence signal
4. **Cross-backend comparison**: pre-run results across six backends including a real IonQ QPU run
5. **Live run**: submit your circuit to the selected backend, see real quantum counts, rank your result against the field

---

## Repository structure

```
qaip-hardware-ranking/
├── qollab_project_code.py      # Qollab playground script (self-contained)
├── utils.py                    # full library implementation (~550 lines)
├── requirements.txt
├── DECISIONS.md                # key design decisions and project history
├── data/
│   ├── iqm_sirius.json         # real IQM Sirius SSRO calibration
│   ├── ionq_aria_1.json        # real IonQ Aria 1 calibration
│   ├── ionq_aria_2.json        # real IonQ Aria 2 calibration
│   └── ionq_forte_1.json       # real IonQ Forte 1 calibration
├── scripts/
│   └── fetch_ionq_calibration.py  # re-fetch calibration from IonQ API
├── LICENSE
└── README.md
```

---

## Running locally

```bash
git clone https://github.com/Rudra1x/qaip-hardware-ranking
cd qaip-hardware-ranking
pip install -r requirements.txt
python qollab_project_code.py
```

---

## Quickstart

```python
from utils import IQMAdapter, IonQAdapter
from utils import rank_backends, print_ranking_table
from qiskit import QuantumCircuit

# Load real calibration snapshots
iqm   = IQMAdapter.load("data/iqm_sirius.json")
aria2 = IonQAdapter.load("data/ionq_aria_2.json")

# Define your circuit
qc = QuantumCircuit(4)
qc.h(0)
qc.cx(0, 1)
qc.cx(1, 2)
qc.cx(2, 3)
qc.measure_all()

# Rank
results = rank_backends([iqm, aria2], qc)
print_ranking_table(results)
```

---

## The intelligence layer

### Circuit fingerprinting

Before scoring hardware, QAIP classifies the circuit by what it demands:

| Fingerprint | Signal | Bottleneck |
|---|---|---|
| `READOUT_SENSITIVE` | entanglement ratio ≤ 0.60 | readout fidelity |
| `COHERENCE_SENSITIVE` | depth > 20 | coherence time |
| `TOPOLOGY_SENSITIVE` | entanglement ratio > 0.60 | connectivity match |
| `WIDTH_CONSTRAINED` | width > 15 qubits | qubit capacity |

### Adaptive scoring

```
score = w_readout   × readout_quality
      + w_coherence × coherence_margin
      + w_topology  × topology_fit
      + w_capacity  × capacity_fit
```

Weights shift per fingerprint. A `TOPOLOGY_SENSITIVE` circuit allocates 30% to topology fit. A `READOUT_SENSITIVE` circuit allocates 70% to readout quality.

### Topology fit

Scores are fixed, grounded in published hardware architecture specs:

| Backend | Fit score | Why |
|---|---|---|
| IonQ all-to-all | 1.00 | every qubit pair connects natively via shared vibrational modes; zero routing overhead |
| IQM star | 0.80–0.92 | MOVE gate required for non-adjacent pairs |
| IBM heavy-hex | 0.70–0.88 | SWAP insertion required for long-range interactions |

---

## Real calibration data

| Backend | Source | Date |
|---|---|---|
| IQM Sirius | IQM hardware API (real) | 2026-07-06 |
| IonQ Aria 1 | IonQ REST API (real) | 2026-09-09 |
| IonQ Aria 2 | IonQ REST API (real) | 2026-09-09 |
| IonQ Forte 1 | IonQ REST API (real) | 2026-09-09 |

To re-fetch fresh IonQ calibration:

```bash
export IONQ_API_KEY="your-key"
python scripts/fetch_ionq_calibration.py
```

---

## License

MIT. See `LICENSE`.
