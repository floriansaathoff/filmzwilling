from __future__ import annotations

from filmzwilling.genres import german_genres
from filmzwilling.placeholder import placeholder_svg


def test_german_genres() -> None:
    assert german_genres(["Comedy", "Sci-Fi", "IMAX", "Children"]) == [
        "Komödie",
        "Science Fiction",
        "Familie",
    ]
    assert german_genres(["Film-Noir", "Crime"]) == ["Krimi"]
    assert german_genres(["Unbekannt"]) == ["Unbekannt"]
    assert german_genres([]) == []


def test_placeholder_svg() -> None:
    svg = placeholder_svg("Der <Pate> & Co", 1972)
    assert svg.startswith("<svg")
    assert "Der &lt;Pate&gt; &amp; Co" in svg
    assert "1972" in svg
    long = placeholder_svg(
        "Ein sehr langer Filmtitel, der umgebrochen werden muss, weil er so lang ist"
    )
    assert long.count("<tspan") >= 2
    assert placeholder_svg("A") != placeholder_svg("B")


def test_version() -> None:
    import filmzwilling

    assert filmzwilling.__version__
