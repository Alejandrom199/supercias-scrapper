"""
Lógica de descarga de estados financieros Supercias (Playwright).
Usada por la UI; no requiere Jupyter.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# Mapeo completo: Alias en el programa (izquierda) -> Término de búsqueda en la Supercias (derecha)
ALIAS_BUSQUEDA = {
    # ALIAS VISUAL - NOMBRE BUSQUEDA
    "ADVFIN": "ADVFIN S.A",
    "ALBION": "ALBION",
    "ANALYTICA": "ANALYTICA",
    "ANDESCAPITAL": "ANDESCAPITAL",
    "ASESOVAL": "ASESOVAL",
    "ATLANTIDA": "ATLANTIDA",
    "REAL CASA": "REAL CASA",
    "ECUABURSATIL": "ECUABURSATIL",
    "EQUITY": "EQUITY",
    "FIDUVALOR": "FIDUVALOR",
    "FUTUROCAPITAL": "FUTUROCAPITAL",
    "INTERVALORES": "INTERVALORES",
    "KAPITAL ONE": "KAPITAL ONE",
    "LATINUM": "LATINUM",
    "MASVALORES": "MASVALORES",
    "MERCAPITAL": "MERCAPITAL",
    "MERCHANTVALORES": "MERCHANTVALORES",
    "METROVALORES": "METROVALORES",
    "ORION": "ORION",
    "PICAVAL": "PICAVAL",
    "PLUSBURSATIL": "PLUSBURSATIL",
    "PLUSVALORES": "PLUSVALORES",
    "PROBROKERS": "PROBROKERS",
    "SANTA FE": "SANTA FE",
    "SILVERCROSS": "SILVERCROSS",
    "SMARTCAPITAL": "SMARTCAPITAL",
    "VALUE S.A": "VALUE",
    "VECTORGLOBAL": "VECTORGLOBAL",
}

CASAS_DEFAULT = list(ALIAS_BUSQUEDA.keys())

MESES = {
    "01": "Enero",
    "02": "Febrero",
    "03": "Marzo",
    "04": "Abril",
    "05": "Mayo",
    "06": "Junio",
    "07": "Julio",
    "08": "Agosto",
    "09": "Septiembre",
    "10": "Octubre",
    "11": "Noviembre",
    "12": "Diciembre",
}

ESTADOS_FINALES = {"OK", "NO_CASA", "NO_ESTADO_FINANCIERO"}

LogFn = Callable[[str], None]
ResultFn = Callable[[dict], None]


def carpeta_para_fecha(carpeta_base: str, fecha: str) -> str:
    anio, mes = fecha.split("-")
    return os.path.join(carpeta_base, f"{MESES[mes]}_{anio}")


def preparar_carpetas(carpeta_base: str, fechas: list[str]) -> dict[str, str]:
    carpetas = {fecha: carpeta_para_fecha(carpeta_base, fecha) for fecha in fechas}
    for ruta in carpetas.values():
        os.makedirs(ruta, exist_ok=True)
    return carpetas


def _dialogos_procesando(page):
    return page.locator(".ui-dialog").filter(has_text="Procesando")


def _hay_procesando_visible(page) -> bool:
    for loc in (_dialogos_procesando(page), page.locator("#dlgProcesando_modal")):
        try:
            for i in range(loc.count()):
                if loc.nth(i).is_visible():
                    return True
        except Exception:
            continue
    return False


def esperar_procesando(
    page, timeout_ms: int = 30000, espera_aparicion_ms: int = 0
) -> None:
    """Espera a que desaparezca el diálogo 'Procesando' de PrimeFaces/JSF.

    Si espera_aparicion_ms es mayor a cero, primero aguarda a que el diálogo
    llegue a mostrarse. El filtro de las tablas lo abre recién ~1 s después
    de la última tecla; sin esa espera esta función sale al instante.
    """
    if espera_aparicion_ms > 0:
        limite = time.time() + espera_aparicion_ms / 1000
        while time.time() < limite:
            if _hay_procesando_visible(page):
                break
            page.wait_for_timeout(200)

    fin = time.time() + timeout_ms / 1000
    while time.time() < fin:
        if not _hay_procesando_visible(page):
            break
        page.wait_for_timeout(250)
    page.wait_for_timeout(400)


def _texto_sin_resultados(texto: str) -> bool:
    t = texto.lower()
    return "no se ha encontrado" in t or "no se encontraron" in t


def tabla_sin_resultados(page, tbody) -> bool:
    """Confirma el mensaje de tabla vacía ya con el AJAX terminado.

    PrimeFaces muestra ese texto mientras la búsqueda todavía no responde.
    Se lee dos veces para no tratar esa pausa como un resultado definitivo.
    """
    for _ in range(2):
        if _hay_procesando_visible(page):
            esperar_procesando(page, timeout_ms=30000, espera_aparicion_ms=2000)
        try:
            texto = tbody.inner_text(timeout=3000)
        except Exception:
            return False
        if not _texto_sin_resultados(texto):
            return False
        page.wait_for_timeout(800)
    return True


def escribir_filtro_primefaces(page, locator, texto: str) -> None:
    """Escribe en un filtro de columna de PrimeFaces y espera el refresco.

    Esas columnas filtran con keyup, un segundo después de la última tecla.
    fill() no emite keyup, y Enter lo bloquea la propia tabla.
    """
    campo = locator.first
    campo.wait_for(state="visible", timeout=20000)
    campo.click()
    campo.press("Control+A")
    campo.press_sequentially(texto, delay=40)
    esperar_procesando(page, timeout_ms=45000, espera_aparicion_ms=4000)


def cerrar_pdf_listado_si_esta_abierto(page) -> None:
    """Cierra el PDF del listado si quedó encima de la tabla de casas."""
    dlg = page.locator("#dlgPresentarListadoEntesMvPdf")
    try:
        if dlg.count() == 0 or not dlg.first.is_visible():
            return
        cerrar = dlg.locator(".ui-dialog-titlebar-close")
        if cerrar.count():
            click_js(cerrar.first)
        else:
            page.keyboard.press("Escape")
        dlg.first.wait_for(state="hidden", timeout=5000)
    except Exception:
        pass


def mostrar_todas_las_filas(page) -> None:
    """Sube el paginador al máximo para que la casa no quede fuera de la página 1."""
    selector = page.locator("select.ui-paginator-rpp-options").first
    try:
        selector.wait_for(state="visible", timeout=8000)
    except PlaywrightTimeoutError:
        return

    mejor = None
    mejor_n = -1
    opciones = selector.locator("option")
    for i in range(opciones.count()):
        valor = opciones.nth(i).get_attribute("value") or ""
        try:
            n = int(valor)
        except ValueError:
            continue
        if n > mejor_n:
            mejor_n = n
            mejor = valor
    if not mejor:
        return
    try:
        if selector.input_value() == mejor:
            return
        selector.select_option(mejor)
    except Exception:
        return
    esperar_procesando(page, timeout_ms=45000, espera_aparicion_ms=5000)


def _condicion_nombre(casa: str, termino: str) -> str:
    terminos: list[str] = []
    for candidato in (termino, casa):
        texto = (candidato or "").upper().strip()
        if texto and texto not in terminos:
            terminos.append(texto)
    return " or ".join(
        "contains(translate(., 'abcdefghijklmnopqrstuvwxyz', "
        f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), '{texto}')"
        for texto in terminos
    )


def localizar_fila_casa(page, casa: str, termino: str):
    """Fila del listado. Si hay inscripción vigente y cancelada, usa la vigente."""
    condicion = _condicion_nombre(casa, termino)
    base = f"//tbody[contains(@id,':tblEntesMv_data')]/tr[({condicion})"
    vigente = page.locator(f"xpath={base} and contains(.,'VIGENTE')]").first
    try:
        vigente.wait_for(state="visible", timeout=15000)
        return vigente
    except PlaywrightTimeoutError:
        cualquiera = page.locator(f"xpath={base}]").first
        cualquiera.wait_for(state="visible", timeout=3000)
        return cualquiera


def localizar_fila_corte(page, fecha: str):
    """Fila del estado financiero. El corte mensual viene como AAAA-MM-DD."""
    base = "//tbody[contains(@id,'tblEstadosFinancierosEntregados')]/tr"
    mensual = page.locator(
        f"xpath={base}[contains(.,'{fecha}') and contains(.,'MENSUAL')]"
    ).first
    try:
        mensual.wait_for(state="visible", timeout=12000)
        return mensual
    except PlaywrightTimeoutError:
        cualquiera = page.locator(f"xpath={base}[contains(.,'{fecha}')]").first
        cualquiera.wait_for(state="visible", timeout=3000)
        return cualquiera


def click_js(locator) -> None:
    """Clic por JS en el enlace/botón (evita overlays y wait-for-load de JSF)."""
    locator.evaluate(
        "node => { const t = node.closest('a,button') || node; t.click(); }"
    )


def abrir_nueva_pagina(context, locator, timeout: int = 30000):
    """Clic y espera la pestaña que abre PrimeFaces vía AJAX."""
    with context.expect_page(timeout=timeout) as info:
        try:
            locator.first.click(timeout=8000)
        except Exception:
            click_js(locator.first)
    nueva = info.value
    try:
        nueva.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass
    esperar_procesando(nueva)
    return nueva


def click_boton_excel(page, timeout_por_intento: int = 5, intentos_totales: int = 6) -> None:
    locator_boton = page.locator(
        "//span[contains(@class,'ui-button-text') and normalize-space(.)='EXCEL']"
        "/ancestor::*[self::button or self::a][1]"
    )
    modal = page.locator("#dlgProcesando_modal")
    fin = time.time() + intentos_totales * timeout_por_intento

    while time.time() < fin:
        for i in range(locator_boton.count()):
            el = locator_boton.nth(i)
            try:
                if not el.is_visible() or not el.is_enabled():
                    continue
            except Exception:
                continue

            try:
                el.evaluate("node => node.click()")
            except Exception:
                continue

            try:
                modal.wait_for(state="visible", timeout=timeout_por_intento * 1000)
                modal.wait_for(state="hidden", timeout=30000)
                return
            except PlaywrightTimeoutError:
                if not _hay_procesando_visible(page):
                    return
                continue

        page.wait_for_timeout(500)

    raise PlaywrightTimeoutError(
        "Ningún botón EXCEL encontrado disparó el modal de procesamiento."
    )


def ejecutar_extraccion_single(
    casa: str,
    fecha: str,
    carpeta_descarga: str,
    navegador: str = "chrome",
) -> dict:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.set_event_loop(asyncio.new_event_loop())

    with sync_playwright() as p:
        opciones_navegador: dict = {"headless": False}
        if navegador:
            opciones_navegador["channel"] = navegador
        browser = p.chromium.launch(**opciones_navegador)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(30000)

        try:
            page.goto(
                "https://appscvsmovil.supercias.gob.ec/PortalInformacion/mercado_valores.html",
                wait_until="domcontentloaded",
            )

            # Catastro público navega a una página JSF que no dispara 'load'.
            page.locator("xpath=//img[contains(@src,'cat_pub.png')]").click(
                no_wait_after=True
            )
            loc_casas = page.locator("xpath=//img[contains(@src,'casas_valores.png')]")
            loc_casas.first.wait_for(state="visible", timeout=45000)
            esperar_procesando(page)

            page_casas = abrir_nueva_pagina(context, loc_casas)
            cerrar_pdf_listado_si_esta_abierto(page_casas)

            tbody_casas = page_casas.locator(
                "xpath=//tbody[contains(@id,':tblEntesMv_data')]"
            )
            tbody_casas.wait_for(state="visible", timeout=20000)
            mostrar_todas_las_filas(page_casas)
            cerrar_pdf_listado_si_esta_abierto(page_casas)

            termino_busqueda = ALIAS_BUSQUEDA.get(casa, casa)
            buscador = page_casas.locator(
                "xpath=//th[contains(.,'Nombre') or contains(.,'Social') or contains(.,'Razón')]"
                "//input[contains(@id,':filter')]"
            )
            escribir_filtro_primefaces(page_casas, buscador, termino_busqueda)

            if tabla_sin_resultados(page_casas, tbody_casas):
                return {
                    "casa": casa,
                    "fecha": fecha,
                    "estado": "NO_CASA",
                    "error": "Casa no registrada en el Catastro de la Supercias",
                    "archivo": None,
                }

            try:
                fila_casa = localizar_fila_casa(page_casas, casa, termino_busqueda)
            except PlaywrightTimeoutError:
                return {
                    "casa": casa,
                    "fecha": fecha,
                    "estado": "NO_CASA",
                    "error": "Casa no registrada en el Catastro de la Supercias",
                    "archivo": None,
                }

            # Localiza el enlace 'más información' (lupa / hoja) de la fila encontrada
            link_detalle = fila_casa.locator(
                "xpath=.//a[contains(@class,'ui-commandlink') or .//img[contains(@src,'mas_informacion')]]"
            ).first
            link_detalle.wait_for(state="visible", timeout=8000)

            page_detalle = abrir_nueva_pagina(context, link_detalle)

            acordeon = page_detalle.locator(
                "xpath=//div[contains(@class,'ui-accordion-header') "
                "and contains(.,'Información periódica')]"
            )
            acordeon.first.wait_for(state="visible", timeout=20000)
            click_js(acordeon.first)

            menu_ef = page_detalle.locator("id=acordionMenuMv:menuEstadosFinancieros")
            menu_ef.wait_for(state="visible", timeout=15000)
            click_js(menu_ef)
            esperar_procesando(
                page_detalle, timeout_ms=45000, espera_aparicion_ms=5000
            )

            buscador_fecha = page_detalle.locator(
                "xpath=//th[contains(.,'Fecha de corte')]"
                "//input[contains(@id,':filter')]"
            )
            escribir_filtro_primefaces(page_detalle, buscador_fecha, fecha)

            tbody_ef = page_detalle.locator(
                "xpath=//tbody[contains(@id,'tblEstadosFinancierosEntregados')]"
            )
            if tabla_sin_resultados(page_detalle, tbody_ef):
                return {
                    "casa": casa,
                    "fecha": fecha,
                    "estado": "NO_ESTADO_FINANCIERO",
                    "error": "Casa no encontrada en ese período",
                    "archivo": None,
                }

            try:
                fila_fecha = localizar_fila_corte(page_detalle, fecha)
            except PlaywrightTimeoutError:
                return {
                    "casa": casa,
                    "fecha": fecha,
                    "estado": "NO_ESTADO_FINANCIERO",
                    "error": "Casa no encontrada en ese período",
                    "archivo": None,
                }
            icono_preview = fila_fecha.locator(
                "xpath=.//img[contains(@src,'mas_informacion.png')]"
            )
            try:
                icono_preview.first.wait_for(state="visible", timeout=8000)
            except PlaywrightTimeoutError:
                return {
                    "casa": casa,
                    "fecha": fecha,
                    "estado": "NO_ESTADO_FINANCIERO",
                    "error": "Casa no encontrada en ese período",
                    "archivo": None,
                }

            page_preview = page_detalle
            try:
                with context.expect_page(timeout=8000) as preview_info:
                    click_js(icono_preview.first)
                page_preview = preview_info.value
                try:
                    page_preview.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
            except PlaywrightTimeoutError:
                pass
            esperar_procesando(page_preview)

            boton_excel = page_preview.locator(
                "//span[contains(@class,'ui-button-text') and normalize-space(.)='EXCEL']"
                "/ancestor::*[self::button or self::a][1]"
            )
            boton_excel.first.wait_for(state="visible", timeout=20000)

            with page_preview.expect_download(timeout=90000) as download_info:
                click_boton_excel(page_preview)

            descarga = download_info.value
            ruta_final = os.path.join(carpeta_descarga, descarga.suggested_filename)
            descarga.save_as(ruta_final)

            return {
                "casa": casa,
                "fecha": fecha,
                "estado": "OK",
                "error": None,
                "archivo": ruta_final,
            }

        except PlaywrightTimeoutError:
            return {
                "casa": casa,
                "fecha": fecha,
                "estado": "TIMEOUT",
                "error": "La página tardó demasiado en responder",
                "archivo": None,
            }
        except Exception as e:
            return {
                "casa": casa,
                "fecha": fecha,
                "estado": "ERROR_UNHANDLED",
                "error": str(e),
                "archivo": None,
            }
        finally:
            context.close()
            browser.close()


def procesar_tarea_con_reintentos(
    item: tuple[str, str],
    carpetas_fechas: dict[str, str],
    carpeta_base: str,
    max_intentos: int = 3,
    log: LogFn | None = None,
    should_stop: Callable[[], bool] | None = None,
    navegador: str = "chrome",
) -> dict:
  casa, fecha = item
  carpeta_descarga = carpetas_fechas.get(fecha, carpeta_base)
  res = {
      "casa": casa,
      "fecha": fecha,
      "estado": "CANCELADO",
      "error": "Cancelado por el usuario",
      "archivo": None,
  }
  _log = log or (lambda _m: None)
  _stop = should_stop or (lambda: False)

  for intento in range(1, max_intentos + 1):
    # Si se pulsó Detener, salir inmediatamente sin abrir Chrome
    if _stop():
      _log(f"⏸ Omitido por detención: {casa} | {fecha}")
      return {
          "casa": casa,
          "fecha": fecha,
          "estado": "CANCELADO",
          "error": "Detenido por el usuario",
          "archivo": None,
      }

    _log(f"→ Intento {intento}/{max_intentos}: {casa} | {fecha}")
    res = ejecutar_extraccion_single(
        casa, fecha, carpeta_descarga, navegador=navegador
    )

    if res["estado"] in ESTADOS_FINALES:
      _log(f"← {res['estado']}: {casa} | {fecha}")
      return res

    if _stop():
      break

    _log(f"Reintentando {casa} ({res.get('error')})")
    time.sleep(2)

  _log(f"✗ Error definitivo: {casa} | {fecha}: {res.get('error')}")
  return res


def ejecutar_lote(
    casas: list[str],
    fechas: list[str],
    carpeta_base: str,
    max_workers: int = 1,
    max_intentos: int = 3,
    log: LogFn | None = None,
    on_result: ResultFn | None = None,
    should_stop: Callable[[], bool] | None = None,
    navegador: str = "chrome",
) -> pd.DataFrame:
  """Ejecuta el lote en paralelo y devuelve el DataFrame de resultados."""
  _log = log or (lambda _m: None)
  _on_result = on_result or (lambda _r: None)
  _stop = should_stop or (lambda: False)

  carpetas = preparar_carpetas(carpeta_base, fechas)
  tareas = [(casa, fecha) for casa in sorted(set(casas)) for fecha in fechas]
  _log(f"Iniciando {len(tareas)} descargas (navegadores: {max_workers})")

  resultados: list[dict] = []

  with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futuros = {
        executor.submit(
            procesar_tarea_con_reintentos,
            item,
            carpetas,
            carpeta_base,
            max_intentos,
            log,
            should_stop=_stop,
            navegador=navegador,
        ): item
        for item in tareas
    }

    for futuro in as_completed(futuros):
      if _stop():
        _log("Detención solicitada; cancelando pendientes...")
        executor.shutdown(wait=False, cancel_futures=True)
        break
      try:
        res = futuro.result()
      except Exception as e:
        casa, fecha = futuros[futuro]
        res = {
            "casa": casa,
            "fecha": fecha,
            "estado": "ERROR_UNHANDLED",
            "error": str(e),
            "archivo": None,
        }
      resultados.append(res)
      _on_result(res)

  df = pd.DataFrame(resultados)
  if not df.empty:
    df = df.sort_values(["casa", "fecha"]).reset_index(drop=True)
  return df


def guardar_reporte(df: pd.DataFrame, ruta: str) -> str:
    df.to_excel(ruta, index=False)
    return ruta