# ChronoTrace — Intelligent Digital Investigation Platform

Processes authorized network activity logs, stores them in MongoDB, represents device
communication as a relationship graph, applies BFS / DFS / Dijkstra / A\*, and scores traffic
with unsupervised anomaly detection — all exposed through a FastAPI REST layer.

Full stack: a Python/FastAPI backend per the
[specification](docs/ChronoTrace_Backend_Network_Updated.md), and a React frontend built to the
[design samples](docs/design-samples).

```
Network activity logs
        │
   Normalizer ──────────────► shared by CSV loader, REST API and live collector
        │
     FastAPI ──► MongoDB ──► NetworkX relationship graph
                    │                 │
                    │        BFS · DFS · Dijkstra · A*
                    │                 │
                    └──► Anomaly detection ──► Investigation results
                                                      │
                                              React frontend
                                    Dashboard · Timeline · Graph · Evidence
                                       Case Manager · Reports · Settings
```

## Repository layout

```
ChronoTrace/
├── backend/     FastAPI · MongoDB · NetworkX · scikit-learn   (Python)
├── frontend/    React · TypeScript · Vite · Tailwind          (Node)
└── docs/        Specification and the original design samples
```

---

## Quick start

Two terminals — backend first, then frontend.

**Backend** (from `backend/`):

```bash
pip install -r requirements.txt
cp .env.example .env                       # then set CHRONOTRACE_MONGO_URI
python scripts/load_dataset.py             # normalize + load the 5,000-row CSV
python -m app.ml.train                     # train the anomaly detector
uvicorn app.main:app --reload              # http://127.0.0.1:8000/docs
```

**Frontend** (from `frontend/`):

```bash
npm install
npm run dev                                # http://localhost:5173
```

The dev server proxies `/api` to the backend, so no CORS setup is needed. Point it elsewhere
with `VITE_API_TARGET`, or set `VITE_API_BASE_URL` to call an absolute URL.

Verify without a database first:

```bash
python scripts/load_dataset.py --dry-run   # validates and profiles the CSV, writes nothing
python -m pytest -q                        # DB-backed tests skip if Mongo is unreachable
```

`GET /health` reports whether MongoDB is connected and whether a model is loaded; the UI
surfaces the same state in its header and on the Settings page.

---

## What the dataset actually contains

The spec's field descriptions are illustrative; these are the measured facts for
`chronotrace_network_5000.csv`, and the code is built against them:

| Property | Value |
|---|---|
| Records | 5,000 — no nulls, no duplicate rows |
| Devices | 125 total; **120 act as a source** |
| Destination-only hosts | `WebServer`, `FileServer`, `DNS`, `BackupServer`, `Mail` — these never initiate |
| Device IDs | Opaque labels (`Comp679356`), **not IP addresses** |
| `SrcPort` | **A string label** (`"Port62917"`) — `DstPort` is a plain integer |
| Protocols | Only 6 (TCP, 4148) and 17 (UDP, 852) |
| Time span | 2024-07-03 → 2024-08-02 (epoch seconds) |
| Total traffic | 80.6 GB across all events |
| Labels | **None** — so anomaly detection is unsupervised, as the spec anticipates |

Two of these drove real design decisions:

- **The `SrcPort` / `DstPort` type mismatch** is reconciled in one place
  ([`parse_port`](backend/app/collector/normalizer.py)), so stored ports are always integers and
  therefore comparable and indexable.
- **The five sink devices** mean the graph is *weakly* but not strongly connected. Path
  queries into a server succeed; queries *out of* one correctly return `found: false`
  rather than an error.

---

## Project layout

