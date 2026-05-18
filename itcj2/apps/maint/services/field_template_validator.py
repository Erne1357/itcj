"""
Validador de field_template para categorías maint.

Función pura: valida estructura y normaliza la lista de campos dinámicos.
No tiene dependencias de BD — es invocable desde cualquier servicio o test.
"""
import re
from fastapi import HTTPException

_VALID_TYPES = {"text", "number", "date", "time", "select"}
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_field_template(fields) -> list[dict]:
    """
    Valida y normaliza una lista de campos dinámicos.

    Reglas:
    - `fields` None o [] es válido → devuelve [] (el service decide si guardar None).
    - Cada item debe ser un dict con:
        - key: str no vacío, regex ^[a-z][a-z0-9_]*$, único en la lista
        - label: str no vacío (tras strip)
        - type: uno de {text, number, date, time, select}
        - required: bool opcional (default False)
        - options: lista de strings no vacíos y únicos — obligatoria si type=='select'
    - Se conservan SOLO las claves conocidas; el resto se descarta.

    Lanza HTTPException(422) con mensaje descriptivo si hay error de validación.
    Devuelve la lista normalizada.
    """
    if fields is None or fields == []:
        return []

    if not isinstance(fields, list):
        raise HTTPException(
            status_code=422,
            detail="field_template debe ser una lista de campos.",
        )

    seen_keys: set[str] = set()
    normalized: list[dict] = []

    for idx, item in enumerate(fields):
        prefix = f"Campo en posición {idx}"

        if not isinstance(item, dict):
            raise HTTPException(
                status_code=422,
                detail=f"{prefix}: se esperaba un objeto (dict), se recibió {type(item).__name__}.",
            )

        # --- key ---
        raw_key = item.get("key")
        if not isinstance(raw_key, str) or not raw_key.strip():
            raise HTTPException(
                status_code=422,
                detail=f"{prefix}: 'key' es obligatorio y debe ser una cadena no vacía.",
            )
        key = raw_key.strip()
        if not _KEY_RE.match(key):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{prefix}: 'key' tiene formato inválido ('{key}'). "
                    "Debe comenzar con letra minúscula y contener solo letras minúsculas, "
                    "dígitos y guiones bajos (^[a-z][a-z0-9_]*$)."
                ),
            )
        if key in seen_keys:
            raise HTTPException(
                status_code=422,
                detail=f"{prefix}: 'key' duplicado ('{key}'). Cada campo debe tener una clave única.",
            )
        seen_keys.add(key)

        # --- label ---
        raw_label = item.get("label")
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise HTTPException(
                status_code=422,
                detail=f"Campo '{key}': 'label' es obligatorio y debe ser una cadena no vacía.",
            )
        label = raw_label.strip()

        # --- type ---
        field_type = item.get("type")
        if field_type not in _VALID_TYPES:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Campo '{key}': 'type' inválido ('{field_type}'). "
                    f"Valores permitidos: {sorted(_VALID_TYPES)}."
                ),
            )

        # --- required ---
        required_raw = item.get("required", False)
        if not isinstance(required_raw, bool):
            raise HTTPException(
                status_code=422,
                detail=f"Campo '{key}': 'required' debe ser booleano (true/false), se recibió {type(required_raw).__name__}.",
            )

        # --- options (solo select) ---
        normalized_item: dict = {
            "key": key,
            "label": label,
            "type": field_type,
            "required": required_raw,
        }

        if field_type == "select":
            options_raw = item.get("options")
            if not isinstance(options_raw, list) or len(options_raw) == 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"Campo '{key}': 'options' es obligatorio para type='select' y debe tener al menos una opción.",
                )
            seen_opts: set[str] = set()
            clean_opts: list[str] = []
            for opt_idx, opt in enumerate(options_raw):
                if not isinstance(opt, str) or not opt.strip():
                    raise HTTPException(
                        status_code=422,
                        detail=f"Campo '{key}', opción {opt_idx}: debe ser una cadena no vacía.",
                    )
                opt_clean = opt.strip()
                if opt_clean in seen_opts:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Campo '{key}': opción duplicada ('{opt_clean}'). Las opciones deben ser únicas.",
                    )
                seen_opts.add(opt_clean)
                clean_opts.append(opt_clean)
            normalized_item["options"] = clean_opts
        else:
            # Descartar 'options' si viene en campos no-select
            pass

        normalized.append(normalized_item)

    return normalized
