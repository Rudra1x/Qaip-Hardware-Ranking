# Notebook Outline — Calibration-Aware Hardware Ranking
## qaip-hardware-ranking | Qollab Track 1

Cell-by-cell plan. Each cell has a type (Markdown/Code), a title, a ~1-sentence purpose, and the key content. Write the actual `.ipynb` from this outline.

---

## Part 0 — Setup (hidden from readers on Qollab; runs automatically)

### Cell 0.1 · Code · Install dependencies
```
!pip install qiskit qiskit-aer matplotlib networkx numpy -q
```
Qollab runs this before the reader sees any output. Keep quiet (`-q`).

---

## Part 1 — Introduction

### Cell 1.1 · Markdown · Title and problem statement

**Title:** Calibration-Aware Hardware Ranking for Quantum Circuits

**Content:**
> Running a quantum circuit is not like running a classical program. Different quantum backends have different calibration states: qubits vary in readout fidelity, coherence time, and gate error — and those metrics change daily. Choosing the wrong backend can cost you fidelity before you even consider circuit compilation.
>
> This notebook demonstrates **calibration-aware backend ranking**: a systematic way to select the best available backend for your circuit, using real calibration data rather than static hardware specs.
>
> We cover one complete idea, end to end: load calibration → normalize → extract features → score → rank → visualize → explain → run.
>
> *(This is one primitive in a larger execution planning stack, [QAIP](link), which also handles qubit mapping, routing estimation, and execution optimization. Those layers are out of scope here.)*

### Cell 1.2 · Code · Imports

```python
import json, math
from pathlib import Path
from statistics import mean, median

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from qiskit import QuantumCircuit

from utils import (
    IQMAdapter, IBMAdapter,
    per_qubit_health, backend_health_score, health_summary,
    print_health_summary,
    bell_circuit, ghz_circuit, qft_circuit,
    extract_circuit_features,
    score_backend, rank_backends,
    print_ranking_table, DEFAULT_WEIGHTS,
    plot_backend_health, plot_backends_side_by_side,
    explain_ranking,
)
```

*No credentials needed. Everything runs locally except the final hardware cell.*

---

## Part 2 — Calibration Ingestion

### Cell 2.1 · Markdown · The normalized schema

Explain the problem: IQM and IBM return calibration in completely different formats. The adapter pattern normalizes both to `BackendSnapshot` + `QubitSnapshot` so the ranking code never sees provider details.

Show the dataclass definitions inline as Markdown (not code — readers should see the schema as documentation, not have to run it).

```
BackendSnapshot
  backend_name: str
  provider: str
  num_qubits: int
  qubits: list[QubitSnapshot]
  connectivity: list[tuple[str, str]]

QubitSnapshot
  qubit_id: str
  readout_fidelity: float   # 0–1, higher is better
  readout_error: float      # 0–1, lower is better
  t1_us: float | None       # µs; None if provider doesn't report
  t2_us: float | None
```

### Cell 2.2 · Code · Load IQM calibration

```python
iqm = IQMAdapter.load("data/iqm_sirius.json")
print(f"Loaded: {iqm.backend_name} ({iqm.provider}) — {iqm.num_qubits} qubits")
print(f"Timestamp: {iqm.timestamp}")
print(f"\nFirst qubit: {iqm.qubits[0]}")
```

**Expected output:**
```
Loaded: IQM Sirius (IQM) — 16 qubits
Timestamp: 2026-07-06T05:53:44.787841

First qubit: QubitSnapshot(qubit_id='QB1', readout_fidelity=0.98195,
             readout_error=0.01805, t1_us=None, t2_us=None)
```

### Cell 2.3 · Code · Load IBM calibration

```python
ibm = IBMAdapter.load("data/ibm_kolkata_fake.json")
print(f"Loaded: {ibm.backend_name} ({ibm.provider}) — {ibm.num_qubits} qubits")
print(f"\nFirst qubit: {ibm.qubits[0]}")
```

**Expected output:**
```
Loaded: ibm_kolkata_fake (IBM) — 27 qubits

First qubit: QubitSnapshot(qubit_id='0', readout_fidelity=0.9712,
             readout_error=0.0288, t1_us=162.3, t2_us=88.1)
```

### Cell 2.4 · Markdown · Adapter pattern note

Short paragraph: adding a third provider (IonQ, Rigetti, OQC) means writing a third adapter. The `score_backend` and `rank_backends` functions remain unchanged. This is the provider-agnostic layer.

