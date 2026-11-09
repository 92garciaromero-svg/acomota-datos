"""Avisa por GitHub (llega a tu correo) cuando una fuente falla varias lecturas seguidas.

Se corre después de main.py. Lleva la cuenta en datos/vigilancia.json:
- si una fuente falla FALLAS_PARA_AVISAR veces seguidas, abre un aviso (issue) en el repositorio;
- cuando la fuente vuelve a leerse bien, cierra ese aviso con un comentario.
"""
import json
import subprocess
import sys
from pathlib import Path

FALLAS_PARA_AVISAR = 3  # unas 6 horas en días de semana (se lee cada 2 horas)
BIEN = ("ok", "enlace")


def actualizar(cuentas, estado):
    """Devuelve (cuentas nuevas, fuentes a avisar, fuentes recuperadas). No toca GitHub."""
    nuevas, avisar, recuperadas = {}, [], []
    for fuente, resultado in estado.items():
        previa = cuentas.get(fuente) or {"fallas": 0, "aviso": None}
        if resultado in BIEN:
            if previa.get("aviso"):
                recuperadas.append((fuente, previa["aviso"]))
            nuevas[fuente] = {"fallas": 0, "aviso": None}
            continue
        fallas = previa.get("fallas", 0) + 1
        nuevas[fuente] = {"fallas": fallas, "aviso": previa.get("aviso"), "ultimo": resultado}
        if fallas >= FALLAS_PARA_AVISAR and not previa.get("aviso"):
            avisar.append((fuente, resultado, fallas))
    return nuevas, avisar, recuperadas


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout.strip()


def main(carpeta="datos"):
    carpeta = Path(carpeta)
    estado = json.loads((carpeta / "actual.json").read_text(encoding="utf-8"))["estado"]
    archivo = carpeta / "vigilancia.json"
    cuentas = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {}
    nuevas, avisar, recuperadas = actualizar(cuentas, estado)

    for fuente, resultado, fallas in avisar:
        cuerpo = (f"La fuente **{fuente}** lleva {fallas} lecturas seguidas con problemas.\n\n"
                  f"Último resultado: `{resultado}`\n\n"
                  "Mientras tanto la app la muestra en gris como «vieja» y no la usa para las 3 mejores. "
                  "Probablemente el sitio cambió su página: hay que revisar su lector en `recolector.py`.\n\n"
                  "Este aviso se cierra solo cuando la fuente se vuelva a leer bien.")
        try:
            url = gh("issue", "create", "--title", f"Fuente con problemas: {fuente}", "--body", cuerpo)
            nuevas[fuente]["aviso"] = int(url.rstrip("/").split("/")[-1])
            print(f"Aviso abierto para {fuente}: {url}")
        except Exception as e:  # noqa: BLE001 - el aviso no debe tumbar la corrida
            print(f"No se pudo abrir el aviso de {fuente}: {e}", file=sys.stderr)

    for fuente, numero in recuperadas:
        try:
            gh("issue", "close", str(numero), "--comment", f"{fuente} se volvió a leer bien. Cerrado automáticamente.")
            print(f"Aviso #{numero} de {fuente} cerrado")
        except Exception as e:  # noqa: BLE001
            print(f"No se pudo cerrar el aviso #{numero}: {e}", file=sys.stderr)

    archivo.write_text(json.dumps(nuevas, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:])
