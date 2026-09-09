# Qaip-Hardware-Ranking

**Calibration-aware backend ranking for quantum circuits**

A self-contained, pedagogical implementation of one primitive from [QAIP](https://github.com/[your-org]/QAIP): ranking available quantum backends for a given circuit, using live calibration data rather than static hardware specs.

Published as a Qollab notebook (Track 1). MIT-licensed.

---

## What this notebook shows

Given a quantum circuit and calibration snapshots for two or more backends, this notebook:

1. **Loads and normalizes** calibration data from IQM and IBM backends using a provider-agnostic adapter pattern
2. **Extracts per-qubit health scores** from readout fidelity, T1, and T2 metrics
3. **Scores and ranks** backends using a transparent, readable scoring function (~50 lines, no learned parameters)
4. **Visualizes** the hardware topology with per-qubit health overlaid as color
5. **Generates a plain-language reasoning trace** explaining why backend A ranked above backend B for this specific circuit
6. **Runs the top-ranked circuit** on real hardware through the Qollab playground runner

Three worked example circuits (Bell, GHZ(5), QFT(4)) and a "bring your own circuit" section are included.

## What this notebook does NOT show

Routing estimation, qubit mapping optimization, execution strategy selection, confidence intervals, multi-provider authentication, or the full `QuantumAdvisor` API. Those layers are part of QAIP and are outside the scope of this focused primitive.

> This notebook demonstrates calibration-aware backend ranking — one primitive in a larger execution planning stack ([QAIP](https://github.com/[your-org]/QAIP)) that also handles qubit mapping, routing estimation, strategy selection, and execution optimization. Those layers are out of scope here; this notebook focuses on ranking done well, so it can serve as a building block for anyone working on hardware-adaptive quantum systems.

---

## Repository structure

```
qaip-hardware-ranking/
├── notebook.ipynb          # the Qollab notebook (one-click runnable)
├── utils.py                # clean self-contained implementation (~550 lines)
├── requirements.txt
├── data/
│   ├── iqm_sirius.json     # IQM Sirius SSRO calibration snapshot
│   └── ibm_kolkata_fake.json  # synthetic IBM 27q calibration (pedagogical)
├── outputs/                # figures saved by the notebook
├── LICENSE                 # MIT
└── README.md
```

## Running locally

```bash
pip install -r requirements.txt
jupyter notebook notebook.ipynb
```

No API credentials needed to run ranking and visualization.
The hardware execution cell (final section) requires a Qollab account or compatible provider credentials.

## Quickstart

```python
from utils import IQMAdapter, IBMAdapter, rank_backends, print_ranking_table, explain_ranking
from qiskit import QuantumCircuit

# Load calibration snapshots
iqm = IQMAdapter.load("data/iqm_sirius.json")
ibm = IBMAdapter.load("data/ibm_kolkata_fake.json")

# Define a circuit
qc = QuantumCircuit(4)
qc.h(0)
qc.cx(0, 1)
qc.cx(1, 2)
qc.cx(2, 3)
qc.measure_all()

# Rank and explain
results = rank_backends([iqm, ibm], qc)
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

**readout_quality** — mean health of the N best qubits (N = circuit width). Health is derived from SSRO fidelity for IQM and from readout_error + T1/T2 for IBM. Always computable; the primary differentiator for shallow NISQ circuits.

**coherence_margin** — T1 relative to estimated circuit runtime. Computed when T1 data is available (IBM). For backends without T1 in the snapshot (IQM), a comfortable value is assumed for shallow circuits and noted in the reasoning trace.

**capacity_fit** — 1.0 if the backend has enough physical qubits for the circuit; 0.0 otherwise. Hard fail.

The weights are named constants in `utils.py` (`DEFAULT_WEIGHTS`) and are easy to adjust. No learned parameters.

---

## Key design decisions

**No `import qaip`** — this is a clean reimplementation, not a wrapper. The QAIP product and this notebook can evolve independently.

**Adapter pattern** — two providers, two adapters (`IQMAdapter`, `IBMAdapter`). Adding a third provider means adding a third adapter; the scoring code is untouched.

**Transparent formula** — the scoring function is readable in its entirety in `utils.py`. Every term has a docstring explaining its purpose and derivation.

**Pedagogical reasoning trace** — `explain_ranking()` generates rule-based plain-language output from the scoring breakdown. No language model involved.

---

## About QAIP

This notebook is one primitive in QAIP (Quantum-Aware Intelligence and Planning), an execution intelligence layer for quantum circuits that handles:

- Calibration-aware backend ranking ← *you are here*
- Topology-aware qubit mapping
- Routing cost estimation (MOVE / SWAP strategy selection)
- Execution plan optimization
- Structured reasoning reports with confidence bounds
- Multi-provider provider adapters with live calibration ingestion

QAIP is under active development. For more: **[github.com/[your-org]/QAIP]**

---

## License

MIT. See `LICENSE`.
