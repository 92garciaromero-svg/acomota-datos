"""Recolector de A Cómo Tá: lee todas las fuentes, revisa los datos y escribe datos/actual.json.

Uso:
    python main.py                      # lee las fuentes reales en internet
    python main.py --copias pruebas/copias --salida /tmp/prueba   # usa copias guardadas (pruebas)
"""
import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import recolector as r
import validar as v

ZONA = ZoneInfo("America/Santo_Domingo")
AGENTE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 AComoTa/1.0")
ATRIBUCION = "Tasas de otras monedas por ExchangeRate-API (https://www.exchangerate-api.com)"
MICM_FEEDS = ["https://micm.gob.do/tag/combustibles/feed/", "https://micm.gob.do/feed/"]

COPIAS = {  # id -> archivo, para correr sin internet
    "popular": "popular.json", "banreservas": "banreservas.html", "bhd": "bhd.json",
    "scotiabank": "scotiabank.html", "caribe": "caribe.html", "bdi": "bdi.html",
    "vimenca": "vimenca.json", "apap": "apap.html", "cibao": "cibao.json",
    "caribeexpress": "caribeexpress.html", "bancocentral": "bancocentral.html",
    "micm": "micm_feed.xml", "exchangerate": "exchangerate.json",
}


class Lector:
    def __init__(self, copias=None):
        self.copias = Path(copias) if copias else None
        self.sesion = requests.Session()
        self.sesion.headers.update({"User-Agent": AGENTE, "Accept-Language": "es-DO,es;q=0.9"})

    def traer(self, ident, url, formato="html"):
        if self.copias:
            return (self.copias / COPIAS[ident]).read_text(encoding="utf-8")
        cabeceras = {"Accept": "application/json;odata=nometadata"} if formato == "json" else {}
        ultimo = None
        for intento in range(2):
            try:
                resp = self.sesion.get(url, headers=cabeceras, timeout=25)
                resp.raise_for_status()
                resp.encoding = resp.encoding or "utf-8"
                return resp.text
            except requests.RequestException as e:
                ultimo = e
                time.sleep(3)
        raise r.FuenteRota(f"no se pudo descargar: {type(ultimo).__name__}")


def ahora():
    return datetime.now(ZONA)


def leer_json(ruta):
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def dia_anterior(salida, hoy):
    """Último resumen guardado de un día anterior a hoy (para las flechas de subió/bajó)."""
    carpeta = Path(salida) / "historial"
    if not carpeta.exists():
        return None
    dias = sorted(p for p in carpeta.glob("*.json") if p.stem < hoy.isoformat())
    return leer_json(dias[-1]) if dias else None


def fecha_de(texto):
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto).astimezone(ZONA).date() if "T" in texto else date.fromisoformat(texto)
    except ValueError:
        return None


