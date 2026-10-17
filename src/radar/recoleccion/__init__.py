"""Recolectores de publicaciones públicas."""
import re
import json
import sys
import unicodedata


def segundos_iso8601(duracion: str) -> int:
    partes = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", duracion)
    if not partes or not any(p is not None for p in partes.groups()):
        raise ValueError("Duración ISO 8601 inválida")
    return sum(int(p or 0) * factor for p, factor in zip(partes.groups(), (86400, 3600, 60, 1)))


def imprimir_json(publicaciones, metricas):
    # La redirección de stdout en Windows puede seleccionar cp1252.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"publicaciones": [p.model_dump(mode="json") for p in publicaciones],
                      "metricas": [m.model_dump(mode="json") for m in metricas]}, ensure_ascii=False, indent=2))


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


def titulo_publico(titulo, texto, *autores):
    """Título breve anonimizado; si falta, primera línea útil del contenido."""
    for candidato in (titulo or '', texto or ''):
        limpio = texto_publico(candidato, *autores)[0]
        limpio = re.sub(r'(?i)\b(?:https?://|www\.)\S+', '', limpio)
        linea = next((l.strip() for l in limpio.splitlines() if l.strip()), '')
        linea = ' '.join(linea.split())
        if linea:
            if len(linea) > 120:
                corte = linea.rfind(' ', 0, 121)
                linea = linea[:corte] if corte > 0 else ''
            return linea or None
    return None
