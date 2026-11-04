"""Controles de calidad: una tasa que no pasa estos controles no se publica como vigente."""

MAX_DISTANCIA_REFERENCIA = 0.06   # 6 % lejos de la tasa de referencia
MAX_SALTO = 0.03                  # 3 % de cambio de golpe frente a la lectura anterior
DIAS_VIEJA = 3                    # una tasa con fecha de la fuente más vieja que esto no está vigente


def revisar_par(par, referencia=None, anterior=None):
    """Devuelve None si el par compra/venta es razonable, o el motivo del rechazo."""
    compra, venta = par.get("compra"), par.get("venta")
    if compra is None or compra <= 0:
        return "compra vacía o en cero"
    if venta is not None:
        if venta <= 0:
            return "venta vacía o en cero"
        if venta <= compra:
            return f"la venta ({venta}) no es mayor que la compra ({compra})"
    if referencia:
        for nombre, valor in (("compra", compra), ("venta", venta)):
            if valor is not None and abs(valor / referencia - 1) > MAX_DISTANCIA_REFERENCIA:
                return f"la {nombre} ({valor}) está a más de 6 % de la referencia ({referencia})"
    if anterior:
        for nombre in ("compra", "venta"):
            nuevo, viejo = par.get(nombre), anterior.get(nombre)
            if nuevo is not None and viejo and abs(nuevo / viejo - 1) > MAX_SALTO:
                return f"la {nombre} saltó de {viejo} a {nuevo} (más de 3 %)"
    return None


def revisar_banco_central(par, anterior=None):
    compra, venta = par.get("compra"), par.get("venta")
    if not compra or not venta or not (20 < compra < 200) or not (20 < venta < 200):
        return "tasa del Banco Central fuera de rango"
    if venta < compra:
        return "venta menor que la compra en el Banco Central"
    if anterior and anterior.get("compra") and abs(compra / anterior["compra"] - 1) > MAX_SALTO:
        return f"el Banco Central saltó de {anterior['compra']} a {compra} (más de 3 %)"
    return None


def revisar_combustibles(precios, anteriores=None):
    if len(precios) < 5:
        return "faltan precios de combustibles"
    for p in precios:
        if not (5 < p["precio"] < 2000):
            return f"precio fuera de rango: {p['nombre']} {p['precio']}"
    return None
