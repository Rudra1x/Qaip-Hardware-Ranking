# QAIP Hardware Ranking — Key Design Decisions

Running record of the decisions that shaped this project.

---

## Platform: Qollab is a code playground, not a Jupyter runner

**Decision:** The submission is a single self-contained Python script, not a notebook.

**Rationale:** Qollab runs Python via WebAssembly (Pyodide) in the browser. There is no file system, no local imports, and no `jupyter` runtime. The `notebook.ipynb` approach was abandoned after discovering the platform. `qollab_project_code.py` embeds all calibration data as Python dicts and inlines all logic — no `from utils import`.

---

## Public / private split

**Decision:** `qollab_project_code.py` and `utils.py` are clean reimplementations. They do not import from the private QAIP product.

**Rationale:** The Qollab submission is pedagogical — the idea done once, done cleanly. The private QAIP product is the system. The public code can evolve independently, and the private codebase can be refactored freely without breaking the published submission.

Three tests govern every scoping decision: Weekend Test, Textbook Test, Fork Test.

---

## Topology fit: fixed scores, not dynamic graph computation

**Decision:** Topology fit uses architecture-grounded fixed lookup scores, not graph distance computation.

**Rationale:** Computing topology fit dynamically requires building the circuit's interaction graph and computing hardware graph distances — that is the routing estimation layer, which belongs to Track 3 and the private QAIP product. Fixed scores grounded in published hardware architecture literature are appropriate for Track 1 and pass the Textbook Test.

Sources: Xu et al. 2025 (QSteed), ASPLOS 2019 (noise-adaptive mappings), IonQ/IQM architecture documentation.

---

## Calibration data: real IQM and IonQ, synthetic IBM

**Decision:** IQM and IonQ calibration is fetched from real hardware APIs. IBM calibration is synthetic, labeled as such.

**Rationale:** IQM calibration was available through existing QAIP infrastructure. IonQ calibration was fetched via `api.ionq.co/v0.3/characterizations/backends/{backend}/current` using Qollab API credentials. IBM backends on Qollab are free simulators — no live IBM calibration API was available. Synthetic values match published IBM Heron-class device ranges.

---

## IonQ health score: composite of SPAM + gate fidelity

**Decision:** IonQ health = 0.5 × SPAM + 0.3 × 1Q fidelity + 0.2 × 2Q fidelity

**Rationale:** IonQ's public API returns only aggregate backend statistics — no per-qubit breakdown. The composite blends all three available fidelity metrics. Weights reflect the relative impact on circuit output quality: SPAM (measurement) is the final error source and highest weight; 1Q gates execute on every qubit and weight more than 2Q; 2Q gates are fewer but higher error.

---

## Four backends: IQM Sirius, IonQ Aria 1, IonQ Aria 2, IBM Boston

**Decision:** IBM Kolkata (synthetic, 27q) replaced with IBM Boston (Heron r3, 156q).

**Rationale:** IBM Kolkata does not exist on Qollab. IBM Boston (Heron r3, 156q) is one of the actual available backends. Values are synthetic but match the published Heron r3 architecture profile.

---

## Hardware run: synchronous, via Qollab's pre-injected backend variable

**Decision:** The script uses `backend.run(qc, shots=1024)` directly — no IonQProvider setup, no API key.

**Rationale:** Qollab pre-creates a `backend` variable in the Python environment based on the user's QPU dropdown selection. `IONQ_API_KEY` is not injected into the environment. `backend.retrieve_job()` fails with HTTP 500 through Qollab's wrapper — results must be retrieved via `cloud.ionq.com/jobs` for real QPU runs.

---

## Pre-run results: hardcoded from real simulator and QPU runs

**Decision:** `PRERUN_RESULTS` contains actual counts from six backends collected on 2026-09-10.

**Rationale:** Hardware jobs are async and the Qollab environment does not support multi-backend execution in a single script run. Pre-run results provide a complete cross-backend comparison without requiring the user to wait or switch backends manually. The IonQ Forte Enterprise QPU counts (`real hw`) are from a real quantum hardware execution.
