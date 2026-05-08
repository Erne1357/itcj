"""Tests para itcj2.apps.maint.utils.location_parser.parse_building."""
import pytest

from itcj2.apps.maint.utils.location_parser import parse_building


class TestParseBuilding:
    @pytest.mark.parametrize("raw,expected", [
        ("Edificio A", "Edificio A"),
        ("edificio b - planta baja", "Edificio B"),
        ("Edif C, segundo piso", "Edif C"),
        ("Lab 5", "Lab 5"),
        ("LAB 12 - Sistemas", "Lab 12"),
        ("Aula 203", "Aula 203"),
        ("aula  7", "Aula  7"),  # parser preserva espacios internos
        ("Sala B", "Sala B"),
        ("Taller Mecánica", "Taller Mecánica"),
        ("Salon 4", "Salon 4"),
        ("Salón 9", "Salón 9"),
        ("Biblioteca central", "Biblioteca"),
        ("Oficina 12 - Tesorería", "Oficina 12"),
    ])
    def test_known_patterns(self, raw, expected):
        result = parse_building(raw)
        assert result == expected, f"parse_building({raw!r}) = {result!r}"

    def test_none_returns_unclassified(self):
        assert parse_building(None) == "Sin clasificar"

    def test_empty_returns_unclassified(self):
        assert parse_building("") == "Sin clasificar"
        assert parse_building("   ") == "Sin clasificar"

    def test_unmatched_returns_unclassified(self):
        assert parse_building("Pasillo principal") == "Sin clasificar"
        assert parse_building("Cancha de fútbol") == "Sin clasificar"
        assert parse_building("123 Calle Falsa") == "Sin clasificar"

    def test_case_insensitive(self):
        assert parse_building("EDIFICIO X") == "Edificio X"
        assert parse_building("edificio y") == "Edificio Y"

    def test_strips_surrounding_text(self):
        # parser anchors at start of string after trim — text after match ignored
        assert parse_building("Lab 1 — entrada lateral") == "Lab 1"
