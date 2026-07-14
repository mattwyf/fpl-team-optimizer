# FPL Team Optimizer

Suggests an optimal Fantasy Premier League squad within a budget, using past
player statistics. Available four ways:

1. **Web app** — `app.py` (Streamlit, deployable to the cloud)
2. **Command line** — `fpl_optimizer.py`
3. **HTTP API** — `api.py` (Python/Flask backend)
4. **iPhone app** — SwiftUI client in `ios/` that talks to the API

---

## Web app (Streamlit)

### Run locally

```bash
.venv/bin/streamlit run app.py
```

The bundled `fpl-data-stats.csv` is loaded automatically; you can also upload
a different CSV in the sidebar.

### Deploy to the internet (free, via Streamlit Community Cloud)

1. Push this repository to GitHub (public repo):

   ```bash
   git remote add origin https://github.com/<your-username>/fpl-team-optimizer.git
   git push -u origin main
   ```

2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub.
3. Click **Create app**, pick this repository, branch `main`, main file `app.py`.
4. Click **Deploy**. You'll get a permanent public URL like
   `https://<your-app-name>.streamlit.app` that works on any device.

Pushing new commits to `main` redeploys the app automatically.

---

## 1. Command-line tool

```bash
python3 fpl_optimizer.py
```

Answer the prompts (CSV path, target gameweek, budget, lookback weeks). The
dataset `fpl-data-stats.csv` is found automatically if it's next to the script,
on the Desktop, or in Downloads.

---

