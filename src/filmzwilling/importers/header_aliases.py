"""Header name variants (English and German) for heuristic CSV/JSON column detection.

Headers are compared after `normalize_header`: lowercase, umlauts transliterated and every
non-alphanumeric character removed ("Date Watched" -> "datewatched").
"""

from __future__ import annotations

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "title": (
        "title",
        "titel",
        "name",
        "titlename",
        "videotitle",
        "contenttitle",
        "programtitle",
        "movietitle",
        "filmtitel",
        "titeldesvideos",
        "seriesormovietitle",
        "asintitle",
    ),
    "date": (
        "date",
        "datum",
        "datewatched",
        "watchdate",
        "watched",
        "watchedat",
        "lastwatched",
        "playbackstarttime",
        "playbackstart",
        "starttime",
        "startzeit",
        "startdatum",
        "zeitpunkt",
        "timestamp",
        "eventtime",
        "eventtimestamp",
        "viewdate",
        "vieweddate",
        "angesehenam",
        "gesehenam",
        "wiedergabedatum",
        "datetimeutc",
        "utctimestamp",
    ),
    "profile": (
        "profile",
        "profil",
        "profilename",
        "profilname",
        "profileid",
        "user",
        "username",
        "benutzer",
        "benutzername",
        "viewer",
    ),
    "duration": (
        "duration",
        "dauer",
        "watchduration",
        "playbackduration",
        "durationseconds",
        "secondsviewed",
        "secondswatched",
        "watchtime",
        "viewingduration",
        "sehdauer",
        "wiedergabedauer",
        "angesehenedauer",
        "durationms",
        "durationmillis",
        "playbackdurationms",
        "minuteswatched",
    ),
    "position": (
        "position",
        "bookmark",
        "playbackposition",
        "lastposition",
        "resumeposition",
        "offset",
        "offsetseconds",
        "positionseconds",
        "wiedergabeposition",
        "fortschritt",
        "positionms",
    ),
    "kind": (
        "type",
        "typ",
        "contenttype",
        "videotype",
        "mediatype",
        "inhaltstyp",
        "kategorie",
        "category",
    ),
    "episode": (
        "episodetitle",
        "episode",
        "folge",
        "folgentitel",
        "episodename",
        "season",
        "staffel",
        "seasonnumber",
        "episodenumber",
    ),
    "year": ("year", "jahr", "releaseyear", "erscheinungsjahr"),
}

# Values of the "kind" column that mean "this row is a series episode".
EPISODE_KIND_VALUES: tuple[str, ...] = (
    "episode",
    "folge",
    "series",
    "serie",
    "tv",
    "tvshow",
    "tvepisode",
    "show",
    "season",
    "staffel",
)

# Values of the "kind" column that mean "this row is a movie".
MOVIE_KIND_VALUES: tuple[str, ...] = ("movie", "film", "feature", "spielfilm")

# Header hints for numeric units.
MILLISECOND_HINTS: tuple[str, ...] = ("ms", "millis", "milliseconds", "millisekunden")
MINUTE_HINTS: tuple[str, ...] = ("minutes", "minuten", "mins")


def normalize_header(header: str) -> str:
    """Normalise a header for alias lookup."""
    raise NotImplementedError
