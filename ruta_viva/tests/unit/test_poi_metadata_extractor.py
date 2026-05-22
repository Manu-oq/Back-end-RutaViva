from __future__ import annotations

from app.services.poi_metadata_extractor import (
    ExtractedMetadata,
    _format_time,
    _weekday_range,
    clean_text,
    extract_description,
    extract_metadata_from_text,
    extract_opening_hours_text,
    html_to_text,
    infer_access_from_text,
    infer_services_from_text,
    parse_opening_hours_text,
)


class TestCleanText:
    def test_none_returns_none(self) -> None:
        assert clean_text(None) is None

    def test_whitespace_only_returns_none(self) -> None:
        assert clean_text("   \t\n  ") is None

    def test_normal_text_trimmed(self) -> None:
        assert clean_text("  hello world  ") == "hello world"

    def test_collapses_whitespace(self) -> None:
        assert clean_text("hello   world") == "hello world"

    def test_empty_string_returns_none(self) -> None:
        assert clean_text("") is None


class TestHtmlToText:
    def test_strips_html_tags(self) -> None:
        assert html_to_text("<p>Hello</p>") == "Hello"

    def test_strips_script_content(self) -> None:
        result = html_to_text("<script>var x = 1;</script><p>Hello</p>")
        assert "var x" not in result
        assert "Hello" in result

    def test_strips_style_content(self) -> None:
        result = html_to_text("<style>body{}</style><p>Hello</p>")
        assert "body" not in result
        assert "Hello" in result

    def test_preserves_text(self) -> None:
        assert html_to_text("Plain text") == "Plain text"


class TestExtractOpeningHoursText:
    def test_extracts_spanish_hours(self) -> None:
        text = "Horario de atención lunes a viernes 09:00 a 18:00"
        result = extract_opening_hours_text(text)
        assert result is not None
        assert "09:00" in result

    def test_no_hours_returns_none(self) -> None:
        text = "Un lugar hermoso en la montaña"
        assert extract_opening_hours_text(text) is None


class TestParseOpeningHoursText:
    def test_lunes_a_viernes(self) -> None:
        result = parse_opening_hours_text("lunes a viernes 09:00 a 18:00")
        assert len(result) > 0
        assert any(result.get(day) for day in ("mon", "tue", "wed", "thu", "fri"))

    def test_cerrado(self) -> None:
        result = parse_opening_hours_text("lunes a viernes 09:00 a 18:00; sábado cerrado")
        assert result.get("sat") == []

    def test_none_input(self) -> None:
        assert parse_opening_hours_text(None) == {}

    def test_empty_input(self) -> None:
        assert parse_opening_hours_text("") == {}


class TestExtractDescription:
    def test_extracts_long_sentences(self) -> None:
        text = "Este es un lugar maravilloso ubicado en la cordillera de los Andes con vistas impresionantes. Tiene senderos señalizados."
        result = extract_description(text, "Test POI")
        assert result is not None
        assert "maravilloso" in result

    def test_filters_short_sentences(self) -> None:
        text = "Corto. Muy corto también. Pero esta es una frase suficientemente larga como para ser considerada una descripción válida del lugar."
        result = extract_description(text, "Test POI")
        assert result is not None

    def test_filters_cookie_notices(self) -> None:
        text = "Este sitio web utiliza cookies para mejorar su experiencia. Este es un parque nacional con senderos increíbles para toda la familia disfrutar."
        result = extract_description(text, "Test POI")
        assert "cookies" not in (result or "").lower()

    def test_none_input(self) -> None:
        assert extract_description("   ", "Test POI") is None


