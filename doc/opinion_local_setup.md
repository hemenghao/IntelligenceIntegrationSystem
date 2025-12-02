# Running the Opinion pages without an AI API

The Opinion-themed market and intelligence pages can run locally without configuring any AI API or live data backend. The UI will fall back to the bundled demo data so you can open the pages and share a quick preview.

## What works without AI or Mongo
* **Market list, market detail, and opinion feed routes** use the local datasets at `static/data/opinion_topics.json` and `static/data/opinion_demo_feed.json` whenever archive queries fail. The topics file is now populated from the latest `markets_opinion_normalized.json` dump (plus its raw counterpart at `static/data/markets_opinion_raw.json`), so you can preview current markets without any AI analysis or MongoDB.
* The styling, category tabs, headlines, and badges will render identically to the production UI; only the data is mock.

## Prerequisites
* Python 3.10+ (the project targets modern Python 3)
* A virtual environment is recommended so dependencies do not pollute your global site-packages

Install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Tip: If you only want the web preview and do not need crawlers, installing from `requirements.txt` is sufficient.

## Start the web service locally
Run the launcher, which will boot the Flask/Waitress server on port 5000 by default:
```bash
python IntelligenceHubLauncher.py
```
Then open one of these URLs in your browser:
* http://127.0.0.1:5000/opinion/feed — category-filtered intelligence feed (uses demo data offline)
* http://127.0.0.1:5000/markets — market list page styled like Opinion
* http://127.0.0.1:5000/markets/<topic_id> — single market intel stream (e.g., `opinion_1463`)

## Moving to live data later
If you later plug in MongoDB and AI analysis, the same pages will automatically query real intelligence via `OpinionFeedService`; no template changes are needed.
