# FPL Team Optimizer

Suggests an optimal Fantasy Premier League squad within a budget, using past
player statistics. Available three ways:

1. **Command line** — `fpl_optimizer.py`
2. **HTTP API** — `api.py` (Python/Flask backend)
3. **iPhone app** — SwiftUI client in `ios/` that talks to the API

---

## 1. Command-line tool

```bash
python3 fpl_optimizer.py
```

Answer the prompts (CSV path, target gameweek, budget, lookback weeks). The
dataset `fpl-data-stats.csv` is found automatically if it's next to the script,
on the Desktop, or in Downloads.

---

## 2. Python backend (API)

The backend reuses the exact same optimizer logic and exposes it over HTTP.

### Setup (one time)

```bash
cd /Users/wangy37/fpl-team-optimizer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Run the server

```bash
.venv/bin/python api.py
```

It serves on `http://0.0.0.0:8000` (reachable at `http://127.0.0.1:8000` on the
Mac, or `http://<your-mac-ip>:8000` from another device on the same Wi-Fi).

### Endpoints

| Method | Path             | Purpose                                       |
|--------|------------------|-----------------------------------------------|
| GET    | `/api/health`    | Status + which dataset file is loaded         |
| GET    | `/api/gameweeks` | Available gameweek range and default values   |
| POST   | `/api/optimize`  | Build a squad (JSON body below)               |

**Optimize request body:**

```json
{ "gameweek": 22, "budget": 100, "lookback": 5 }
```

**Quick test:**

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/gameweeks
curl -s -X POST http://127.0.0.1:8000/api/optimize \
  -H "Content-Type: application/json" \
  -d '{"gameweek":22,"budget":100,"lookback":5}'
```

---

## 3. iPhone app (SwiftUI client)

The Swift source lives in `ios/FPLOptimizer/`. These are plain source files;
you assemble them into an Xcode project once.

### Create the Xcode project

1. Open **Xcode** → **File ▸ New ▸ Project… ▸ iOS ▸ App**.
2. Product Name: `FPLOptimizer`, Interface: **SwiftUI**, Language: **Swift**.
3. Save it anywhere (e.g. inside `ios/`).
4. Delete the auto-generated `ContentView.swift` and `FPLOptimizerApp.swift`.
5. Drag the five files from `ios/FPLOptimizer/` into the project
   (**Copy items if needed** checked):
   - `FPLOptimizerApp.swift`
   - `ContentView.swift`
   - `Models.swift`
   - `APIService.swift`
   - `OptimizerViewModel.swift`

### Allow local HTTP (App Transport Security)

iOS blocks plain `http://` by default. For local testing, add this to the
app target's **Info** tab (or `Info.plist`) so it can reach the dev server:

```xml
<key>NSAppTransportSecurity</key>
<dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
</dict>
```

### Point the app at your server

In `APIService.swift`, set `baseURL`:

- **iOS Simulator** on the same Mac: `http://127.0.0.1:8000`
- **Real iPhone** on the same Wi-Fi: `http://<your-mac-ip>:8000`
  (find the IP with `ipconfig getifaddr en0`)

### Run

1. Start the backend (`.venv/bin/python api.py`).
2. In Xcode press **▶ Run** (choose an iPhone simulator or your device).
3. Adjust gameweek / budget / lookback, tap **Build Optimal Squad**.

---

## How it works (prediction)

For a target gameweek, only data from **earlier gameweeks** is used (no data
leakage). Each player's predicted points come from a recency-weighted average
over the last *N* (lookback) gameweeks, blending actual points with expected
points, scaled by how often they actually started. The squad builder then picks
the highest-value valid 15-player squad within budget and FPL constraints.
