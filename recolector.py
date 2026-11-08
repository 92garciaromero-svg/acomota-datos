"""Lectores de cada fuente de A Cómo Tá.

Cada lector recibe el texto que publica la fuente y devuelve los números.
Si la fuente cambia su página y ya no se encuentran los datos, el lector
lanza FuenteRota con una explicación; nunca devuelve un número inventado.
"""
import html
import json
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup


class FuenteRota(Exception):
    """La fuente respondió, pero no se encontraron los datos esperados."""


MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def numero(texto):
    """'1,516.50' -> 1516.5 ; ' 58.40 ' -> 58.4"""
    if isinstance(texto, (int, float)):
        return float(texto)
    limpio = str(texto).strip().replace("RD$", "").replace(",", "").strip()
    try:
        return float(limpio)
    except ValueError:
        raise FuenteRota(f"no es un número: {texto!r}")


def _par(compra, venta):
    return {"compra": numero(compra), "venta": None if venta is None else numero(venta)}


# ---------------------------------------------------------------- bancos (JSON)

def leer_popular(texto):
    datos = json.loads(texto)
    try:
        f = datos["value"][0]
        resultado = {
            "usd": _par(f["DollarBuyRate"], f["DollarSellRate"]),
            "eur": _par(f["EuroBuyRate"], f["EuroSellRate"]),
        }
    except (KeyError, IndexError, TypeError):
        raise FuenteRota("Popular: no aparecen DollarBuyRate/DollarSellRate")
    fecha = f.get("BuySellRatesAsOf")
    if fecha:
        resultado["fecha_fuente"] = fecha.replace("Z", "+00:00")
    return resultado


def _buscar_clave(obj, clave):
    if isinstance(obj, dict):
        if clave in obj:
            return obj[clave]
        for v in obj.values():
            r = _buscar_clave(v, clave)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _buscar_clave(v, clave)
            if r is not None:
                return r
    return None


def leer_bhd(texto):
    tasas = _buscar_clave(json.loads(texto), "exchangeRates")
    if not tasas:
        raise FuenteRota("BHD: no aparece exchangeRates")
    porm = {t.get("currency"): t for t in tasas}
    if "USD" not in porm:
        raise FuenteRota("BHD: no aparece el dólar")
    r = {"usd": _par(porm["USD"]["buyingRate"], porm["USD"]["sellingRate"])}
    if "EUR" in porm:
        r["eur"] = _par(porm["EUR"]["buyingRate"], porm["EUR"]["sellingRate"])
    return r


def leer_cibao(texto):
    lista = json.loads(texto)
    porm = {str(x.get("codigoMoneda", "")).upper(): x for x in lista}
    usd = porm.get("US$") or porm.get("USD") or porm.get("USD$")
    if not usd:
        raise FuenteRota("Cibao: no aparece US$")
    r = {"usd": _par(usd["compra"], usd["venta"])}
    eur = porm.get("EUR$") or porm.get("EUR")
    if eur:
        r["eur"] = _par(eur["compra"], eur["venta"])
    return r


def leer_vimenca(texto):
    datos = json.loads(texto).get("data") or []
    porm = {str(x.get("coinName", "")).upper(): x for x in datos}
    usd = next((v for k, v in porm.items() if "DOLAR EE" in k), None)
    if not usd:
        raise FuenteRota("Vimenca: no aparece DOLAR EE.UU")
    r = {"usd": _par(usd["purchaseValue"], usd["saleValue"])}
    eur = porm.get("EURO")
    if eur:
        r["eur"] = _par(eur["purchaseValue"], eur["saleValue"])
    f = str(usd.get("fecha", ""))
    if re.fullmatch(r"\d{8}", f):
        r["fecha_fuente"] = f"{f[:4]}-{f[4:6]}-{f[6:]}"
    return r


# ---------------------------------------------------------------- bancos (HTML)

def leer_banreservas(texto):
    sopa = BeautifulSoup(texto, "html.parser")

    def celda(clase):
        el = sopa.select_one(f"td.{clase}")
        if el is None:
            raise FuenteRota(f"Banreservas: no aparece {clase}")
        m = re.search(r"\d+(?:\.\d+)?", el.get_text())
        if not m:
            raise FuenteRota(f"Banreservas: {clase} vacío")
        return m.group(0)

    r = {"usd": _par(celda("tasacambio-compraUS"), celda("tasacambio-ventaUS"))}
    try:
        r["eur"] = _par(celda("tasacambio-compraEU"), celda("tasacambio-ventaEU"))
    except FuenteRota:
        pass
    return r


