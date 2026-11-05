"""Pruebas con copias reales de cada fuente (3 nov 2026) y con casos malos a propósito."""
import json
from datetime import datetime
from pathlib import Path

import pytest

import main
import recolector as r
import validar as v

COPIAS = Path(__file__).parent / "copias"


def leer(nombre):
    return (COPIAS / nombre).read_text(encoding="utf-8")


# ---------------------------------------------------------------- cada lector con su copia real

@pytest.mark.parametrize("lector, archivo, usd, eur", [
    (r.leer_popular, "popular.json", (57.45, 61.45), (65.80, 70.40)),
    (r.leer_banreservas, "banreservas.html", (58.40, 61.40), (66.00, 71.50)),
    (r.leer_bhd, "bhd.json", (57.95, 61.40), (66.00, 71.50)),
    (r.leer_scotiabank, "scotiabank.html", (58.00, 61.45), (65.15, 69.55)),
    (r.leer_caribe, "caribe.html", (59.35, 61.35), (66.00, 70.00)),
    (r.leer_bdi, "bdi.html", (59.75, 61.50), (66.00, 70.00)),
    (r.leer_vimenca, "vimenca.json", (59.40, 61.40), (66.50, 70.40)),
    (r.leer_apap, "apap.html", (58.50, 61.45), (66.30, 71.00)),
    (r.leer_cibao, "cibao.json", (59.40, 61.40), (66.00, 71.50)),
    (r.leer_caribeexpress, "caribeexpress.html", (59.75, None), (66.00, None)),
])
def test_lectores_bancos(lector, archivo, usd, eur):
    datos = lector(leer(archivo))
    assert (datos["usd"]["compra"], datos["usd"]["venta"]) == usd
    assert (datos["eur"]["compra"], datos["eur"]["venta"]) == eur


def test_fechas_de_la_fuente():
    assert r.leer_popular(leer("popular.json"))["fecha_fuente"] == "2026-11-03T17:20:00+00:00"
    assert r.leer_vimenca(leer("vimenca.json"))["fecha_fuente"] == "2026-11-03"


def test_banco_central():
    bc = r.leer_bancocentral(leer("bancocentral.html"))
    assert bc["usd"] == {"compra": 60.4231, "venta": 60.8721}
    assert bc["fecha_fuente"] == "2026-11-03"


def test_micm_toma_la_nota_mas_reciente():
    nota = r.leer_micm(leer("micm_feed.xml"))
    assert nota["semana"] == "31 de octubre al 6 de noviembre de 2026"
    precios = {p["id"]: (p["precio"], p["cambio"], p["unidad"]) for p in nota["precios"]}
    assert precios == {
        "gasolina_premium": (358.10, 0.0, "galón"),
        "gasolina_regular": (317.50, 0.0, "galón"),
        "gasoil_regular": (270.80, 0.0, "galón"),
        "gasoil_optimo": (318.10, 0.0, "galón"),
        "glp": (135.20, 0.0, "galón"),
        "kerosene": (400.10, -2.60, "galón"),
        "gas_natural": (43.97, 0.0, "m³"),
    }


def test_micm_lee_subidas_de_la_nota_vieja():
    feed = leer("micm_feed.xml")
    vieja = feed.split("<item>")[2]
    nota = r.leer_micm("<rss><channel><item>" + vieja)
    precios = {p["id"]: (p["precio"], p["cambio"]) for p in nota["precios"]}
    assert precios["gasolina_premium"] == (353.10, 3.00)
    assert precios["gasoil_optimo"] == (306.10, 4.00)
    assert precios["kerosene"] == (383.70, -4.60)


def test_otras_monedas():
    m = r.leer_exchangerate(leer("exchangerate.json"))
    pesos = {x["codigo"]: x["pesos"] for x in m["monedas"]}
    assert pesos["EUR"] == pytest.approx(67.4855, abs=0.001)
    assert set(pesos) == {"USD", "EUR", "CAD", "GBP", "MXN", "CHF"}


# ---------------------------------------------------------------- páginas cambiadas o rotas

@pytest.mark.parametrize("lector", [r.leer_banreservas, r.leer_scotiabank, r.leer_caribe, r.leer_bdi,
                                    r.leer_apap, r.leer_caribeexpress, r.leer_bancocentral])
def test_pagina_sin_datos_avisa(lector):
    with pytest.raises(r.FuenteRota):
        lector("<html><body><h1>Sitio en mantenimiento</h1></body></html>")


@pytest.mark.parametrize("lector, texto", [
    (r.leer_popular, '{"value": []}'), (r.leer_bhd, '{"data": {}}'),
    (r.leer_cibao, "[]"), (r.leer_vimenca, '{"data": []}'),
    (r.leer_exchangerate, '{"result": "error"}'), (r.leer_micm, "<rss></rss>"),
])
def test_json_sin_datos_avisa(lector, texto):
    with pytest.raises(r.FuenteRota):
        lector(texto)


