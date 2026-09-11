# Calibration-Aware Hardware Ranking for Quantum Circuits

Picking the right quantum backend matters more than most people realise. Different backends have different calibration states every day — qubits vary in readout fidelity, gate error, and coherence time. Sending a circuit to the wrong backend costs you fidelity before compilation even begins.

This project demonstrates **QAIP's execution intelligence**: a systematic way to analyze your circuit, classify what it demands from hardware, and recommend the best available backend using real calibration data — not static specs.

---

## The problem

Say you have access to IonQ Aria 1 and Aria 2. Same hardware class. Same 25 qubits. Same all-to-all connectivity. How do you choose?

Without calibration data, you can't. On the day we fetched calibration, Aria 1 had a degraded 1Q gate fidelity of **0.7913** — anomalously low, likely a maintenance state. Aria 2 was at **0.9997** — near-perfect. Same backend class, completely different execution quality.

QAIP sees this. A naive selector doesn't.

---

## Four backends compared

Calibration snapshots pulled directly from real hardware APIs.

### IQM Sirius *(fetched 2026-07-06)*
- 16 qubits, star topology via central resonator coupler
- Per-qubit SSRO (state-space readout) fidelity — mean **0.9828**
- Native MOVE gate enables qubit interactions through the resonator
- No T1/T2 in this snapshot format

### IonQ Aria 1 *(fetched 2026-09-09)*
- 25 qubits, all-to-all connectivity
- SPAM: 0.9953 · **1Q: 0.7913 (degraded)** · 2Q: 0.9862
- T1: 100 seconds — trapped-ion coherence far exceeds superconducting

### IonQ Aria 2 *(fetched 2026-09-09)*
- 25 qubits, all-to-all connectivity
- SPAM: 0.9974 · **1Q: 0.9997 (near-perfect)** · 2Q: 0.9699
- T1: 10 seconds

### IBM Boston *(Heron r3 architecture)*
- 156 qubits, heavy-hex topology
- Nearest-neighbor coupling — long-range interactions require SWAP insertion
- Readout fidelity: 0.974 · T1: ~186 µs

---

## The intelligence layer

QAIP does more than score hardware. Before ranking, it analyses the circuit itself.

### Step 1 — Circuit fingerprinting

QAIP classifies every circuit by what it demands from hardware:

| Fingerprint | Signal | Primary bottleneck |
|---|---|---|
| `READOUT_SENSITIVE` | shallow, entanglement ratio ≤ 0.60 | readout fidelity |
| `COHERENCE_SENSITIVE` | deep (depth > 20) or high depth-per-qubit | coherence time |
| `TOPOLOGY_SENSITIVE` | entanglement ratio > 0.60 | connectivity match |
| `WIDTH_CONSTRAINED` | circuit width > 15 qubits | qubit capacity |

A Bell circuit (depth 3, entanglement ratio 0.33) is `READOUT_SENSITIVE`. A GHZ(5) circuit (entanglement ratio 0.80) is `TOPOLOGY_SENSITIVE`. The ranker adjusts accordingly.

### Step 2 — Adaptive weights

Fixed weights (70/20/10) treat every circuit the same. QAIP shifts weights based on the fingerprint:

| Fingerprint | Readout | Coherence | Topology | Capacity |
|---|---|---|---|---|
| READOUT_SENSITIVE | 70% | 15% | 5% | 10% |
| COHERENCE_SENSITIVE | 40% | 45% | 5% | 10% |
| TOPOLOGY_SENSITIVE | 40% | 20% | 30% | 10% |
| WIDTH_CONSTRAINED | 40% | 15% | 10% | 35% |

### Step 3 — Four-component scoring

```
score = w_readout   × readout_quality
      + w_coherence × coherence_margin
      + w_topology  × topology_fit
      + w_capacity  × capacity_fit
```

**readout_quality** — mean health of the N best qubits (N = circuit width). IQM uses SSRO fidelity. IonQ blends SPAM + 1Q + 2Q gate fidelity. IBM uses readout error + T1/T2.

**coherence_margin** — T1 headroom above estimated circuit runtime. Matters for deep circuits; less relevant for shallow ones.

**topology_fit** — architecture-grounded connectivity score. IonQ all-to-all scores 1.00 for every circuit — zero routing overhead by design. IQM star scores 0.80–0.92 depending on entanglement demand. IBM heavy-hex scores 0.70–0.88 — long-range interactions require SWAP insertion, and QFT-class circuits are documented to inflate in depth even at maximum compiler optimization.

**capacity_fit** — 1.0 if the backend has enough qubits; 0.0 if not. Hard fail.