def leer_scotiabank(texto):
    sopa = BeautifulSoup(texto, "html.parser")
    filas = {}
    for tr in sopa.select("table tr"):
        celdas = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        nums = [c for c in celdas if re.fullmatch(r"\d+(?:\.\d+)?", c)]
        nombre = " ".join(c for c in celdas if c not in nums).lower()
        if len(nums) >= 2:
            filas[nombre] = (nums[0], nums[1])
    usd = next((v for k, v in filas.items() if "dólar (us)" in k and "sucursal" in k), None) \
        or next((v for k, v in filas.items() if "dólar (us)" in k or "dolar (us)" in k), None)
    if not usd:
        raise FuenteRota("Scotiabank: no aparece la fila del Dólar (US)")
    r = {"usd": _par(*usd)}
    eur = next((v for k, v in filas.items() if "euro" in k), None)
    if eur:
        r["eur"] = _par(*eur)
    return r


def leer_apap(texto):
    def valor(lado, moneda):
        m = re.search(r'#currency-%s-%s"\)\.html\((?:addZeroes\()?"?([\d.]+)' % (lado, moneda), texto)
        if not m:
            raise FuenteRota(f"APAP: no aparece currency-{lado}-{moneda}")
        return m.group(1)

    r = {"usd": _par(valor("buy", "USD"), valor("sell", "USD"))}
    try:
        r["eur"] = _par(valor("buy", "EUR"), valor("sell", "EUR"))
    except FuenteRota:
        pass
    return r


def leer_caribe(texto):
    sopa = BeautifulSoup(texto, "html.parser")

    def valor(idx):
        el = sopa.find(id=idx)
        if el is None:
            raise FuenteRota(f"Banco Caribe: no aparece #{idx}")
        return el.get_text(strip=True)

    r = {"usd": _par(valor("us_buy_res"), valor("us_sell_res"))}
    try:
        r["eur"] = _par(valor("eur_buy_res"), valor("eur_sell_res"))
    except FuenteRota:
        pass
    return r


def leer_bdi(texto):
    def valor(nombre):
        m = re.search(r"function\s+%s\s*\([^)]*\)\s*\{.{0,400}?parseFloat\(\s*([\d.]+)\s*\)" % nombre,
                      texto, re.S)
        if not m:
            raise FuenteRota(f"BDI: no aparece {nombre}")
        return m.group(1)

    r = {"usd": _par(valor("ChangeRateDollarBuy"), valor("ChangeRateDollarSell"))}
    try:
        r["eur"] = _par(valor("ChangeRateEuroBuy"), valor("ChangeRateEuroSell"))
    except FuenteRota:
        pass
    return r


def leer_caribeexpress(texto):
    """Caribe Express solo publica la tasa a la que compra (te da)."""
    opciones = dict((m.group(2), m.group(1))
                    for m in re.finditer(r'value="([\d.]+)\|([A-Z]{3})"', texto))
    if "USD" not in opciones:
        raise FuenteRota("Caribe Express: no aparece la opción USD")
    r = {"usd": _par(opciones["USD"], None)}
    if "EUR" in opciones:
        r["eur"] = _par(opciones["EUR"], None)
    return r


# ---------------------------------------------------------------- Banco Central

def leer_bancocentral(texto):
    plano = re.sub(r"\s+", " ", BeautifulSoup(texto, "html.parser").get_text(" "))
    m = re.search(r"Tipo de cambio\s+(\d{1,2}) de (\w+) (\d{4})\s+Compra\s+([\d.]+)\s+Venta\s+([\d.]+)",
                  plano, re.I)
    if not m:
        raise FuenteRota("Banco Central: no aparece 'Tipo de cambio ... Compra ... Venta'")
    dia, mes, anio, compra, venta = m.groups()
    mes_n = MESES.get(mes.lower())
    if not mes_n:
        raise FuenteRota(f"Banco Central: mes desconocido {mes!r}")
    return {"usd": _par(compra, venta), "fecha_fuente": date(int(anio), mes_n, int(dia)).isoformat()}


# ---------------------------------------------------------------- MICM

COMBUSTIBLES = [
    ("gasolina_premium", "Gasolina premium", r"Gasolina Premium"),
    ("gasolina_regular", "Gasolina regular", r"Gasolina Regular"),
    ("gasoil_regular", "Gasoil regular", r"Gasoil Regular"),
    ("gasoil_optimo", "Gasoil óptimo", r"Gasoil [OÓ]ptimo"),
    ("glp", "Gas (GLP)", r"Gas Licuado de Petr[oó]leo \(GLP\)"),
    ("kerosene", "Kerosene", r"Kerosene"),
    ("gas_natural", "Gas natural", r"Gas Natural"),
]


def _texto_plano(fragmento_html):
    return re.sub(r"\s+", " ", html.unescape(BeautifulSoup(fragmento_html, "html.parser").get_text(" "))).strip()