class TestInferServicesFromText:
    def test_bathrooms_confirmed(self) -> None:
        result = infer_services_from_text("El lugar cuenta con baños públicos")
        assert result["bathrooms"]["evidence_level"] == "confirmed"

    def test_parking_confirmed(self) -> None:
        result = infer_services_from_text("Hay estacionamiento gratuito")
        assert result["parking"]["evidence_level"] == "confirmed"

    def test_family_friendly_inferred(self) -> None:
        result = infer_services_from_text("Cuenta con juegos infantiles para los más pequeños")
        assert result["family_friendly"]["evidence_level"] == "inferred"

    def test_no_services_unknown(self) -> None:
        result = infer_services_from_text("Un mirador en la montaña")
        assert result["bathrooms"]["evidence_level"] == "unknown"
        assert result["parking"]["evidence_level"] == "unknown"


class TestInferAccessFromText:
    def test_ripio_gravel(self) -> None:
        result = infer_access_from_text("Camino de ripio los últimos 5 km")
        assert result["road_type"]["value"] == "gravel"
        assert result["road_type"]["evidence_level"] == "confirmed"

    def test_asfalto_paved(self) -> None:
        result = infer_access_from_text("Camino de asfalto hasta la entrada")
        assert result["road_type"]["value"] == "paved"
        assert result["road_type"]["evidence_level"] == "confirmed"

    def test_no_info_unknown(self) -> None:
        result = infer_access_from_text("Un lugar hermoso")
        assert result["road_type"]["value"] == "unknown"
        assert result["road_type"]["evidence_level"] == "unknown"

    def test_vehicle_recommended_confirmed(self) -> None:
        result = infer_access_from_text("Vehículo recomendado para el acceso")
        assert result["vehicle_recommended"]["evidence_level"] == "confirmed"


class TestExtractMetadataFromText:
    def test_end_to_end(self) -> None:
        text = (
            "Parque Nacional con senderos señalizados y baños públicos. "
            "Horario de atención lunes a viernes 09:00 a 18:00. "
            "Camino de ripio los últimos 3 km, vehículo recomendado."
        )
        result = extract_metadata_from_text(
            poi_name="Parque Nacional",
            category_ids=[10],
            raw_text=text,
            source_url="https://example.com",
        )
        assert isinstance(result, ExtractedMetadata)
        assert result.description is not None
        assert result.opening_hours_structured != {}
        assert result.services["bathrooms"]["evidence_level"] == "confirmed"
        assert result.access["road_type"]["value"] == "gravel"
        assert len(result.evidence) > 0

    def test_no_relevant_info(self) -> None:
        text = "Hola mundo"
        result = extract_metadata_from_text(
            poi_name="Test",
            category_ids=[1],
            raw_text=text,
        )
        assert result.description is None
        assert result.opening_hours_text is None


class TestFormatTime:
    def test_pm_conversion(self) -> None:
        assert _format_time("3", "00", "pm") == "15:00"

    def test_am_noon(self) -> None:
        assert _format_time("12", "00", "am") == "00:00"

    def test_pm_noon(self) -> None:
        assert _format_time("12", "00", "pm") == "12:00"

    def test_am_morning(self) -> None:
        assert _format_time("9", "30", "am") == "09:30"

    def test_no_meridiem(self) -> None:
        assert _format_time("9", "30", None) == "09:30"

    def test_no_minutes(self) -> None:
        assert _format_time("9", None, "am") == "09:00"

    def test_invalid_hour(self) -> None:
        assert _format_time("25", "00", None) is None

    def test_invalid_minute(self) -> None:
        assert _format_time("9", "99", None) is None


class TestWeekdayRange:
    def test_mon_to_fri(self) -> None:
        result = _weekday_range("mon", "fri")
        assert result == ["mon", "tue", "wed", "thu", "fri"]

    def test_mon_to_sun(self) -> None:
        result = _weekday_range("mon", "sun")
        assert result == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

    def test_fri_to_tue_wraps(self) -> None:
        result = _weekday_range("fri", "tue")
        assert result == ["fri", "sat", "sun", "mon", "tue"]

    def test_single_day(self) -> None:
        result = _weekday_range("wed", "wed")
        assert result == ["wed"]