### Step 4 — Confidence signal

After ranking, QAIP outputs a confidence level based on the score gap between #1 and #2:

- **HIGH** — gap > 0.025, top backend healthy
- **MEDIUM** — gap > 0.010
- **LOW** — close call, consider running both

---

## Results

### Bell circuit — READOUT_SENSITIVE (depth 3, entanglement 0.33)

| Rank | Backend | Score | Readout | Coherence | Topology | Capacity |
|------|---------|-------|---------|-----------|----------|----------|
| ★ 1 | IonQ Aria 2 | 0.9948 | 0.9926 | 1.0000 | 1.0000 | 1.0000 |
| 2 | IBM Boston | 0.9758 | 0.9740 | 1.0000 | 0.8800 | 1.0000 |
| 3 | IQM Sirius | 0.9729 | 0.9885 | 0.9000 | 0.9200 | 1.0000 |
| 4 | IonQ Aria 1 | 0.9526 | 0.9323 | 1.0000 | 1.0000 | 1.0000 |

Confidence: MEDIUM (gap +0.0190)

Aria 2 wins on composite hardware quality. Aria 1 falls to last despite identical topology advantage — its degraded 1Q gate fidelity (0.79) pulls the composite health score down significantly.

### Before / After — The value of QAIP

Aria 1 and Aria 2 are indistinguishable without calibration data.

| Approach | Backend | Est. Bell fidelity |
|---|---|---|
| ✗ Without QAIP | IonQ Aria 1 | 77.3% |
| ★ With QAIP | IonQ Aria 2 | 96.5% |
| **Improvement** | | **+19.1 percentage points** |

Model: F = F_1Q × F_2Q × SPAM² (simplified product model)

### Cross-backend hardware results (Bell · 1024 shots · pre-run)

| Backend | \|00⟩ | \|11⟩ | \|01⟩ | \|10⟩ | Error | Source |
|---|---|---|---|---|---|---|
| ★ IonQ Aria 2 sim | 511 | 501 | 3 | 9 | 1.2% | simulator |
| IonQ Forte Ent. sim | 501 | 515 | 6 | 2 | 0.8% | simulator |
| IonQ Forte Ent. QPU | 487 | 517 | 11 | 9 | 2.0% | **real hardware** |
| IonQ Aria 1 sim | 508 | 510 | 1 | 5 | 0.6% | simulator |
| IBM Boston sim | 497 | 512 | 11 | 4 | 1.5% | simulator |
| IBM Miami sim | 511 | 462 | 22 | 29 | 5.0% | simulator |
| Ideal | 512 | 512 | 0 | 0 | 0.0% | reference |

IBM Miami shows 8× more error than IonQ Aria 2. Without calibration-aware ranking, there is no way to know this before submitting.

---

## What the code does

The playground runs five steps:

1. **Circuit intelligence** — fingerprints the Bell circuit, classifies it as `READOUT_SENSITIVE`, explains the reasoning, shows adapted weights
2. **Calibration scan** — loads real IQM, IonQ Aria 1, IonQ Aria 2, and IBM Boston calibration; computes health and topology fit per backend
3. **QAIP recommendation** — ranks all four backends using the four-component adaptive scoring formula; outputs confidence signal
4. **Cross-backend comparison** — pre-run results table across six backends including one real hardware QPU run
5. **Live run** — submits Bell circuit to your selected backend, returns real quantum counts, ranks your result against all pre-run backends

**Select any free simulator from the QPU dropdown** and hit Run. The live run section executes and shows where your backend lands in the field.

---

## Running locally

The full implementation with `utils.py` and real calibration JSON files is on GitHub:

**[github.com/Rudra1x/qaip-hardware-ranking](https://github.com/Rudra1x/qaip-hardware-ranking)**

```bash
git clone https://github.com/Rudra1x/qaip-hardware-ranking
cd qaip-hardware-ranking
pip install -r requirements.txt
python qollab_project_code.py
```

The repo includes:
- `utils.py` — full library implementation with proper classes and adapters (~550 lines)
- `qollab_project_code.py` — this Qollab script (self-contained, no local imports)
- `data/iqm_sirius.json` — real IQM Sirius SSRO calibration
- `data/ionq_aria_1.json` and `ionq_aria_2.json` — real IonQ calibration from the API
- `scripts/fetch_ionq_calibration.py` — re-fetch fresh calibration from the IonQ API

---

## About QAIP

This project is one primitive in [QAIP](https://github.com/Rudra1x/QAIP), a larger execution intelligence layer for quantum circuits that builds on top of this ranking to also handle qubit mapping, routing cost estimation, and full execution strategy selection.