```
backend/
├── app/
│   ├── main.py              FastAPI app, lifespan, error handlers
│   ├── config.py            Settings from .env
│   ├── api/                 events · timeline · graph · analysis · investigations
│   ├── database/            connection (async PyMongo) · collections + indexes
│   ├── models/              Pydantic request/response models
│   ├── services/            event_service · graph_service · analysis_service
│   ├── graph/               builder · bfs · dfs · dijkstra · astar
│   ├── ml/                  features · train · predict
│   └── collector/           normalizer (shared) · live collector
├── data/                    chronotrace_network_5000.csv
├── scripts/load_dataset.py  CSV → MongoDB (idempotent)
└── tests/                   176 tests

frontend/
└── src/
    ├── lib/api.ts           Typed client covering every endpoint
    ├── types.ts             Mirrors of the backend Pydantic models
    ├── components/          Layout · ui · Charts · NetworkGraph
    └── pages/               Dashboard · Timeline · GraphView · Evidence
                             CaseManager · Reports · Settings
```

---

## API

Interactive docs at `/docs`. All 25 paths:

**Events** — `POST /events` · `POST /events/bulk` · `GET /events` · `GET /events/{id}` ·
`DELETE /events/{id}`

`GET /events` supports every filter the spec lists, plus a few: `src_device`, `dst_device`,
`device` (either end), `protocol`, `src_port`, `dst_port`, `start_time`, `end_time`,
`min_duration`, `max_duration`, `min_bytes`, `max_bytes`, `source`, `limit`, `skip`,
`sort_by`, `order`.

**Timeline** — `GET /timeline` — bucketed by interval (aggregated in MongoDB) or `raw=true`
for individual events in time order.

**Devices & relationships** — `GET /devices` · `GET /devices/{device}` ·
`GET /relationships/{device}` · `GET /protocols` · `GET /ports`

**Graph** — `POST /graph/bfs` · `POST /graph/dfs` · `POST /graph/dijkstra` ·
`POST /graph/astar` · `GET /graph/stats` · `GET /graph/neighborhood/{device}` ·
`POST /graph/rebuild`

**Analysis** — `POST /analysis` · `GET /analysis` · `GET /analysis/{id}` ·
`GET /analysis/model` · `POST /analysis/model/reload` · `GET /analysis/device/{device}`

**Investigations** — `POST /investigations` · `GET /investigations` ·
`GET /investigations/{id}` · `PATCH /investigations/{id}` · `DELETE /investigations/{id}`

### Examples

```bash
# Traffic from one device
curl "localhost:8000/events?src_device=Comp431255&limit=10"

# Hourly activity for a device
curl "localhost:8000/timeline?device=Comp431255&interval=3600"

# Devices within 2 hops
curl -X POST localhost:8000/graph/bfs \
  -H 'Content-Type: application/json' \
  -d '{"source":"Comp431255","max_depth":2}'

# Strongest communication route, plus 2 alternatives
curl -X POST localhost:8000/graph/dijkstra \
  -H 'Content-Type: application/json' \
  -d '{"source":"Comp431255","target":"DNS","weight":"strength","k":3}'

# Score a slice of traffic
curl -X POST localhost:8000/analysis \
  -H 'Content-Type: application/json' \
  -d '{"limit":2000,"top_n":10}'

# Open a case file on a device
curl -X POST localhost:8000/investigations \
  -H 'Content-Type: application/json' \
  -d '{"device":"Comp431255","depth":2}'
```

---

## Data model

One normalizer ([`backend/app/collector/normalizer.py`](backend/app/collector/normalizer.py)) serves the CSV
loader, the REST API and the live collector, so all three produce identical documents.

```json
{
  "event_id": "evt_d5c7cdd218ddad59",
  "timestamp": 1720001344,
  "event_time": "2024-07-03T10:09:04Z",
  "duration": 10540.0,
  "src_device": "Comp679356",
  "dst_device": "Comp654763",
  "protocol": 6,            "protocol_name": "TCP",
  "src_port": 62917,        "dst_port": 443,      "dst_service": "HTTPS",
  "src_packets": 4636,      "dst_packets": 9480,
  "src_bytes": 3782976,     "dst_bytes": 6948840,
  "total_packets": 14116,   "total_bytes": 10731816,
  "packet_ratio": 0.48903,  "byte_ratio": 0.544404,
  "bytes_per_second": 1018.198861,
  "src_bytes_per_packet": 816.0, "dst_bytes_per_packet": 733.0,
  "source": "dataset"
}
```

