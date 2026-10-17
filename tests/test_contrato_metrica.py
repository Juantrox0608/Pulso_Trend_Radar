from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from radar.contrato import Metrica


def datos(**cambios):
    return dict(publicacion_id="yt:vid_test01A", capturada_en="2026-01-02T10:00:00-05:00",
                vistas=0, origen="api_oficial") | cambios


def test_cero_vacio_utc_json():
    m = Metrica(**datos())
    assert m.vistas == 0 and m.likes is None and m.compartidos is None
    assert m.capturada_en == datetime(2026, 1, 2, 15, tzinfo=timezone.utc)
    assert Metrica.model_validate_json(m.model_dump_json()) == m
    assert m.schema_version == "1.0"
    with pytest.raises(ValidationError):
        m.vistas = 3


@pytest.mark.parametrize("cambios", [dict(vistas=None), dict(vistas=-1), dict(likes=-1),
    dict(comentarios=1.5), dict(compartidos=True), dict(vistas="3"),
    dict(capturada_en="2026-01-02T10:00:00"), dict(publicacion_id="otro:123"),
    dict(origen="inventado"), dict(nombre="dato_privado")])
def test_rechaza_datos_invalidos(cambios):
    with pytest.raises(ValidationError):
        Metrica(**datos(**cambios))


@pytest.mark.parametrize("identificador", ["tt:1234567890123456789", "li:lnkd-p-ABcd1234"])
def test_ids_otras_plataformas(identificador):
    assert Metrica(**datos(publicacion_id=identificador)).publicacion_id == identificador