Note that IQM's SSRO calibration snapshot doesn't include T1/T2. Those are available through the live IQM API (and handled in QAIP's production ingestion layer). For this notebook, IQM's T1/T2 are treated as "available but not in this snapshot" and the scoring function accounts for that explicitly.

---

## Part 3 — Feature Extraction

### Cell 3.1 · Markdown · Per-qubit health

Explain: raw SSRO fidelity is one metric. `per_qubit_health` normalizes across providers and combines readout + T1/T2 into a single [0, 1] health score per qubit.

For IQM: `health = readout_fidelity` (SSRO, the dominant metric for this snapshot format)
For IBM: `health = 0.70 × readout_fidelity + 0.20 × t1_normalized + 0.10 × t2_normalized`

### Cell 3.2 · Code · Per-qubit health for IQM

```python
iqm_health = per_qubit_health(iqm)

# Sort by health descending
for qid, h in sorted(iqm_health.items(), key=lambda x: -x[1]):
    bar = "█" * int(h * 40)
    print(f"  {qid:6s}  {h:.4f}  {bar}")
```

**Purpose:** readers can see which qubits are healthy and which are degraded — at a glance, before any scoring.

### Cell 3.3 · Code · Per-qubit health for IBM

Same as above for IBM. Note the difference: IBM shows health variation driven partly by T1/T2 distribution, not just readout.

### Cell 3.4 · Code · Backend health summaries

```python
print_health_summary(iqm)
print()
print_health_summary(ibm)
```

**Show:** IQM has higher average readout fidelity (~0.982) vs IBM (~0.963). IBM has T1 data available; IQM does not in this snapshot format. This difference will drive the ranking.

---

## Part 4 — Example Circuits

### Cell 4.1 · Markdown · Three example circuits

Brief descriptions of Bell, GHZ(5), and QFT(4) — what they test and why they're canonical benchmarks.

### Cell 4.2 · Code · Build and display circuits

```python
circuits = [bell_circuit(), ghz_circuit(5), qft_circuit(4)]

for qc in circuits:
    print(f"\n{qc.name}")
    print(qc.draw("text", fold=80))
```

### Cell 4.3 · Code · Extract circuit features

```python
for qc in circuits:
    f = extract_circuit_features(qc)
    print(f"{f['name']:12s}  qubits={f['num_qubits']}  "
          f"depth={f['depth']}  2Q={f['two_qubit_count']}  "
          f"entanglement_ratio={f['entanglement_ratio']:.2f}")
```

**Purpose:** show what the scoring function actually uses about each circuit. Demystify "what does the ranker see about my circuit."

---

## Part 5 — Ranking

### Cell 5.1 · Markdown · The scoring function

Explain the formula clearly. Show the weights. Describe each component in one sentence. The key message: **for shallow NISQ circuits, readout quality is the primary differentiator.**

```
score = 0.70 × readout_quality
      + 0.20 × coherence_margin
      + 0.10 × capacity_fit
```

Note: weights are named constants (`DEFAULT_WEIGHTS`) and easy to change. No learned parameters.

### Cell 5.2 · Code · Rank backends for Bell circuit

```python
results_bell = rank_backends([iqm, ibm], bell_circuit())
print_ranking_table(results_bell)
```

**Expected:** IQM ranks first (superior readout fidelity outweighs IBM's coherence data for depth-2 circuit).

### Cell 5.3 · Code · Rank backends for GHZ(5)

```python
results_ghz = rank_backends([iqm, ibm], ghz_circuit(5))
print_ranking_table(results_ghz)
```

**Discussion (Markdown sub-cell):** The margin to IQM increases slightly because we're using 5 qubits — the mean health over the top 5 IQM qubits is higher than IBM's top 5.

### Cell 5.4 · Code · Rank backends for QFT(4)

```python
results_qft = rank_backends([iqm, ibm], qft_circuit(4))
print_ranking_table(results_qft)
```

**Discussion:** QFT has more depth and 2Q gates. IBM's coherence margin matters slightly more, but IQM's readout advantage is still decisive for depth-10 circuits.

### Cell 5.5 · Code · What happens when the circuit is too large?

```python
large_qc = QuantumCircuit(20)
large_qc.h(range(20))
large_qc.measure_all()

results_large = rank_backends([iqm, ibm], large_qc)
print_ranking_table(results_large)
print(explain_ranking(results_large))
```

**Discussion (Markdown):** IQM Sirius has 16 qubits; this circuit needs 20. `capacity_fit = 0.0` for IQM. IBM's 27 qubits cover the circuit, so IBM wins clearly — illustrating that qubit count, not just calibration quality, matters for larger circuits.

---

## Part 6 — Topology Visualization

### Cell 6.1 · Markdown · Reading the graph

Each node is a physical qubit. Color: green = healthy, red = degraded. Edges show which qubits can directly interact via native two-qubit gates. This tells you at a glance which qubits to avoid when mapping your circuit.

### Cell 6.2 · Code · Side-by-side topology plots

```python
plot_backends_side_by_side([iqm, ibm])
```

**What to look for:**
- IQM: most qubits are green (high SSRO), a few showing modest degradation. Star topology via central coupler.
- IBM: wider spread from green to yellow (T1/T2 variation). Heavy-hex connectivity pattern.

---

## Part 7 — Reasoning Trace

### Cell 7.1 · Markdown · Rule-based explanations

Ranking alone is not enough — you need to know *why* a backend ranked above another. `explain_ranking` generates a deterministic plain-language explanation from the scoring breakdown. No language model involved: the output is fully reproducible.

### Cell 7.2 · Code · Explain the Bell ranking

```python
print(explain_ranking(results_bell))
```

**Purpose:** show that the reasoning is readable, specific, and honest about what data was and wasn't available (e.g., "T1 not in snapshot; assumed comfortable for shallow circuit").

### Cell 7.3 · Code · Explain the large-circuit ranking

```python
print(explain_ranking(results_large))
```

**Purpose:** show the capacity failure path — the trace explicitly flags that IQM couldn't fit the circuit.

---

## Part 8 — Bring Your Own Circuit

### Cell 8.1 · Markdown · Try it with your own circuit

```markdown
Replace the circuit below with your own. The ranking and reasoning trace
will update automatically.
```

### Cell 8.2 · Code · User-editable cell

```python
# ── Define your circuit here ──────────────────────────────────────────
qc = QuantumCircuit(3)
qc.h(0)
qc.cx(0, 1)
qc.cx(1, 2)
qc.rz(0.5, 2)
qc.measure_all()

# ── Rank and explain ──────────────────────────────────────────────────
my_results = rank_backends([iqm, ibm], qc)
print_ranking_table(my_results)
print()
print(explain_ranking(my_results))
```

---

## Part 9 — Hardware Run

*Depends on Neil confirming IonQ availability. Use whichever provider Qollab's playground supports.*

### Cell 9.1 · Markdown · Running on real hardware

Brief framing: we'll run the top-ranked circuit from the Bell ranking on the recommended backend, then compare the measured bit-string distribution with the noiseless simulation.

### Cell 9.2 · Code · Noiseless simulation (always runs)

```python
from qiskit_aer import AerSimulator

qc_bell = bell_circuit()
sim = AerSimulator()
job = sim.run(qc_bell, shots=1024)
counts_sim = job.result().get_counts()
print("Noiseless simulation:", counts_sim)
```

### Cell 9.3 · Code · Hardware run (requires Qollab provider)

*Placeholder — fill in with Qollab SDK once provider is confirmed.*

```python
# PENDING: IonQ availability confirmed by Neil Veira (Qollab Team)
# Fallback: use IQM or IBM via Qollab playground runner

# from qiskit_ionq import IonQProvider   # or Qollab-specific import
# provider = IonQProvider(token=...)     # handled by Qollab runner
# backend = provider.get_backend("ionq_aria_1")
# job = backend.run(qc_bell, shots=1024)
# counts_hw = job.result().get_counts()
# print("Hardware result:", counts_hw)

print("Hardware run cell — provider pending Qollab confirmation.")
print("The ranking above tells you which backend to target.")
```

### Cell 9.4 · Code · Compare results (conditional on hardware run)

```python
# Plot side by side: ideal vs hardware
# (Run this cell after Cell 9.3 produces counts_hw)
```

---

## Part 10 — About QAIP

### Cell 10.1 · Markdown · The bigger picture

```markdown
## About QAIP

This notebook demonstrates *calibration-aware backend ranking* —
one primitive in a larger execution planning stack.

[QAIP](https://github.com/[your-org]/QAIP) is a Python library for
hardware-adaptive quantum execution planning. Beyond backend ranking, it:

- Maps logical qubits to physical qubits using calibration-aware heuristics
- Estimates routing cost (MOVE vs SWAP strategies for each backend)
- Selects an execution strategy from multiple candidates
- Generates structured, machine-readable reasoning reports with confidence bounds
- Supports multiple providers through the same adapter pattern shown here

The QAIP production API looks like:

```python
from qaip import QuantumAdvisor
from qiskit import QuantumCircuit

qc = QuantumCircuit(4)
advisor = QuantumAdvisor()
report = advisor.analyze(qc)   # analyze → plan → explain
print(report.summary())
```

If you found this notebook useful, star the repo or open an issue — feedback
is welcome.

→ [github.com/[your-org]/QAIP](https://github.com/[your-org]/QAIP)
```

---

## Checklist before submitting to Qollab

- [ ] All cells run top-to-bottom with no errors
- [ ] Cell 0.1 (pip install) runs silently
- [ ] Hardware run cell degrades gracefully if provider not available (prints helpful message, doesn't error)
- [ ] IonQ / alternative provider confirmed and wired up
- [ ] `data/` folder included in repo
- [ ] `utils.py` included in repo
- [ ] README explains the public/private split briefly
- [ ] "About QAIP" section links to real GitHub URLs
- [ ] MIT license header in `utils.py`
- [ ] Notebook saved with output cells populated (Qollab reviewers see pre-run output)