**`event_id` is a content hash**, not a counter. That makes ingestion idempotent: re-running
the loader, or a collector re-sending a buffered event, upserts the same document instead of
duplicating it. The raw epoch is kept alongside the derived `event_time`, as the spec requires.

Ratios floor their denominator at 1 rather than returning `null`, because `dst_packets` and
`dst_bytes` are legitimately `0` in this dataset — keeping them numeric means they stay
queryable in Mongo and usable as ML features.

Indexes cover every documented filter: `event_id` (unique), `timestamp`, `(src_device,
timestamp)`, `(dst_device, timestamp)`, `(src_device, dst_device)`, `protocol`, `dst_port`,
`src_port`, `total_bytes`, `duration`.

---

## Relationship graph

Devices are nodes; repeated communication between the same ordered pair folds into **one
aggregated edge** carrying `event_count`, `total_bytes`, `total_packets`, `total_duration`,
`protocols`, `dst_ports`, `first_seen`, `last_seen`, and sample event ids.

Aggregating is what makes edges *weightable* — one edge per event would leave nothing for
Dijkstra to minimise. On this dataset: **125 nodes, 4,242 edges, density 0.27**.

The graph is cached in-process with a TTL and rebuilt on ingestion, guarded by a lock so
concurrent requests don't each trigger their own rebuild.

### Edge weights

