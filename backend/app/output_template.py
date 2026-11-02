import re


DEFAULT_OUTPUT_TEMPLATE = "{title} - {id}"
_ALLOWED_FIELDS = {
    "{title}": "%(title).160B",
    "{id}": "%(id)s",
    "{uploader}": "%(uploader).80B",
}
_FIELD_PATTERN = re.compile(r"\{[^{}]*\}")
_INVALID_FILENAME_CHARACTERS = set('<>:"/\\|?*')
_WINDOWS_RESERVED_NAMES = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE)


def validate_output_name(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("O nome do arquivo deve ser um texto.")
    name = value.strip()
    if not name:
        return None
    if len(name) > 120:
        raise ValueError("O nome do arquivo deve ter até 120 caracteres.")
    if (
        any(ord(character) < 32 or character in _INVALID_FILENAME_CHARACTERS for character in name)
        or "%" in name
        or ".." in name
        or name.endswith((".", " "))
    ):
        raise ValueError("Use um nome simples, sem caminhos ou caracteres inválidos.")
    if _WINDOWS_RESERVED_NAMES.match(name):
        raise ValueError("Esse nome é reservado pelo Windows. Escolha outro.")
    return name


def validate_output_template(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError("Informe um padrão de nome com até 160 caracteres.")
    template = value.strip()
    if any(ord(character) < 32 or character in _INVALID_FILENAME_CHARACTERS for character in template):
        raise ValueError("O padrão não pode conter separadores ou caracteres inválidos.")
    if ".." in template:
        raise ValueError("O padrão não pode conter segmentos de caminho.")
    fields = _FIELD_PATTERN.findall(template)
    if any(field not in _ALLOWED_FIELDS for field in fields):
        raise ValueError("Use somente os campos {title}, {id} e {uploader}.")
    if "{title}" not in fields:
        raise ValueError("O padrão deve incluir o campo {title}.")
    if "{" in _FIELD_PATTERN.sub("", template) or "}" in _FIELD_PATTERN.sub("", template):
        raise ValueError("O padrão contém chaves sem correspondência.")
    return template


def to_yt_dlp_template(value: str, output_name: str | None = None) -> str:
    validated_name = validate_output_name(output_name)
    if validated_name is not None:
        return f"{validated_name}.%(ext)s"
    validated = validate_output_template(value)
    for field, replacement in _ALLOWED_FIELDS.items():
        validated = validated.replace(field, replacement)
    return f"{validated}.%(ext)s"
