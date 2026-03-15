# Early Shift Public

Public demo of Early Shift, a Roblox creator-intelligence system.

This repo is intentionally scoped as a public proof layer:
- hosted lite dashboard
- demo DuckDB snapshot
- case study
- game-check workflow

The full product version is kept separate and includes additional analytics, pipeline logic, and private product-facing tooling.

## What It Shows

Early Shift combines Roblox CCU data with recent YouTube creator coverage to answer three practical questions:
- Which creators repeatedly show up before lift?
- Which spikes look durable versus temporary?
- Does a specific Roblox game have real momentum right now?

The public dashboard is designed for fast comprehension, not full internal depth.

## Included Files

- [public_lite_dashboard.py](./public_lite_dashboard.py): public Streamlit app
- [public_app_helpers.py](./public_app_helpers.py): query and presentation helpers
- [check_my_game.py](./check_my_game.py): CCU + YouTube game check logic
- [CASE_STUDY.md](./CASE_STUDY.md): proof-oriented snapshot
- `early_shift_demo.db`: demo data snapshot for hosting

## Local Run

```bash
pip install -r requirements.txt
streamlit run public_lite_dashboard.py
```

If you want live YouTube search in the game-check tool, set:

```bash
YOUTUBE_API_KEY=your-key
```

## Hosting

See [DEPLOY_PUBLIC_DASHBOARD.md](./DEPLOY_PUBLIC_DASHBOARD.md).

The fastest path is Streamlit Community Cloud. Render is also configured via [render.yaml](./render.yaml).

## Positioning

This repo is not meant to prove every internal detail of the product. It is meant to prove one thing clearly:

Early Shift produces creator-linked Roblox growth signals that are worth looking at.