Every strategy is **strictly positive** (required for Dijkstra's correctness) and ordered so
that *a stronger relationship is cheaper to traverse* — the lowest-cost path is therefore the
most plausible communication route.

| Strategy | Cost | Meaning |
|---|---|---|
| `hops` | `1` | Fewest intermediaries |
| `frequency` | `1 / event_count` | Frequent contact is close |
| `bytes` | `1 / (1 + log₁₀(1+bytes))` | High-volume links are close |
| `duration` | `1 / (1 + log₁₀(1+avg_duration))` | Long sessions are close |
| `strength` *(default)* | blend of all three | General-purpose relationship strength |

Byte volumes span six orders of magnitude here, hence the log compression.

### Algorithms

All four are implemented directly (NetworkX supplies the graph structure) because the
investigation use case needs more than a yes/no answer — hop levels, discovery trees, visit
order, and expansion counts.

- **BFS** — nodes grouped by hop distance, discovery tree, shortest path to a target, and a
  `truncated` flag so a capped result is never mistaken for a complete neighbourhood.
- **DFS** — iterative (a recursive walk would blow the stack on a large graph); returns the
  discovery chain plus enumerated loop-free routes to a target.
- **Dijkstra** — binary heap, with **Yen's algorithm** for `k` alternative routes. A second,
  slightly costlier path is often the one that explains an observed relationship.
- **A\*** — devices have no coordinates, so the heuristic is
  `h(n) = min_edge_weight × undirected_hop_distance(n, target)`.
  This is **admissible** (undirected hop distance never exceeds the directed one; no edge is
  cheaper than the minimum) and **consistent** (adjacent hop distances differ by ≤ 1), so it
  returns the true optimum and never needs to re-expand a settled node.

**Verified against NetworkX on the real graph:** BFS depths match
`single_source_shortest_path_length` exactly; DFS visits exactly the reachable set; Dijkstra
matches `nx.dijkstra_path_length` across all five weight strategies over 200 random pairs; A\*
returns identical costs to Dijkstra while expanding **81% fewer nodes**.

---

## Anomaly detection

The dataset has **no label column**, so there is nothing for a supervised classifier to learn
"malicious" from. The model is an **IsolationForest** — unsupervised, tolerant of mixed-scale
features, near-linear to score.

**27 features** in two families:

- *Per-event* — duration, protocol, ports, packets, bytes, and the derived ratios, `log1p`-compressed.
- *Per-device context* — communication frequency, distinct destinations, distinct ports, and
  how usual this destination is for this device. A 900 MB transfer is unremarkable for a
  backup server and glaring for a workstation; the context is what makes it a signal.

**Device profiles are persisted with the model**, not recomputed per request. Otherwise an
event's features would depend on the query that retrieved it, and the same event would score
differently in a single-device query than in a full sweep.

### Risk scores are absolute, not ranked

The obvious calibration — percentile rank against training scores — has a serious flaw for an
investigation tool: it forces a *fixed proportion* of every batch into the top band, so a
quiet day looks exactly as alarming as an incident.

Instead the score is anchored to two fixed points of the training distribution: the median
(risk 0) and the 1st percentile (risk 0.9), with the tail beyond compressed exponentially. A
batch of ordinary traffic scores near zero throughout, and ordering is preserved because the
mapping is monotone.

Measured on this dataset — the ~70 injected high-volume transfers serve as a pseudo ground truth:

| Metric | Result |
|---|---|
| ROC AUC | **0.997** |
| PR AUC | 0.853 |
| Recall @ top 100 | 64 / 70 |
| Flagged for review (full dataset) | 90 of 5,000 (1.8%) |
| Flagged for review (outliers removed) | 27 of 4,930 (0.5%) |

That last row is the one that matters: ordinary traffic is *not* mass-flagged.

### Reasons

IsolationForest offers no per-feature attribution, so inventing one would be fiction. Reasons
come from **rule checks against the training percentiles** — a claim that can actually be
checked:

```json
{
  "event_id": "evt_72837d6c66d88d97",
  "risk_score": 0.943,
  "classification": "high_priority",
  "reasons": [
    "High outbound data volume",
    "Unusually large total data transfer",
    "Strongly outbound-skewed byte exchange",
    "Data volume far exceeds this device's usual level"
  ],
  "contributing_features": { "src_bytes_log": 20.52, "byte_ratio_log": 5.13 }
}
```

Bands: `normal` (<0.50) · `low_concern` (<0.75) · `requires_review` (<0.90) · `high_priority` (≥0.90).

**These are indicators, not verdicts.** The model reports statistical unusualness, and unusual
traffic is frequently legitimate. Every band above `normal` means *an analyst should look*,
never *this is an attack*. The wording is deliberate throughout the API.

---

## Frontend

React 18 + TypeScript + Vite + Tailwind, built to the six mockups in
[docs/design-samples](docs/design-samples). Design tokens (colours, type scale, spacing) are
transcribed verbatim from the mockups own Tailwind config into
[`frontend/tailwind.config.js`](frontend/tailwind.config.js), so the app and the samples stay
in sync.

| Page | Backed by |
|---|---|
| **Dashboard** | `/events` · `/graph/stats` · `/protocols` · `/ports` · `/timeline` · `/analysis` |
| **Timeline** | `/timeline` bucketed and raw, with a per-event risk overlay |
| **Graph View** | `/graph/neighborhood` plus all four traversal algorithms |
| **Evidence** | `/events` with every documented filter, sort and pagination |
| **Case Manager** | `/investigations` full CRUD lifecycle |
| **Reports** | Printable report composed from a stored case file |
| **Settings** | `/health` · `/analysis/model` · `/graph/rebuild` |

Every page is driven by live API data — there are no mocked fixtures. Loading, error and
empty states are handled per query, and an API error explains the fix (start the backend,
check the Mongo URI, train the model) rather than just reporting a status code. Cases and
reports are deep-linkable (`/cases/:id`, `/reports?case=:id`).

### Two deliberate departures from the mockups

**The design palette fails colour-vision-deficiency checks.** The samples use Tailwind
500-level blue/purple/emerald/orange/teal/pink; blue↔purple measure ΔE 0.9 under
deuteranopia — effectively identical. The palette was re-stepped and validated: all six sit
inside the dark-mode lightness band and the worst adjacent pair is now ΔE 8.1. The order is
fixed and never cycled, and every chart carries a legend so identity is never colour-alone.

**The mockups describe generic host forensics** (file access, registry, USB devices); this
backend analyses *network activity*. The information architecture is preserved and remapped:
event categories become protocols and services, the alert feed becomes ML-scored events, and
Evidence becomes the network record browser — in this system the network event *is* the
evidence.

### Graph rendering

`d3-force` runs the layout; rendering is plain SVG so nodes carry the rounded-square
treatment and highlight states from the mockup. The simulation runs once per data change and
then stops — a permanently ticking layout burns CPU and makes nodes impossible to click.

This dataset is dense (27% graph density), so the full induced subgraph of a 1-hop
neighbourhood is a hairball of peer-to-peer edges. **Direct links only** is on by default,
showing just the focus device relationships; switch it off to see the peer structure.

---

## Live collector

```bash
python -m app.collector.collector --once
python -m app.collector.collector --interval 10 --api http://127.0.0.1:8000
python -m app.collector.collector --replay data/chronotrace_network_5000.csv
```

Samples the **local host's own connection table** via `psutil` — metadata only, no packet
contents, no probing of other hosts — tracks each connection across samples to measure real
duration, and posts completed connections to `/events/bulk`.

One honest limitation: `psutil` exposes no per-connection byte or packet counters, so those
are apportioned from per-NIC deltas across the sample interval. They are **estimates**, and
every such event is tagged `source: "collector"` so estimated traffic is never confused with
the exact figures from a dataset import.

`--replay` pushes the CSV through the real HTTP ingestion path — an end-to-end test of the
full pipeline.

> Run only on systems you are authorized to monitor.

---

## Testing

```bash
cd backend && python -m pytest -q    # 176 passed against a live MongoDB
python -m pytest -m "not mongo" -q   # skip the DB-backed tests

cd frontend && npm run typecheck     # strict TypeScript, no errors
npm run build                        # production bundle
```

| Area | Coverage |
|---|---|
| Normalizer | Port labels, missing/invalid fields, derived features, zero-denominator cases, id determinism |
| Graph | Cross-validated against NetworkX; weight positivity; admissibility checked against true costs |
| ML | Feature invariance to query slice, calibration monotonicity, detection quality, no mass-flagging |
| Queries | Filter shapes, plus semantic equivalence against an in-memory evaluator on all 5,000 events |
| API | Validation, pagination, filtering, all four algorithms, investigation lifecycle |

DB-backed tests are marked `mongo` and skip cleanly when no server is reachable, so the suite
never reports false failures. Running them against a real MongoDB is what caught the
`aggregate()` await bug described below.

---

## Configuration

All settings take a `CHRONOTRACE_` prefix (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017` | Connection string |
| `MONGO_DB` | `chronotrace` | Database name |
| `GRAPH_CACHE_TTL` | `300` | Seconds before the graph is rebuilt |
| `GRAPH_MAX_EVENTS` | `200000` | Cap on events per graph build |
| `MODEL_PATH` | `app/ml/model.pkl` | Trained model location |
| `CORS_ORIGINS` | `["*"]` | Allowed frontend origins |

---

## Notes on implementation choices

**PyMongo's `AsyncMongoClient`, not Motor.** MongoDB has deprecated Motor in favour of the
driver now built into PyMongo (≥ 4.13). The spec listed either; this is the one with a future.

**A missing database does not stop startup.** The service starts, logs the problem, and
reports it through `/health`, rather than crash-looping. Endpoints that need storage return
503 with an actionable message.

**Analysis endpoints return 503 until a model exists**, with the training command in the
message, rather than failing obscurely at the first request.

---

## Status

Phases 1–9 of the backend spec are implemented, and all six design samples are built.
**176 backend tests pass against a live MongoDB Atlas cluster**, and all seven frontend pages
were verified rendering real data.

Running the DB-backed tests for the first time caught five real bugs: PyMongo async
`aggregate()` returns a *coroutine* (unlike `find()`), so every aggregation pipeline —
timeline buckets, device summaries, relationships, the device list — had to be awaited before
iteration. Those five endpoints were broken; they are now fixed and covered.

### Security note

`backend/.env` holds the MongoDB connection string, including its password. It is gitignored,
and the loader redacts credentials before printing them. If that URI was ever shared outside
a private channel, rotate the database password in Atlas.
