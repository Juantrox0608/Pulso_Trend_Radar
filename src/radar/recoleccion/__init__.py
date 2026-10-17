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


def reparar_texto(texto: str) -> str:
    """Repara UTF-8 leído como Windows-1252 conservando mayúsculas y acentos."""
    try:
        return texto.encode("cp1252").decode("utf-8")
    except UnicodeError:
        # Excel también puede mezclar texto correcto y mojibake en una misma celda.
        def reparar_grupo(coincidencia):
            valor = coincidencia.group()
            try:
                return valor.encode("cp1252").decode("utf-8")
            except UnicodeError:
                return valor
        return re.sub(r"[^\x00-\x7f]+", reparar_grupo, texto)


def texto_publico(texto: str, *autores: str) -> tuple[str, tuple[str, ...]]:
    texto = reparar_texto(texto)
    etiquetas = sin_autor(re.findall(r"#(\w+)", texto), *autores)
    texto = re.sub(r"@[\w.\-]+", "@[usuario]", texto)
    for autor in sorted(filter(None, autores), key=len, reverse=True):
        texto = re.sub(r"(?<!\w)" + re.escape(autor) + r"(?!\w)", "[autor]", texto, flags=re.I)
    return texto, etiquetas
