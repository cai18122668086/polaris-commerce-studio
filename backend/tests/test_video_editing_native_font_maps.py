from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTCollection

from app.video_editing_native_font_maps import _font_reader


def face(character: str) -> FontBuilder:
    builder = FontBuilder(1000, isTTF=True)
    names = [".notdef", "marker"]
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({ord(character): "marker"})
    builder.setupGlyf({name: TTGlyphPen(None).glyph() for name in names})
    builder.setupHorizontalMetrics({name: (500, 0) for name in names})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Coverage test", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    return builder


def test_native_coverage_cache_distinguishes_faces_and_font_replacements(
    tmp_path: Path,
) -> None:
    package_fonts = tmp_path / "fonts"
    package_fonts.mkdir()
    path = package_fonts / "coverage.ttc"
    collection = TTCollection()
    collection.fonts = [face("洗").font, face("锅").font]
    collection.save(path)
    reader = _font_reader(package_fonts)

    def coverage(font_path: Path, index: int) -> dict[int, str] | None:
        with reader(str(font_path), fontNumber=index, lazy=True) as font:
            return font.getBestCmap()

    first = coverage(path, 0)
    assert first == {ord("洗"): "marker"}
    assert coverage(path, 0) is first
    assert coverage(path, 1) == {ord("锅"): "marker"}

    outside = tmp_path / "replacement.ttc"
    collection.fonts = [face("碗").font]
    collection.save(outside)
    external = coverage(outside, 0)
    assert external == {ord("碗"): "marker"}
    assert coverage(outside, 0) is not external
    outside.replace(path)
    assert coverage(path, 0) == external
