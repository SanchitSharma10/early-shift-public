# Deploy Public Dashboard

Use the public app entrypoint:

```bash
streamlit run public_lite_dashboard.py
```

The public dashboard is deploy-safe by default:
- if `DB_PATH` is set, it uses that
- otherwise it falls back to `early_shift_demo.db` when available
- if no demo DB exists, it uses `early_shift.db`

## Fastest Hosting Options

### Option 1: Streamlit Community Cloud
Best for a hiring/demo link.

1. Push this repo to GitHub.
2. Open https://share.streamlit.io/
3. Create a new app from your public repo.
4. Set the main file path to `public_lite_dashboard.py`.
5. In app settings, add:
   - `DB_PATH=early_shift_demo.db`
   - `YOUTUBE_API_KEY=...` if you want the live game-check YouTube search enabled

If you skip `YOUTUBE_API_KEY`, the dashboard still loads, but the game-check tool will not return live YouTube coverage.

### Option 2: Render
Best if you want a more product-like hosted link.

This repo now includes [render.yaml](./render.yaml), so Render can auto-detect the setup.

1. Push this repo to GitHub.
2. In Render, choose `New +` -> `Blueprint`.
3. Select the GitHub repo.
4. Confirm the generated service:
   - build command: `pip install -r requirements.txt`
   - start command: `streamlit run public_lite_dashboard.py --server.port $PORT --server.address 0.0.0.0`
5. Add `YOUTUBE_API_KEY` in the Render environment settings if you want live YouTube search.

`DB_PATH=early_shift_demo.db` is already set in the blueprint.

## Recommended First Deploy

For tomorrow morning:
- push the repo
- deploy to Streamlit Community Cloud
- use that link for LinkedIn and outreach

That is the shortest path to a working public artifact.
