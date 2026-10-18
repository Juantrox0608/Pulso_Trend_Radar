"""Presupuesto local conservador para búsquedas pagas, sin guardar consultas ni claves."""
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError


class LimiteBusqueda(ValueError):
    """No se deben iniciar más búsquedas pagas en esta corrida."""


def _dinero(valor):
    try:
        numero = Decimal(str(valor))
        if not numero.is_finite() or numero < 0:
            raise ValueError()
        return numero
    except (InvalidOperation, ValueError):
        raise ValueError('Importe de presupuesto inválido') from None


class PresupuestoBusqueda:
    def __init__(self, ruta='data/raw/openrouter_busqueda_gasto.json', *, diario='0.25',
                 reserva='0.05', maximo=5, reloj=None):
        self.ruta = Path(ruta)
        self.diario, self.reserva = _dinero(diario), _dinero(reserva)
        if not 0 < self.reserva <= self.diario <= 10 or type(maximo) is not int or not 1 <= maximo <= 20:
            raise ValueError('Presupuesto: reserva positiva hasta el límite diario (máximo USD 10) y 1–20 llamadas')
        self.maximo, self.intentos, self.detenido = maximo, 0, False
        self.reloj = reloj or (lambda:datetime.now(timezone.utc))

    @classmethod
    def desde_entorno(cls):
        try:
            return cls(diario=os.environ.get('OPENROUTER_BUSQUEDA_DIARIO_USD', '0.25'),
                maximo=int(os.environ.get('OPENROUTER_BUSQUEDA_MAX_LLAMADAS', '5')))
        except ValueError:
            raise ValueError('Revisa OPENROUTER_BUSQUEDA_DIARIO_USD y OPENROUTER_BUSQUEDA_MAX_LLAMADAS') from None

    def _leer(self, dia):
        try:
            datos = json.loads(self.ruta.read_text(encoding='utf-8'))
            datetime.strptime(datos['dia'], '%Y-%m-%d')
            usado = _dinero(datos['usado_usd'])
            return usado if datos['dia'] == dia else Decimal('0')
        except FileNotFoundError:
            return Decimal('0')
        except (ValueError, KeyError, TypeError):
            raise ValueError('No se pudo validar el registro de gasto; no se harán búsquedas') from None

    def _guardar(self, dia, usado):
        temporal = self.ruta.with_suffix('.tmp')
        temporal.write_text(json.dumps({'dia':dia, 'usado_usd':str(usado)}), encoding='utf-8')
        temporal.replace(self.ruta)

    def llamar(self, request, pedir):
        if self.detenido:
            raise LimiteBusqueda('Búsquedas pagas detenidas por cuota, saldo o costo no confirmado')
        if self.intentos >= self.maximo:
            raise LimiteBusqueda('Tope de búsquedas pagas por corrida alcanzado')
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        bloqueo = self.ruta.with_suffix('.lock')
        try:
            exclusivo = bloqueo.open('x', encoding='ascii')
        except FileExistsError:
            raise LimiteBusqueda('Registro de gasto en uso; no se inicia otra búsqueda paga') from None
        try:
            dia = self.reloj().astimezone(timezone.utc).date().isoformat()
            usado = self._leer(dia)
            if usado + self.reserva > self.diario:
                raise LimiteBusqueda('Presupuesto diario de búsqueda agotado o insuficiente para reservar otra llamada')
            # Reservar ANTES: un timeout o una caída del proceso también pueden haber generado cargos.
            self._guardar(dia, usado + self.reserva)
            self.intentos += 1
            try:
                respuesta = pedir(request)
                costo = _dinero(respuesta['usage']['cost'])
            except HTTPError as error:
                if error.code in (402, 429):
                    self.detenido = True
                    raise LimiteBusqueda(f'OpenRouter: búsqueda {error.code}; se conserva la reserva y no se reintenta') from None
                raise ValueError('OpenRouter rechazó la búsqueda; se conserva la reserva') from None
            except Exception:
                raise ValueError('No se confirmó el costo de la búsqueda; se conserva la reserva') from None
            self._guardar(dia, usado + costo)
            return respuesta
        finally:
            exclusivo.close()
            bloqueo.unlink(missing_ok=True)