def recolectar(lector, salida, momento=None):
    momento = momento or ahora()
    hoy = momento.date()
    anterior = leer_json(Path(salida) / "actual.json") or {}
    ayer = dia_anterior(salida, hoy) or {}
    estado = {}

    # ---- otras monedas (también sirven de referencia para el euro)
    monedas_ant = anterior.get("monedas") or {}
    try:
        m = r.leer_exchangerate(lector.traer("exchangerate", r.EXCHANGERATE[1], "json"))
        monedas = {"lista": m["monedas"], "fecha_fuente": m["fecha_fuente"], "vigente": True,
                   "atribucion": ATRIBUCION, "fuente": "https://www.exchangerate-api.com"}
        estado["exchangerate"] = "ok"
    except Exception as e:  # noqa: BLE001 - una fuente rota no debe tumbar las demás
        monedas = dict(monedas_ant, vigente=False) if monedas_ant else {"lista": [], "vigente": False,
                                                                         "atribucion": ATRIBUCION}
        estado["exchangerate"] = f"error: {e}"
    ref = {x["codigo"]: x["pesos"] for x in monedas.get("lista", [])}

    # ---- Banco Central
    bc_ant = anterior.get("banco_central") or {}
    try:
        bc = r.leer_bancocentral(lector.traer("bancocentral", r.BANCO_CENTRAL[1]))
        motivo = v.revisar_banco_central(bc["usd"], bc_ant.get("usd"))
        if motivo:
            raise r.FuenteRota(motivo)
        banco_central = {"usd": bc["usd"], "fecha_fuente": bc["fecha_fuente"], "vigente": True,
                         "leido": momento.isoformat(timespec="minutes"), "fuente": r.BANCO_CENTRAL[1]}
        estado["bancocentral"] = "ok"
    except Exception as e:  # noqa: BLE001
        banco_central = dict(bc_ant, vigente=False, motivo=str(e)) if bc_ant else {"usd": None, "vigente": False,
                                                                                   "motivo": str(e)}
        estado["bancocentral"] = f"error: {e}"
    ayer_bc = (ayer.get("banco_central") or {}).get("usd")
    banco_central["ayer"] = ayer_bc if ayer_bc and ayer.get("banco_central", {}).get("vigente") else None

    usd_bc = banco_central.get("usd") or {}
    referencia_usd = ((usd_bc.get("compra") or 0) + (usd_bc.get("venta") or 0)) / 2 or ref.get("USD")
    referencias = {"usd": referencia_usd, "eur": ref.get("EUR")}

    # ---- bancos, asociaciones y remesadoras
    previos = {x["id"]: x for x in anterior.get("lugares", [])}
    previos_ayer = {x["id"]: x for x in ayer.get("lugares", [])}
    lugares = []
    for ident, nombre, tipo, url, formato, leer in r.LUGARES:
        base = {"id": ident, "nombre": nombre, "tipo": tipo, "fuente": url}
        previo = previos.get(ident) or {}
        try:
            datos = leer(lector.traer(ident, url, formato))
            for moneda in ("usd", "eur"):
                if moneda in datos:
                    motivo = v.revisar_par(datos[moneda], referencias[moneda], previo.get(moneda))
                    if motivo:
                        raise r.FuenteRota(f"{moneda.upper()}: {motivo}")
            entrada = dict(base, usd=datos["usd"], eur=datos.get("eur"), vigente=True,
                           leido=momento.isoformat(timespec="minutes"), fecha_fuente=datos.get("fecha_fuente"))
            f = fecha_de(entrada["fecha_fuente"])
            if f and (hoy - f).days > v.DIAS_VIEJA:
                entrada.update(vigente=False, motivo=f"la fuente no actualiza desde el {f.isoformat()}")
            estado[ident] = "ok" if entrada["vigente"] else f"vieja: {entrada['motivo']}"
        except Exception as e:  # noqa: BLE001
            if previo.get("usd"):
                entrada = dict(previo, **base, vigente=False, motivo=str(e))
            else:
                entrada = dict(base, usd=None, eur=None, vigente=False, motivo=str(e), leido=None)
            estado[ident] = f"error: {e}"
        dia_ant = previos_ayer.get(ident) or {}
        entrada["ayer"] = ({"usd": dia_ant.get("usd"), "eur": dia_ant.get("eur")}
                           if dia_ant.get("vigente") and dia_ant.get("usd") else None)
        entrada.pop("motivo", None) if entrada["vigente"] else None
        lugares.append(entrada)

    # ---- combustibles
    comb_ant = anterior.get("combustibles") or {}
    try:
        textos = [lector.traer("micm", u, "html") for u in (MICM_FEEDS[:1] if lector.copias else MICM_FEEDS)]
        nota = r.leer_micm("\n".join(textos))
        motivo = v.revisar_combustibles(nota["precios"])
        if motivo:
            raise r.FuenteRota(motivo)
        combustibles = dict(nota, vigente=True, fuente="https://micm.gob.do")
        estado["micm"] = "ok"
    except Exception as e:  # noqa: BLE001
        combustibles = dict(comb_ant, vigente=False) if comb_ant else {"precios": [], "vigente": False}
        estado["micm"] = f"error: {e}"

    resumen = {
        "version": 1,
        "actualizado": momento.isoformat(timespec="minutes"),
        "banco_central": banco_central,
        "lugares": lugares,
        "monedas": monedas,
        "combustibles": combustibles,
        "estado": estado,
    }
    escribir(salida, resumen, hoy)
    return resumen


def escribir(salida, resumen, hoy):
    carpeta = Path(salida)
    (carpeta / "historial").mkdir(parents=True, exist_ok=True)
    texto = json.dumps(resumen, ensure_ascii=False, indent=1)
    (carpeta / "actual.json").write_text(texto + "\n", encoding="utf-8")
    (carpeta / "historial" / f"{hoy.isoformat()}.json").write_text(texto + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--copias", help="carpeta con copias guardadas de las fuentes (modo prueba)")
    p.add_argument("--salida", default="datos")
    a = p.parse_args()
    resumen = recolectar(Lector(a.copias), a.salida)
    malos = {k: e for k, e in resumen["estado"].items() if e != "ok"}
    print(f"Actualizado {resumen['actualizado']}: {len(resumen['estado']) - len(malos)} fuentes bien, "
          f"{len(malos)} con problemas")
    for k, e in malos.items():
        print(f"  - {k}: {e}")
    # Solo falla la corrida si no se pudo leer nada de nada.
    sys.exit(1 if len(malos) == len(resumen["estado"]) else 0)


if __name__ == "__main__":
    main()
