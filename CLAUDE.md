# CLAUDE.md – Filmzwilling

Persönliche Film-Empfehlungs-App für eine Person (Florian), lokal laufend. Empfehlungen per
user-based Collaborative Filtering („Geschmackszwillinge“) auf MovieLens 32M, Metadaten und
Streaming-Anbieter (DE) über TMDB. Oberfläche, README und Doku auf Deutsch; Code, Bezeichner und
Commit-Messages auf Englisch.

## Struktur

- `src/filmzwilling/` – Python-Paket
  - `config.py` – Pfade, `.env`, zentrale `RecommenderConfig`-Dataclass (alle CF-Parameter)
  - `scale.py` – Umrechnung Note 0–10 ↔ MovieLens 0,5–5
  - `movielens.py` – Download, MD5-Prüfung, Aufbereitung nach `data/processed/`, Laden
  - `similarity.py` / `recommender.py` / `evaluate.py` – Kernlogik (vektorisiert, scipy.sparse)
  - `db.py` (Verbindung + versionierte Migrationen), `repository.py` (Repository-Schicht)
  - `tmdb.py` (async httpx-Client, Rate-Limit, Retry, Cache), `providers.py`, `matching.py`
  - `importers/` – Netflix, Prime (heuristisch, `header_aliases.py`), generische CSV
  - `abandonment.py`, `rating_queue.py`, `filters.py`, `service.py` (Orchestrierung, Neuberechnung)
  - `synthetic.py` – reproduzierbarer synthetischer Datensatz (Tests und `demo`)
  - `web/` – FastAPI-App, Jinja2-Templates, Vanilla-JS (ES-Module, kein Build), CSS
  - `cli.py` – typer-CLI `filmzwilling`
- `tests/` – pytest; `tests/fixtures/` Mini-Daten; `tests/js/` für `node --test`
- `docs/ENTSCHEIDUNGEN.md` – getroffene Entscheidungen mit Begründung; `docs/BERICHT.md` – Abschlussbericht

## Befehle

```bash
pip install -e ".[dev]"
pytest                      # Standardlauf (ohne slow, e2e, real_data)
pytest -m slow              # Performance
FILMZWILLING_REAL_DATA=1 pytest -m real_data   # echte MovieLens-Daten in ./data
node --test tests/js/
ruff check . && ruff format --check .
mypy src
pytest --cov=filmzwilling --cov-report=term-missing
filmzwilling demo           # App mit synthetischen Daten, ohne Netz
```

## Konventionen

- Daten nur in `./data/` (oder `FILMZWILLING_DATA_DIR`), komplett in `.gitignore`. Niemals
  MovieLens-Dateien, Datenbanken, Exporte oder Tokens committen.
- Tests zuerst; Tests nur ändern, wenn nachweislich falsch (Begründung in `docs/ENTSCHEIDUNGEN.md`).
- Kein Python-Loop über MovieLens-Nutzer; Sparse-Operationen verwenden.
- TMDB-Token optional: ohne `TMDB_READ_TOKEN` Requests ohne Auth-Header senden (Proxy hängt ihn an).
- mypy strict für `scale`, `similarity`, `recommender`; ruff für Lint und Format (Zeilenlänge 100).
- Frontend-Logik ohne DOM-Abhängigkeit in `web/static/js/keys.js` und `queue.js` (mit `node --test` testbar).
