import pytest


@pytest.fixture(autouse=True)
def entorno_sin_red(monkeypatch):
    # Una clave opcional del proceso no debe activar respaldos en las pruebas anteriores.
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    def prohibido(*args, **kwargs):
        pytest.fail('Red prohibida en las pruebas')
    monkeypatch.setattr('socket.socket.connect', prohibido)
    monkeypatch.setattr('socket.create_connection', prohibido)
