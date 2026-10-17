"""Recolectores de publicaciones públicas."""
import re
import unicodedata


def _clave(valor: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", valor.casefold())
    return re.sub(r"[\W_]+", "", "".join(c for c in sin_acentos if not unicodedata.combining(c)))


def sin_autor(etiquetas, *autores: str) -> tuple[str, ...]:
    """Quita las etiquetas que son el nombre o usuario del autor: no guardamos quién publicó."""
    # shortcut: solo coincidencia exacta (#AnaPerez); variantes como #AnaPerezIA pasan, revisar si aparecen.
    prohibidas = {_clave(a) for a in autores if a and _clave(a)}
    return tuple(e for e in etiquetas if _clave(e) not in prohibidas)