# ---------------------------------------------------------------- controles de calidad

def test_control_venta_menor_que_compra():
    assert "no es mayor" in v.revisar_par({"compra": 61.0, "venta": 60.0}, 60.6)


def test_control_lejos_de_la_referencia():
    assert "6 %" in v.revisar_par({"compra": 5.84, "venta": 61.40}, 60.6)  # punto mal puesto


def test_control_salto_brusco():
    assert "saltó" in v.revisar_par({"compra": 62.5, "venta": 64.0}, 60.6, {"compra": 58.4, "venta": 61.4})


def test_control_par_bueno():
    assert v.revisar_par({"compra": 58.40, "venta": 61.40}, 60.6, {"compra": 58.30, "venta": 61.40}) is None
    assert v.revisar_par({"compra": 59.75, "venta": None}, 60.6) is None


# ---------------------------------------------------------------- corrida completa

MOMENTO = datetime(2026, 11, 3, 19, 30, tzinfo=main.ZONA)


def test_corrida_completa_con_copias(tmp_path):
    res = main.recolectar(main.Lector(COPIAS), tmp_path, MOMENTO)
    assert all(e in ("ok", "enlace") for e in res["estado"].values()), res["estado"]
    assert len(res["lugares"]) == 10
    assert sum(x["vigente"] for x in res["lugares"]) == 8
    solo = {x["id"]: x for x in res["lugares"] if x.get("solo_enlace")}
    assert set(solo) == {"banreservas", "caribe"}
    assert solo["banreservas"]["enlace"] == "https://www.banreservas.com/" and solo["caribe"]["usd"] is None
    assert res["banco_central"]["usd"]["compra"] == 60.4231
    assert len(res["combustibles"]["precios"]) == 7
    guardado = json.loads((tmp_path / "actual.json").read_text(encoding="utf-8"))
    assert guardado["actualizado"] == "2026-11-03T19:30-04:00"
    assert (tmp_path / "historial" / "2026-11-03.json").exists()


class LectorQueAnota(main.Lector):
    def __init__(self):
        super().__init__(COPIAS)
        self.pedidos = []

    def traer(self, ident, url, formato="html"):
        self.pedidos.append(ident)
        return super().traer(ident, url, formato)


def test_no_se_piden_los_sitios_que_bloquean(tmp_path):
    lector = LectorQueAnota()
    main.recolectar(lector, tmp_path, MOMENTO)
    assert "banreservas" not in lector.pedidos and "caribe" not in lector.pedidos


class LectorRoto(main.Lector):
    """Simula que un banco cambió su página."""

    def __init__(self, rotos):
        super().__init__(COPIAS)
        self.rotos = rotos

    def traer(self, ident, url, formato="html"):
        if ident in self.rotos:
            return "<html>pagina nueva</html>"
        return super().traer(ident, url, formato)


def test_banco_roto_conserva_ultimo_valor_bueno(tmp_path):
    main.recolectar(main.Lector(COPIAS), tmp_path, MOMENTO)
    res = main.recolectar(LectorRoto({"bhd"}), tmp_path, MOMENTO)
    bhd = next(x for x in res["lugares"] if x["id"] == "bhd")
    assert bhd["vigente"] is False and bhd["usd"]["compra"] == 57.95 and "motivo" in bhd
    assert res["estado"]["bhd"].startswith("error")
    assert sum(x["vigente"] for x in res["lugares"]) == 7


def test_banco_roto_sin_valor_anterior(tmp_path):
    res = main.recolectar(LectorRoto({"bdi"}), tmp_path, MOMENTO)
    bdi = next(x for x in res["lugares"] if x["id"] == "bdi")
    assert bdi["vigente"] is False and bdi["usd"] is None


def test_flechas_de_ayer(tmp_path):
    ayer = datetime(2026, 11, 2, 19, 0, tzinfo=main.ZONA)
    main.recolectar(main.Lector(COPIAS), tmp_path, ayer)
    res = main.recolectar(main.Lector(COPIAS), tmp_path, MOMENTO)
    popular = next(x for x in res["lugares"] if x["id"] == "popular")
    assert popular["ayer"]["usd"] == {"compra": 57.45, "venta": 61.45}
    assert res["banco_central"]["ayer"] == {"compra": 60.4231, "venta": 60.8721}


def test_fuente_vieja_no_es_vigente(tmp_path):
    lejos = datetime(2026, 11, 10, 9, 0, tzinfo=main.ZONA)  # Vimenca dice 3 nov: 7 días atrás
    res = main.recolectar(main.Lector(COPIAS), tmp_path, lejos)
    vimenca = next(x for x in res["lugares"] if x["id"] == "vimenca")
    assert vimenca["vigente"] is False and "no actualiza" in vimenca["motivo"]