def leer_combustibles_de_nota(contenido_html):
    texto = _texto_plano(contenido_html)
    precios = []
    for ident, nombre, patron in COMBUSTIBLES:
        m = re.search(
            patron + r"(?: se vender[aá] a)?\s+RD\$\s*([\d,]+(?:\.\d+)?)\s+por (gal[oó]n|m3)\s+"
            r"(mantiene su precio|sube RD\$\s*(\d+(?:\.\d+)?)|baja RD\$\s*(\d+(?:\.\d+)?))",
            texto, re.I)
        if not m:
            continue
        precio, unidad, _, sube, baja = m.groups()
        cambio = numero(sube) if sube else (-numero(baja) if baja else 0.0)
        precios.append({
            "id": ident, "nombre": nombre, "precio": numero(precio),
            "unidad": "galón" if unidad.lower().startswith("gal") else "m³",
            "cambio": round(cambio, 2),
        })
    semana = None
    m = re.search(r"semana del ((?:\d{1,2})(?: de \w+)? al \d{1,2} de \w+(?: de \d{4})?)", texto)
    if m:
        semana = m.group(1)
    return precios, semana


def leer_micm(texto):
    """Busca en el feed la nota más reciente que trae la lista de precios."""
    partes = re.split(r"<item>", texto)[1:]
    if not partes:
        raise FuenteRota("MICM: el feed no trae notas")
    candidatas = []
    for item in partes:
        cuerpo = re.search(r"<content:encoded><!\[CDATA\[(.*?)\]\]></content:encoded>", item, re.S)
        if not cuerpo:
            continue
        precios, semana = leer_combustibles_de_nota(cuerpo.group(1))
        if len(precios) < 5:
            continue
        fecha = re.search(r"<pubDate>([^<]+)</pubDate>", item)
        enlace = re.search(r"<link>([^<]+)</link>", item)
        publicado = parsedate_to_datetime(fecha.group(1)) if fecha else datetime.min.replace(tzinfo=timezone.utc)
        candidatas.append({"publicado": publicado, "semana": semana, "precios": precios,
                           "enlace": enlace.group(1).strip() if enlace else None})
    if not candidatas:
        raise FuenteRota("MICM: ninguna nota trae la lista de precios")
    mejor = max(candidatas, key=lambda c: c["publicado"])
    mejor["publicado"] = mejor["publicado"].isoformat()
    return mejor


# ---------------------------------------------------------------- otras monedas

MONEDAS = [("USD", "Dólar estadounidense"), ("EUR", "Euro"), ("CAD", "Dólar canadiense"),
           ("GBP", "Libra esterlina"), ("MXN", "Peso mexicano"), ("CHF", "Franco suizo"),
           ("HTG", "Gourde haitiano")]


def leer_exchangerate(texto):
    datos = json.loads(texto)
    if datos.get("result") != "success" or datos.get("base_code") != "DOP":
        raise FuenteRota("ExchangeRate-API: respuesta inesperada")
    tasas = datos.get("rates") or {}
    lista = []
    for codigo, nombre in MONEDAS:
        v = tasas.get(codigo)
        if v:
            lista.append({"codigo": codigo, "nombre": nombre, "pesos": round(1 / v, 4)})
    if len(lista) < 3:
        raise FuenteRota("ExchangeRate-API: faltan monedas")
    return {"monedas": lista, "fecha_fuente": datos.get("time_last_update_utc")}


# ---------------------------------------------------------------- catálogo

LUGARES = [
    # id, nombre, tipo, url, formato, lector
    ("popular", "Banco Popular", "Banco",
     "https://popularenlinea.com/_api/web/lists/getbytitle('Rates')/items?$filter=ItemID%20eq%20%271%27",
     "json", leer_popular),
    ("banreservas", "Banreservas", "Banco", "https://www.banreservas.com/", "html", leer_banreservas),
    ("bhd", "BHD", "Banco", "https://backend.bhd.com.do/api/modal-cambio-rate?populate=deep", "json", leer_bhd),
    ("scotiabank", "Scotiabank", "Banco",
     "https://do.scotiabank.com/banca-personal/tarifas/tasas-de-cambio.html", "html", leer_scotiabank),
    ("caribe", "Banco Caribe", "Banco", "https://www.bancocaribe.com.do/", "html", leer_caribe),
    ("bdi", "Banco BDI", "Banco", "https://www.bdi.com.do/", "html", leer_bdi),
    ("vimenca", "Banco Vimenca", "Banco", "https://backend.bancovimenca.com/api/services/bank/tasa", "json",
     leer_vimenca),
    ("apap", "APAP", "Asociación", "https://www.apap.com.do/", "html", leer_apap),
    ("cibao", "Asociación Cibao", "Asociación", "https://www.cibao.com.do/api/Coins/GetCoins", "json",
     leer_cibao),
    ("caribeexpress", "Caribe Express", "Remesadora", "https://caribeexpress.com.do/servicios/cambio", "html",
     leer_caribeexpress),
]

BANCO_CENTRAL = ("bancocentral", "https://www.bancentral.gov.do/", leer_bancocentral)
MICM = ("micm", "https://micm.gob.do/tag/combustibles/feed/", leer_micm)
EXCHANGERATE = ("exchangerate", "https://open.er-api.com/v6/latest/DOP", leer_exchangerate)
