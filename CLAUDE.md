# CLAUDE.md für Filmzwilling

Persönliche Film-Empfehlungs-App für eine Person (Florian), läuft lokal. Empfehlungen per
user-based Collaborative Filtering („Geschmackszwillinge“) auf MovieLens 32M, Metadaten und
Streaming-Anbieter für Deutschland über TMDB. Oberfläche, README und Doku auf Deutsch; Code,
Bezeichner und Commit-Messages auf Englisch.

## Struktur

```
src/filmzwilling/
  config.py         Pfade, .env, RecommenderConfig (alle CF-Parameter an einer Stelle)
  scale.py          Note 0 bis 10 <-> MovieLens 0,5 bis 5 (mypy strict)
  movielens.py      Download, MD5, Aufbereitung nach data/processed/, load_processed
  similarity.py     angepasste Kosinus-Ähnlichkeit, Sparse-Matvecs (mypy strict)
  recommender.py    k-Nachbarschaft pro Film über CSC, Schrumpfung (mypy strict)
  evaluate.py       Hold-out und k-fache Kreuzvalidierung gegen Filmdurchschnitt
  db.py             sqlite3, Migrationen über PRAGMA user_version
  repository.py     alle SQL-Zugriffe
  tmdb.py           async httpx-Client: Rate-Limit, Retry, Cache (Tabelle tmdb_cache)
  providers.py      "meine Anbieter" über Namen, nie über feste IDs
  matching.py       Importtitel -> TMDB (rapidfuzz) -> MovieLens
  importers/        netflix.py, prime.py (header_aliases.py), generic_csv.py, common.py
  abandonment.py    Abbruch-Erkennung, Hinweistexte
  rating_queue.py   Warteschlange (Quellen 1 bis 4, Später, Fortschritt)
  filters.py        Filter und Sortierung der Empfehlungen, URL-Parameter
  service.py        FilmService: verbindet alles, Hintergrund-Neuberechnung, Dedup per client_id
  synthetic.py      synthetische Cluster-Daten (Tests und demo), demo.py baut den Demo-Ordner
  web/app.py        FastAPI-Seiten und JSON-API; templates/, static/js/, static/css/
  cli.py            typer-CLI "filmzwilling"
tests/              pytest; fixtures/ (Mini-MovieLens, Exporte, TMDB-JSON); js/ für node --test
docs/               ENTSCHEIDUNGEN.md (Entscheidungen mit Begründung), BERICHT.md (Stand)
```

Datenfluss: `setup` schreibt `data/processed/` und trägt alle MovieLens-Filme in die Tabelle
`films` ein. Importe schreiben `watch_events`, die Zuordnung setzt dort tmdb_id und
movielens_id. Bewertungen hängen an `films.id`. `FilmService.recompute()` speichert
`recommendations` und `twins`; Ausschlüsse (bewertet, kein Interesse) gelten erst bei der Abfrage.

## Befehle

```bash
pip install -e ".[dev]"
pytest                                          # Standardlauf (ohne slow, e2e, real_data)
pytest -m slow                                  # Performance
pytest -m e2e                                   # braucht Playwright für Node
FILMZWILLING_REAL_DATA=1 pytest -m real_data -s # echte Daten in ./data
node --test tests/js/
ruff check . && ruff format --check .
mypy src                                        # oder python -m mypy src (globales mypy sieht die Pakete nicht)
pytest --cov=filmzwilling --cov-report=term-missing
filmzwilling demo                               # App mit synthetischen Daten, ohne Netz
```

## Konventionen

- Daten nur in `./data/` (oder `FILMZWILLING_DATA_DIR`), komplett in `.gitignore`. Niemals
  MovieLens-Dateien, Datenbanken, Exporte oder Tokens committen.
- Tests zuerst. Tests nur ändern, wenn sie nachweislich falsch sind; Begründung in
  `docs/ENTSCHEIDUNGEN.md` und in der Commit-Message.
- Keine Python-Schleife über MovieLens-Nutzer oder -Filme; scipy.sparse und numpy benutzen.
- TMDB-Token ist optional: ohne `TMDB_READ_TOKEN` gehen Requests ohne Auth-Header raus (ein Proxy
  kann ihn anhängen). Erst ein 401 führt zur deutschen Fehlermeldung.
- `FILMZWILLING_OFFLINE=1` schaltet TMDB ab; Demo-Ordner sind immer offline.
- Frontend-Logik ohne DOM in `web/static/js/keys.js` und `queue.js`, mit `node --test` getestet.
  Keine npm-Abhängigkeiten, kein Build-Schritt.
- ruff (Zeilenlänge 100) und mypy müssen sauber bleiben, Coverage mindestens 90 %.

## Stand

Alles aus dem Auftrag ist umgesetzt, siehe `docs/BERICHT.md`. Offen ist nur die Live-Prüfung
gegen TMDB (in der Cloud-Umgebung gab es keinen Token). Der MovieLens-Download scheitert mit
aktuellen Zertifikatslisten, siehe `docs/ENTSCHEIDUNGEN.md`.
