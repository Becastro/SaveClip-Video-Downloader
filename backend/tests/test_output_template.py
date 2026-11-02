import pytest

from app.output_template import (
    to_yt_dlp_template,
    validate_output_name,
    validate_output_template,
)


@pytest.mark.parametrize(
    "template",
    ["../{title}", "folder/{title}", r"folder\\{title}", "{unknown}", "{id}", ""],
)
def test_output_template_rejects_paths_unknown_fields_or_missing_title(template):
    with pytest.raises(ValueError):
        validate_output_template(template)


def test_output_template_is_converted_to_yt_dlp_syntax():
    assert to_yt_dlp_template("{uploader} - {title} ({id})") == (
        "%(uploader).80B - %(title).160B (%(id)s).%(ext)s"
    )


@pytest.mark.parametrize(
    "name",
    ["../video", r"folder\\video", "bad:name", "bad%name", "CON", "name.", "x" * 121],
)
def test_custom_output_name_rejects_paths_and_unsafe_names(name):
    with pytest.raises(ValueError):
        validate_output_name(name)


def test_custom_output_name_is_trimmed_and_used_without_changing_extension():
    assert validate_output_name("  Minha aula  ") == "Minha aula"
    assert to_yt_dlp_template("{title} - {id}", "Minha aula") == (
        "Minha aula.%(ext)s"
    )
