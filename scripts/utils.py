"""
utils.py — Calibration-aware backend ranking primitives
for the qaip-hardware-ranking Qollab notebook.

Self-contained: no dependency on the QAIP product package.
MIT License.

Sections
--------
1. Normalized Schema
2. Calibration Adapters  (IQM, IBM)
3. Feature Extraction    (per-qubit health, backend health)
4. Circuit Builders      (Bell, GHZ, QFT)
5. Circuit Features      (num_qubits, depth, 2Q count)
6. Scoring & Ranking     (transparent scoring formula)
7. Topology Visualization
8. Reasoning Trace       (rule-based, human-readable)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Optional

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from qiskit import QuantumCircuit


# ══════════════════════════════════════════════════════════════════════════════
# 1. NORMALIZED SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class QubitSnapshot:
    """
    Provider-agnostic per-qubit calibration data.

    Different providers report different metrics; we normalize everything
    to a common representation so the ranking logic is provider-agnostic.
    """
    qubit_id: str
    readout_fidelity: float          # 0–1, higher is better
    readout_error: float             # 0–1, lower is better
    t1_us: Optional[float] = None    # coherence time (µs); None if not reported
    t2_us: Optional[float] = None    # dephasing time (µs); None if not reported


@dataclass
class BackendSnapshot:
    """
    Provider-agnostic backend calibration snapshot.

    Produced by one of the calibration adapters below.
    Consumed by feature extraction and scoring.
    """
    backend_name: str
    provider: str                          # "IQM" | "IBM" | ...
    timestamp: Optional[str]
    num_qubits: int
    qubits: list[QubitSnapshot]
    connectivity: list[tuple[str, str]]    # pairs of connected qubit_ids
    native_gates: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
# 2. CALIBRATION ADAPTERS
# ══════════════════════════════════════════════════════════════════════════════

class IQMAdapter:
    """
    Parses an IQM observation-set calibration JSON into a BackendSnapshot.

    IQM reports per-qubit SSRO (state-space readout) fidelity.
    T1/T2 are available separately via the IQM live API (see the QAIP product
    for the production ingestion layer); they are not present in this snapshot
    format.

    The adapter pattern here shows two concrete implementations of a common
    interface.  A third provider would add a third adapter — no changes needed
    to the scoring or ranking code.
    """

    @staticmethod
    def load(path: str | Path) -> BackendSnapshot:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return IQMAdapter._parse(data)

    @staticmethod
    def _parse(data: dict) -> BackendSnapshot:
        # ── Parse per-qubit SSRO metrics from the observation array ──────────
        readout: dict[str, dict] = {}

        for obs in data["observations"]:
            field_path = obs["dut_field"]
            if "ssro" not in field_path:
                continue

            parts    = field_path.split(".")
            qubit_id = parts[-2]
            metric   = parts[-1]
            value    = obs["value"]

            if qubit_id not in readout:
                readout[qubit_id] = {}
            readout[qubit_id][metric] = value

        # ── Build QubitSnapshot list ──────────────────────────────────────────
        qubits = []
        for qubit_id, metrics in sorted(readout.items()):
            ssro    = metrics.get("fidelity",     0.0)
            err_01  = metrics.get("error_0_to_1", 0.0)
            err_10  = metrics.get("error_1_to_0", 0.0)
            avg_err = (err_01 + err_10) / 2

            qubits.append(QubitSnapshot(
                qubit_id=qubit_id,
                readout_fidelity=ssro,
                readout_error=avg_err,
                t1_us=None,   # not available in this snapshot format
                t2_us=None,
            ))

        return BackendSnapshot(
            backend_name=data.get("backend_name", "IQM Sirius"),
            provider="IQM",
            timestamp=data.get("created_timestamp"),
            num_qubits=len(qubits),
            qubits=qubits,
            connectivity=IQMAdapter._sirius_connectivity(),
            native_gates=["prx", "cz", "move"],
            metadata={"topology": data.get("topology", "star_16q")},
        )

    @staticmethod
    def _sirius_connectivity() -> list[tuple[str, str]]:
        """
        IQM Sirius 16-qubit coupling map.

        The Sirius architecture connects qubits through a central coupler
        resonator using the native MOVE gate.  The logical coupling graph
        below reflects the publicly documented qubit-qubit connectivity.
        """
        return [
            ("QB1",  "QB2"),  ("QB2",  "QB3"),  ("QB3",  "QB4"),
            ("QB4",  "QB5"),  ("QB5",  "QB6"),  ("QB6",  "QB7"),
            ("QB7",  "QB8"),  ("QB8",  "QB9"),  ("QB9",  "QB10"),
            ("QB10", "QB11"), ("QB11", "QB13"), ("QB13", "QB15"),
            ("QB15", "QB17"), ("QB17", "QB19"), ("QB19", "QB20"),
            ("QB20", "QB21"), ("QB21", "QB23"), ("QB23", "QB1"),
        ]


class IBMAdapter:
    """
    Parses an IBM Qiskit-style calibration JSON into a BackendSnapshot.

    IBM reports per-qubit T1, T2, readout_error, and per-gate error.
    This is the standard format emitted by Qiskit's FakeProvider backends
    and the IBM Quantum API.
    """

    @staticmethod
    def load(path: str | Path) -> BackendSnapshot:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return IBMAdapter._parse(data)

    @staticmethod
    def _parse(data: dict) -> BackendSnapshot:
        qubits = []

        for i, qubit_props in enumerate(data["qubits"]):
            metrics = {p["name"]: p["value"] for p in qubit_props}

            re = metrics.get("readout_error", 0.0)
            t1 = metrics.get("T1")
            t2 = metrics.get("T2")

            qubits.append(QubitSnapshot(
                qubit_id=str(i),
                readout_fidelity=round(1.0 - re, 6),
                readout_error=round(re, 6),
                t1_us=t1,
                t2_us=t2,
            ))

        # Extract connectivity from cx gate entries
        connectivity = [
            (str(e["qubits"][0]), str(e["qubits"][1]))
            for e in data.get("gates", [])
            if e["gate"] == "cx"
            and len(e["qubits"]) == 2
            and e["qubits"][0] < e["qubits"][1]   # deduplicate symmetric pairs
        ]

        return BackendSnapshot(
            backend_name=data["backend_name"],
            provider="IBM",
            timestamp=data.get("last_update_date"),
            num_qubits=len(qubits),
            qubits=qubits,
            connectivity=connectivity,
            native_gates=data.get("basis_gates", []),
            metadata={"backend_version": data.get("backend_version")},
        )




class IonQAdapter:
    """
    Parses an IonQ Aria-style calibration JSON into a BackendSnapshot.

    IonQ uses trapped-ion qubits — fundamentally different from superconducting:
      - All-to-all connectivity: every qubit pair can interact natively via
        the Molmer-Sorensen (MS) entangling gate. No routing cost for small circuits.
      - T1/T2 in seconds (not us). Coherence times 3-6 orders of magnitude
        longer than superconducting devices.
      - SPAM error (state preparation and measurement) replaces readout_error.
      - Native gates: GPI, GPI2, MS.
    """

    @staticmethod
    def load(path) -> BackendSnapshot:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return IonQAdapter._parse(data)

    @staticmethod
    def _parse(data: dict) -> BackendSnapshot:
        """
        Handles two formats:
          Real API  — response from /characterizations/backends/{backend}/current
                      has aggregate fidelity only (no per-qubit breakdown)
          Fake data — our synthetic file with per_qubit list (used as placeholder)

        IonQ's public API does not expose per-qubit SPAM/T1/T2.
        For real data, all qubits receive the aggregate backend value.
        Qubit-to-qubit variation is much smaller for trapped-ion than
        superconducting systems, so aggregate stats are meaningful.
        """
        real_api = "fidelity" in data and "timing" in data

        if real_api:
            # ── Real API format ───────────────────────────────────────────────
            fid        = data["fidelity"]
            spam_med   = fid["spam"]["median"]
            fid_1q     = fid.get("1q", {}).get("median")
            fid_2q     = fid.get("2q", {}).get("median")

            # Composite hardware quality:
            #   SPAM fidelity captures readout accuracy.
            #   1Q/2Q gate fidelity captures how cleanly the backend executes gates.
            #   For IonQ real data all three are available, so we blend them.
            #   Weights: 50% SPAM + 30% 1Q + 20% 2Q.
            if fid_1q is not None and fid_2q is not None:
                composite = round(0.5 * spam_med + 0.3 * fid_1q + 0.2 * fid_2q, 6)
            else:
                composite = spam_med

            t1_s  = data["timing"].get("t1")
            t2_s  = data["timing"].get("t2")
            t1_us = round(t1_s * 1e6, 0) if t1_s else None
            t2_us = round(t2_s * 1e6, 0) if t2_s else None
            n     = data["qubits"]

            qubits = [
                QubitSnapshot(
                    qubit_id=str(i),
                    readout_fidelity=composite,
                    readout_error=round(1.0 - composite, 6),
                    t1_us=t1_us,
                    t2_us=t2_us,
                )
                for i in range(n)
            ]

            raw_connectivity = data.get("connectivity", [])
            connectivity = [
                (str(pair[0]), str(pair[1]))
                for pair in raw_connectivity
            ] if raw_connectivity else [
                (str(i), str(j)) for i in range(n) for j in range(i+1, n)
            ]

            backend_name = data.get("backend", "ionq_backend").replace("qpu.", "ionq_").replace("-", "_")
            timestamp    = data.get("date") or data.get("_fetched_at")
            system       = "Aria" if "aria" in data.get("backend", "") else "Forte"
            meta_fidelity = {
                "spam":   round(spam_med, 4),
                "1q":     round(fid_1q, 4) if fid_1q else None,
                "2q":     round(fid_2q, 4) if fid_2q else None,
                "composite": composite,
            }

        else:
            # ── Fake/synthetic format (per_qubit list) ────────────────────────
            qubits = []
            for q in data["per_qubit"]:
                spam_err = q.get("spam_error", 0.0)
                qubits.append(QubitSnapshot(
                    qubit_id=str(q["qubit"]),
                    readout_fidelity=round(1.0 - spam_err, 6),
                    readout_error=round(spam_err, 6),
                    t1_us=q.get("t1_us"),
                    t2_us=q.get("t2_us"),
                ))

            n            = len(qubits)
            connectivity = [(str(i), str(j)) for i in range(n) for j in range(i+1, n)]
            backend_name = data.get("backend_name", "ionq_aria_1")
            timestamp    = data.get("calibration_time")
            system       = data.get("system", "Aria")
            meta_fidelity = None

        metadata = {
            "topology": "all_to_all",
            "system":   system,
            "source":   "real_api" if real_api else "synthetic",
        }
        if meta_fidelity:
            metadata["fidelity"] = meta_fidelity

        return BackendSnapshot(
            backend_name=backend_name,
            provider="IonQ",
            timestamp=str(timestamp) if timestamp else None,
            num_qubits=len(qubits),
            qubits=qubits,
            connectivity=connectivity,
            native_gates=data.get("native_gates", ["gpi", "gpi2", "ms"]),
            metadata=metadata,
        )

# ══════════════════════════════════════════════════════════════════════════════
# 3. FEATURE EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def per_qubit_health(snapshot: BackendSnapshot) -> dict[str, float]:
    """
    Compute a health score in [0, 1] for every physical qubit.

    For backends with only readout data (IQM in this snapshot format):
      health = readout_fidelity

    For backends with T1/T2 data (IBM):
      health = 0.70 × readout_fidelity
             + 0.20 × t1_normalized   (300 µs → 1.0)
             + 0.10 × t2_normalized   (200 µs → 1.0)

    The T1/T2 normalization constants reflect what a high-quality
    superconducting device looks like today.  They are transparent and
    easy to adjust.
    """
    scores = {}

    for q in snapshot.qubits:
        if q.t1_us is not None and q.t2_us is not None:
            # Normalization anchors: 200 µs T1 and 150 µs T2 are "good"
            # for current NISQ superconducting devices; 1.0 beyond those.
            t1_norm = min(1.0, q.t1_us / 200.0)
            t2_norm = min(1.0, q.t2_us / 150.0)
            score   = (0.70 * q.readout_fidelity
                     + 0.20 * t1_norm
                     + 0.10 * t2_norm)
        else:
            score = q.readout_fidelity

        scores[q.qubit_id] = round(score, 6)

    return scores


def backend_health_score(snapshot: BackendSnapshot) -> float:
    """
    Scalar backend health aggregated from per-qubit scores.

    Uses 60 % median (robust to outlier qubits) + 40 % mean.
    Returns a value in [0, 1].
    """
    values = list(per_qubit_health(snapshot).values())
    if not values:
        return 0.0
    return round(0.6 * median(values) + 0.4 * mean(values), 6)


def health_summary(snapshot: BackendSnapshot) -> dict:
    """Human-readable health summary dict for a backend."""
    scores = per_qubit_health(snapshot)
    vals   = list(scores.values())
    return {
        "backend":         snapshot.backend_name,
        "provider":        snapshot.provider,
        "num_qubits":      snapshot.num_qubits,
        "health_score":    backend_health_score(snapshot),
        "mean_health":     round(mean(vals), 4),
        "min_health":      round(min(vals),  4),
        "max_health":      round(max(vals),  4),
        "best_qubit":      max(scores, key=scores.get),
        "worst_qubit":     min(scores, key=scores.get),
        "t1_available":    snapshot.qubits[0].t1_us is not None,
    }


def print_health_summary(snapshot: BackendSnapshot) -> None:
    """Pretty-print a health summary for a backend."""
    s = health_summary(snapshot)
    sep = "─" * 48
    print(sep)
    print(f"  {s['backend']}  ({s['provider']})")
    print(sep)
    print(f"  Qubits         : {s['num_qubits']}")
    print(f"  Health score   : {s['health_score']:.4f}")
    print(f"  Mean / min / max: {s['mean_health']:.4f} / "
          f"{s['min_health']:.4f} / {s['max_health']:.4f}")
    print(f"  Best qubit     : {s['best_qubit']}")
    print(f"  Worst qubit    : {s['worst_qubit']}")
    print(f"  T1/T2 available: {s['t1_available']}")
    fid = snapshot.metadata.get("fidelity")
    if fid:
        print(f"  Gate fidelity  : 1Q={fid['1q']}  2Q={fid['2q']}  SPAM={fid['spam']}")
        print(f"  Composite score: {fid['composite']:.4f}  (0.5×SPAM + 0.3×1Q + 0.2×2Q)")


# ══════════════════════════════════════════════════════════════════════════════
# 4. CIRCUIT BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def bell_circuit() -> QuantumCircuit:
    """
    2-qubit Bell state |Φ⁺⟩ = (|00⟩ + |11⟩) / √2.

    The minimal entangling circuit.  A Bell measurement with near-ideal
    results is the standard smoke test for two-qubit hardware quality.
    """
    qc = QuantumCircuit(2, name="Bell")
    qc.h(0)
    qc.cx(0, 1)
    qc.measure_all()
    return qc


def ghz_circuit(n: int = 5) -> QuantumCircuit:
    """
    n-qubit GHZ state (|00...0⟩ + |11...1⟩) / √2.

    Tests multi-qubit entanglement and connectivity: the linear CNOT chain
    means every qubit pair in the circuit must be reachable with low error.
    """
    qc = QuantumCircuit(n, name=f"GHZ({n})")
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    qc.measure_all()
    return qc


def qft_circuit(n: int = 4) -> QuantumCircuit:
    """
    Quantum Fourier Transform on n qubits.

    QFT has O(n²) gates and O(n) long-range controlled-phase interactions,
    making it sensitive to both gate fidelity and connectivity quality.
    """
    qc = QuantumCircuit(n, name=f"QFT({n})")
    for i in range(n):
        qc.h(i)
        for j in range(i + 1, n):
            qc.cp(math.pi / (2 ** (j - i)), i, j)
    # Optional: add bit-reversal swaps for standard QFT output ordering
    for i in range(n // 2):
        qc.swap(i, n - 1 - i)
    qc.measure_all()
    return qc


# ══════════════════════════════════════════════════════════════════════════════
# 5. CIRCUIT FEATURE EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

_TWO_QUBIT_GATES = frozenset({
    "cx", "cz", "cp", "ecr", "rzz", "rxx", "ryy",
    "crx", "cry", "crz", "swap", "iswap", "dcx", "ch",
})


def extract_circuit_features(qc: QuantumCircuit) -> dict:
    """
    Extract hardware-relevant features from a Qiskit circuit.

    These features feed the scoring function and tell it what the circuit
    demands from a backend.

    Returns
    -------
    dict with keys:
        name             : circuit name
        num_qubits       : logical qubit count
        depth            : circuit depth (layers of gates)
        gate_count       : total gate count (excluding measurements)
        two_qubit_count  : number of two-qubit gates
        entanglement_ratio : two_qubit_count / gate_count
    """
    ops = qc.count_ops()
    # Exclude measurement from gate counts
    non_meas = {g: c for g, c in ops.items() if g != "measure"}
    total_gates    = sum(non_meas.values())
    two_qubit_count = sum(
        c for g, c in non_meas.items() if g in _TWO_QUBIT_GATES
    )

    return {
        "name":              qc.name,
        "num_qubits":        qc.num_qubits,
        "depth":             qc.depth(),
        "gate_count":        total_gates,
        "two_qubit_count":   two_qubit_count,
        "entanglement_ratio": round(
            two_qubit_count / max(1, total_gates), 3
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 6. SCORING AND RANKING
# ══════════════════════════════════════════════════════════════════════════════

#: Default weights for the scoring function.
#: Adjust these to explore the sensitivity of rankings to your priorities.
DEFAULT_WEIGHTS: dict[str, float] = {
    "readout_quality":  0.70,   # per-qubit readout fidelity (always available)
    "coherence_margin": 0.20,   # T1 headroom above circuit time (IBM only)
    "capacity_fit":     0.10,   # hard penalty if backend has too few qubits
}

# Gate duration assumed for coherence estimation (50 ns/layer is typical
# for superconducting qubits; adjust if you know the backend clock speed).
_GATE_DURATION_US: float = 0.050   # 50 ns per gate layer, in µs

# Margin at which T1 is considered "ample" (no longer a differentiator).
# 100× circuit time → full score. Below 10× → steep penalty.
_AMPLE_MARGIN: float = 100.0


def score_backend(
    snapshot: BackendSnapshot,
    circuit_features: dict,
    weights: Optional[dict] = None,
) -> tuple[float, dict]:
    """
    Score a backend for a specific circuit.

    Parameters
    ----------
    snapshot         : BackendSnapshot for the candidate backend
    circuit_features : output of extract_circuit_features()
    weights          : weight dict to override DEFAULT_WEIGHTS

    Returns
    -------
    (score, breakdown)
        score     : float in [0, 1]
        breakdown : dict explaining each component

    Scoring components
    ------------------

    readout_quality
        Mean health of the N best qubits (N = circuit width).
        We assume the mapper will place logical qubits on the
        physically best available sites.

    coherence_margin
        T1 relative to estimated circuit runtime.
        Only computed if T1 data is available (IBM).
        If unavailable (IQM in this snapshot format), we assume the
        backend is comfortable for circuits with depth < 20, and note
        the assumption explicitly.

    capacity_fit
        1.0 if the backend has enough physical qubits for the circuit.
        0.0 if it does not — a hard fail.
    """
    w = weights or DEFAULT_WEIGHTS
    n_needed     = circuit_features["num_qubits"]
    circuit_depth = circuit_features["depth"]

    # ── Component 1: Readout quality ──────────────────────────────────────────
    qubit_scores = per_qubit_health(snapshot)
    top_n_scores = sorted(qubit_scores.values(), reverse=True)[:n_needed]
    readout_component = mean(top_n_scores) if top_n_scores else 0.0

    # ── Component 2: Coherence margin ─────────────────────────────────────────
    t1_values = [q.t1_us for q in snapshot.qubits if q.t1_us is not None]

    if t1_values:
        median_t1         = median(t1_values)
        est_runtime_us    = max(circuit_depth * _GATE_DURATION_US, 0.001)
        margin            = median_t1 / est_runtime_us
        # Smooth mapping: 100× margin → 1.0; 10× → 0.8; 2× → 0.4; <1× → 0
        coherence_component = min(1.0, math.log10(max(margin, 1.0)) / math.log10(_AMPLE_MARGIN))
        t1_note = f"T1 median {median_t1:.0f} µs, est. runtime {est_runtime_us:.3f} µs"
    else:
        # No T1 in this snapshot.  IQM hardware has excellent coherence for
        # shallow circuits; we assign a near-ample score and note the assumption.
        coherence_component = 0.90 if circuit_depth <= 20 else 0.65
        t1_note = "T1 not in snapshot; assumed comfortable for shallow circuits"

    # ── Component 3: Capacity fit ──────────────────────────────────────────────
    capacity_component = 1.0 if snapshot.num_qubits >= n_needed else 0.0

    # ── Weighted sum ───────────────────────────────────────────────────────────
    score = (
        w["readout_quality"]  * readout_component
      + w["coherence_margin"] * coherence_component
      + w["capacity_fit"]     * capacity_component
    )

    breakdown = {
        "readout_quality":   round(readout_component,   4),
        "coherence_margin":  round(coherence_component, 4),
        "capacity_fit":      round(capacity_component,  4),
        "score":             round(score,               4),
        "t1_note":           t1_note,
        "qubits_needed":     n_needed,
        "qubits_available":  snapshot.num_qubits,
    }

    return round(score, 4), breakdown


def rank_backends(
    snapshots: list[BackendSnapshot],
    circuit: QuantumCircuit,
    weights: Optional[dict] = None,
) -> list[dict]:
    """
    Rank a list of backends for a given circuit.

    Returns a list of result dicts sorted best → worst, each containing:
        rank, backend, provider, score, breakdown, snapshot, circuit_features
    """
    features = extract_circuit_features(circuit)
    results  = []

    for snapshot in snapshots:
        score, breakdown = score_backend(snapshot, features, weights)
        results.append({
            "rank":             None,
            "backend":          snapshot.backend_name,
            "provider":         snapshot.provider,
            "score":            score,
            "breakdown":        breakdown,
            "snapshot":         snapshot,
            "circuit_features": features,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results


def print_ranking_table(results: list[dict]) -> None:
    """Pretty-print a ranking table to stdout."""
    if not results:
        print("No results.")
        return

    cf  = results[0]["circuit_features"]
    sep = "─" * 82

    print()
    print(f"  Circuit : {cf['name']}")
    print(f"  Qubits  : {cf['num_qubits']}  |  "
          f"Depth: {cf['depth']}  |  "
          f"2Q gates: {cf['two_qubit_count']}  |  "
          f"Entanglement ratio: {cf['entanglement_ratio']:.2f}")
    print()
    print(f"  {'Rank':<5} {'Backend':<25} {'Prov':<6} "
          f"{'Score':<8} {'Readout':<10} {'Coherence':<12} {'Capacity'}")
    print("  " + sep)

    for r in results:
        b      = r["breakdown"]
        marker = "★" if r["rank"] == 1 else " "
        print(f"  {marker}{r['rank']:<4} {r['backend']:<25} {r['provider']:<6} "
              f"{r['score']:<8.4f} {b['readout_quality']:<10.4f} "
              f"{b['coherence_margin']:<12.4f} {b['capacity_fit']:.4f}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# 7. TOPOLOGY VISUALIZATION
# ══════════════════════════════════════════════════════════════════════════════

def plot_backend_health(
    snapshot: BackendSnapshot,
    figsize: tuple = (9, 6),
    ax: Optional[plt.Axes] = None,
) -> None:
    """
    Draw the backend connectivity graph, coloring each node by qubit health.

    Green → healthy qubit, Red → degraded qubit.

    Parameters
    ----------
    snapshot : BackendSnapshot
    figsize  : figure size (used only if ax is None)
    ax       : optional existing Axes; if None, a new figure is created
    """
    G = nx.Graph()
    G.add_nodes_from(q.qubit_id for q in snapshot.qubits)

    all_to_all = snapshot.metadata.get("topology") == "all_to_all"

    # For all-to-all (IonQ): circular layout, skip drawing 300 edges.
    # For other backends: draw actual connectivity graph.
    if not all_to_all:
        G.add_edges_from(snapshot.connectivity)

    health = per_qubit_health(snapshot)
    colors = [health.get(n, 0.5) for n in G.nodes()]

    vmin = min(colors) - 0.002
    vmax = max(colors) + 0.002

    own_fig = ax is None
    if own_fig:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.get_figure()

    pos = (
        nx.circular_layout(G)
        if all_to_all
        else nx.spring_layout(G, seed=42, k=2.0, iterations=80)
    )

    nodes = nx.draw_networkx_nodes(
        G, pos,
        node_color=colors,
        cmap=plt.cm.RdYlGn,
        vmin=vmin, vmax=vmax,
        node_size=700,
        ax=ax,
    )
    nx.draw_networkx_edges(G, pos, alpha=0.35, width=1.5, ax=ax)
    nx.draw_networkx_labels(G, pos, font_size=7, font_weight="bold", ax=ax)

    cbar = fig.colorbar(nodes, ax=ax, fraction=0.03, pad=0.04)
    cbar.set_label("Qubit Health Score", fontsize=9)

    h = backend_health_score(snapshot)
    topo_note = "  |  All-to-all" if all_to_all else ""
    ax.set_title(
        f"{snapshot.backend_name}  ({snapshot.provider}){topo_note}\n"
        f"Backend health: {h:.4f}  |  Qubits: {snapshot.num_qubits}",
        fontsize=11,
    )
    ax.axis("off")

    if own_fig:
        plt.tight_layout()
        plt.show()


def plot_backends_side_by_side(
    snapshots: list[BackendSnapshot],
    figsize: tuple = (16, 6),
) -> None:
    """Plot one topology graph per backend, arranged horizontally."""
    n = len(snapshots)
    fig, axes = plt.subplots(1, n, figsize=figsize)
    if n == 1:
        axes = [axes]
    for ax, snap in zip(axes, snapshots):
        plot_backend_health(snap, ax=ax)
    plt.tight_layout()
    plt.show()


# ══════════════════════════════════════════════════════════════════════════════
# 8. REASONING TRACE
# ══════════════════════════════════════════════════════════════════════════════

def explain_ranking(results: list[dict]) -> str:
    """
    Generate a human-readable explanation of the ranking decision.

    This is a rule-based trace — produced deterministically from the
    numeric scoring breakdown.  It explains the *why* behind each rank,
    not just the numbers.

    This is the pedagogical version.  The QAIP product's explain() method
    returns a structured, machine-readable reasoning object (JSON) that
    can be consumed by downstream tools.
    """
    if not results:
        return "No backends to rank."

    w    = DEFAULT_WEIGHTS
    cf   = results[0]["circuit_features"]
    best = results[0]

    lines: list[str] = []
    sep  = "═" * 62

    lines += [
        sep,
        f"  RANKING EXPLANATION",
        f"  Circuit : {cf['name']}  "
        f"({cf['num_qubits']}q, depth {cf['depth']}, "
        f"{cf['two_qubit_count']} 2Q gates)",
        sep,
    ]

    for r in results:
        b      = r["breakdown"]
        marker = "★ " if r["rank"] == 1 else "  "
        lines.append(
            f"\n{marker}#{r['rank']}  {r['backend']}  "
            f"[{r['provider']}]  →  score {r['score']:.4f}"
        )
        lines.append(
            f"    Readout quality  {b['readout_quality']:.4f}  "
            f"× {w['readout_quality']:.0%} weight"
        )
        lines.append(
            f"    Coherence margin {b['coherence_margin']:.4f}  "
            f"× {w['coherence_margin']:.0%} weight"
        )
        lines.append(
            f"    Capacity fit     {b['capacity_fit']:.4f}  "
            f"× {w['capacity_fit']:.0%} weight"
        )
        lines.append(f"    [{b['t1_note']}]")

    lines.append("\n" + "─" * 62)
    lines.append(f"\n  Why {best['backend']} ranked first:\n")

    bd = best["breakdown"]

    if bd["readout_quality"] >= 0.975:
        lines.append(
            f"  ✓ Strong readout quality ({bd['readout_quality']:.4f}): "
            f"its top {cf['num_qubits']} qubit(s) have low measurement error."
        )
    elif bd["readout_quality"] >= 0.950:
        lines.append(
            f"  ✓ Adequate readout quality ({bd['readout_quality']:.4f})."
        )
    else:
        lines.append(
            f"  △ Readout quality is modest ({bd['readout_quality']:.4f}); "
            f"other components drive the win."
        )

    if bd["coherence_margin"] >= 0.95:
        lines.append(
            f"  ✓ Ample coherence margin ({bd['coherence_margin']:.4f}): "
            f"T1 is well above estimated circuit runtime."
        )
    elif bd["coherence_margin"] >= 0.80:
        lines.append(
            f"  ✓ Comfortable coherence margin ({bd['coherence_margin']:.4f})."
        )
    else:
        lines.append(
            f"  △ Coherence margin ({bd['coherence_margin']:.4f}) not reported "
            f"for this backend; assumed comfortable for shallow circuits."
        )

    if bd["capacity_fit"] == 1.0:
        lines.append(
            f"  ✓ Sufficient qubits: {bd['qubits_available']} available, "
            f"{bd['qubits_needed']} needed."
        )
    else:
        lines.append(
            f"  ✗ Insufficient qubits ({bd['qubits_available']} available, "
            f"{bd['qubits_needed']} needed)."
        )

    # Show gap to second place if present
    if len(results) > 1:
        second = results[1]
        gap    = best["score"] - second["score"]
        lines.append(
            f"\n  Gap to #{second['rank']} ({second['backend']}): "
            f"+{gap:.4f}"
        )
        if gap < 0.01:
            lines.append(
                "  Note: the gap is small — consider running both backends "
                "if submission costs allow."
            )

    # Show gate fidelity breakdown for IonQ backends if available
    for r in results:
        fid = r["snapshot"].metadata.get("fidelity")
        if fid and fid.get("1q") is not None:
            lines.append(
                f"\n  {r['backend']} gate fidelity breakdown:\n"
                f"    SPAM: {fid['spam']}  |  1Q: {fid['1q']}  |  2Q: {fid['2q']}\n"
                f"    Composite: {fid['composite']:.4f}  (0.5×SPAM + 0.3×1Q + 0.2×2Q)"
            )

    lines.append(
        "\n  ─────────────────────────────────────────────────────────\n"
        "  IonQ scores use real API calibration: SPAM + 1Q + 2Q gate\n"
        "  fidelity blended into a composite hardware quality score.\n"
        "  The QAIP production layer adds: calibration drift trends,\n"
        "  topology-aware routing cost, circuit-family-specific weights,\n"
        "  and uncertainty bounds.\n"
        "  See github.com/[your-org]/QAIP for the full system."
    )

    return "\n".join(lines)
