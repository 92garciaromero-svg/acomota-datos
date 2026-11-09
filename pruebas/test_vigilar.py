import vigilar as vg


def test_avisa_a_la_tercera_falla_seguida():
    cuentas = {}
    for vez in range(1, 4):
        cuentas, avisar, _ = vg.actualizar(cuentas, {"bhd": "error: no se pudo descargar (500)", "popular": "ok"})
        assert (avisar != []) == (vez == 3)
    assert avisar == [("bhd", "error: no se pudo descargar (500)", 3)]
    assert cuentas["popular"]["fallas"] == 0


def test_no_repite_el_aviso():
    cuentas = {"bhd": {"fallas": 5, "aviso": 12}}
    cuentas, avisar, _ = vg.actualizar(cuentas, {"bhd": "error: x"})
    assert avisar == [] and cuentas["bhd"] == {"fallas": 6, "aviso": 12, "ultimo": "error: x"}


def test_una_falla_suelta_no_avisa_y_se_olvida():
    cuentas, avisar, _ = vg.actualizar({}, {"bdi": "error: timeout"})
    cuentas, avisar2, _ = vg.actualizar(cuentas, {"bdi": "ok"})
    assert avisar == avisar2 == [] and cuentas["bdi"]["fallas"] == 0


def test_cierra_el_aviso_al_recuperarse():
    cuentas, _, recuperadas = vg.actualizar({"bhd": {"fallas": 4, "aviso": 12}}, {"bhd": "ok"})
    assert recuperadas == [("bhd", 12)] and cuentas["bhd"] == {"fallas": 0, "aviso": None}


def test_fuente_vieja_tambien_cuenta_y_enlace_no():
    cuentas = {}
    for _ in range(3):
        cuentas, avisar, _ = vg.actualizar(cuentas, {"vimenca": "vieja: la fuente no actualiza", "banreservas": "enlace"})
    assert [a[0] for a in avisar] == ["vimenca"]
