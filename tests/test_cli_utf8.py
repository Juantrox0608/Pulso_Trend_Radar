"""La salida redirigida no depende de la página de códigos de Windows."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("modulo,funcion",[("csv_manual","leer_con_metricas"),("youtube","buscar_con_metricas")])
def test_json_redirigido_utf8_con_emoji(tmp_path,modulo,funcion):
    codigo=f'''
import socket
from radar.recoleccion import {modulo} as recolector
def sin_red(*a, **kw):
    raise AssertionError("Red prohibida")
socket.socket.connect = sin_red
class Dato:
    def model_dump(self, **kw):
        return {{"texto": "Educaci\\u00f3n IA \\U0001f916"}}
recolector.{funcion} = lambda *a, **kw: ([Dato()], [])
recolector.main(["ficticio"])
'''
    # Entorno mínimo: sin heredar claves ni leer archivos de configuración.
    entorno={"PYTHONIOENCODING":"cp1252", "PYTHONPATH":str(Path(__file__).resolve().parents[1]/"src")}
    if os.name=="nt":
        entorno["SYSTEMROOT"]=os.environ["SYSTEMROOT"]
    salida=tmp_path/"salida.json"
    with salida.open("wb") as archivo:
        resultado=subprocess.run([sys.executable,"-c",codigo],env=entorno,stdout=archivo,stderr=subprocess.PIPE,timeout=20)
    assert resultado.returncode==0, resultado.stderr.decode("utf-8",errors="replace")
    assert json.loads(salida.read_text(encoding="utf-8"))["publicaciones"][0]["texto"]=="Educación IA 🤖"
