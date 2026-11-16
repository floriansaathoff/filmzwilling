"""MovieLens genre names mapped to TMDB's German genre names."""

from __future__ import annotations

ML_TO_GERMAN: dict[str, str] = {
    "Action": "Action",
    "Adventure": "Abenteuer",
    "Animation": "Animation",
    "Children": "Familie",
    "Comedy": "Komödie",
    "Crime": "Krimi",
    "Documentary": "Dokumentarfilm",
    "Drama": "Drama",
    "Fantasy": "Fantasy",
    "Film-Noir": "Krimi",
    "Horror": "Horror",
    "IMAX": "",
    "Musical": "Musik",
    "Mystery": "Mystery",
    "Romance": "Liebesfilm",
    "Sci-Fi": "Science Fiction",
    "Thriller": "Thriller",
    "War": "Kriegsfilm",
    "Western": "Western",
    "(no genres listed)": "",
}


def german_genres(ml_genres: list[str]) -> list[str]:
    """Translate MovieLens genres; unknown names pass through, duplicates and blanks vanish."""
    result: list[str] = []
    for genre in ml_genres:
        name = ML_TO_GERMAN.get(genre, genre)
        if name and name not in result:
            result.append(name)
    return result
