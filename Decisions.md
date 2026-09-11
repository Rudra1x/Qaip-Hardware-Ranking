# QAIP Hardware Ranking: Key Design Decisions

A record of the decisions that shaped this project and why we made them.

---

## Qollab is a code playground, not a Jupyter runner

**Decision:** The submission is a single self-contained Python script, not a notebook.

**Why:** Qollab runs Python via WebAssembly (Pyodide) in the browser. There is no file system, no local imports, and no Jupyter runtime. We discovered this mid-build. The `notebook.ipynb` approach was abandoned after testing on the platform. `qollab_project_code.py` embeds all calibration data as Python dicts and inlines all logic with no `from utils import`.

---

## Public / private split

**Decision:** `qollab_project_code.py` and `utils.py` are clean reimplementations that do not import from the private QAIP product.

**Why:** The Qollab submission is pedagogical: the idea, done once, done cleanly. The private QAIP product is the full system. Keeping the two separate means the public code can evolve independently and the private codebase can be refactored freely without breaking the published submission.

Three tests govern every scoping decision: Weekend Test, Textbook Test, Fork Test.

---

## Topology fit uses fixed scores, not dynamic graph computation

**Decision:** Topology fit is a fixed lookup table grounded in published architecture specs, not computed from graph distances.

**Why:** Computing topology fit dynamically requires building the circuit's interaction graph and measuring hardware graph distances. That is routing estimation, which belongs to Track 3 and the private product. Fixed scores based on published hardware architecture literature are appropriate for Track 1 and pass the Textbook Test.

Sources: Xu et al. 2025 (QSteed), ASPLOS 2019 (noise-adaptive mappings), IonQ and IQM architecture documentation.

---

## Calibration data: real IQM and IonQ, synthetic IBM

**Decision:** IQM and IonQ calibration is fetched from real hardware APIs. IBM calibration is synthetic, labeled as such.

**Why:** IQM calibration was available through existing QAIP infrastructure. IonQ calibration was fetched via `api.ionq.co/v0.3/characterizations/backends/{backend}/current` using Qollab API credentials. IBM backends on Qollab are free simulators with no live calibration API. Synthetic IBM values match published Heron-class device ranges.

---

## IonQ health score: composite of SPAM and gate fidelity

**Decision:** IonQ health = 0.5 × SPAM + 0.3 × 1Q fidelity + 0.2 × 2Q fidelity

**Why:** IonQ's public API returns only aggregate backend statistics with no per-qubit breakdown. The composite blends all three available fidelity metrics. Weights reflect relative impact on circuit output quality: SPAM (measurement) is the final error source and gets the highest weight; 1Q gates execute on every qubit and outweigh 2Q; 2Q gates are fewer but individually higher error.

---

## Four backends: IQM Sirius, IonQ Aria 1, IonQ Aria 2, IBM Boston

**Decision:** IBM Kolkata (synthetic, 27q) was replaced with IBM Boston (Heron r3, 156q).

**Why:** IBM Kolkata does not exist on Qollab. IBM Boston (Heron r3, 156q) is one of the actual available backends. Values are synthetic but match the published Heron r3 architecture profile.

---

## Hardware run via Qollab's pre-injected backend variable

**Decision:** The script uses `backend.run(qc, shots=1024)` directly with no IonQProvider setup or API key.

**Why:** Qollab pre-creates a `backend` variable in the Python environment based on the user's QPU dropdown selection. `IONQ_API_KEY` is not injected into the environment. `backend.retrieve_job()` returns HTTP 500 through Qollab's wrapper, so results for real QPU runs must be retrieved separately via `cloud.ionq.com/jobs`.

---

## Pre-run results are hardcoded from real simulator and QPU runs

**Decision:** `PRERUN_RESULTS` contains actual counts from six backends collected on 2026-09-10.

**Why:** Hardware jobs are async and Qollab does not support multi-backend execution in a single script run. Hardcoding pre-run results lets the script show a complete cross-backend comparison without requiring the user to wait or switch backends manually. The IonQ Forte Enterprise QPU counts are from a real quantum hardware execution.
