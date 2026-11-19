"""UI de escritorio para descargar estados financieros Supercias.

Ejecutar:  python app_supercias.py o py app_supercias.py
"""

from __future__ import annotations

from datetime import datetime
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from supercias_core import (
    CASAS_DEFAULT,
    ejecutar_lote,
    guardar_reporte,
)

# Apariencia: clara, institucional (sin morados)
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

COLOR_BG = "#F4F6F8"
COLOR_CARD = "#FFFFFF"
COLOR_PRIMARY = "#0B3A5B"
COLOR_ACCENT = "#1A7A6D"
COLOR_BORDER = "#D5DDE5"
COLOR_TEXT = "#1C2430"
COLOR_MUTED = "#5C6B7A"
COLOR_OK = "#1B7F4E"
COLOR_WARN = "#B45309"
COLOR_ERR = "#B42318"

DEFAULT_CARPETA = ""

# Etiqueta visible -> canal de Playwright. Vacío usa el Chromium que instala Playwright.
NAVEGADORES_UI = {
    "Google Chrome": "chrome",
    "Microsoft Edge": "msedge",
    "Chromium": "",
}


class App(ctk.CTk):

  def __init__(self) -> None:
    super().__init__()
    self.title("Estados financieros · Supercias")
    self.minsize(820, 520)
    self.after(0, lambda: self.state("zoomed"))  # Maximiza en Windows
    self.configure(fg_color=COLOR_BG)

    self._msg_queue: queue.Queue = queue.Queue()
    self._stop_flag = threading.Event()
    self._worker: threading.Thread | None = None
    self._resultados: list[dict] = []
    self._casa_vars: dict[str, ctk.BooleanVar] = {}
    self._total = 0
    self._hechos = 0
    self._last_df = None

    self._build()
    self.after(120, self._drain_queue)

  # ------------------------------------------------------------------ UI
  def _build(self) -> None:
    header = ctk.CTkFrame(self, fg_color=COLOR_PRIMARY, corner_radius=0, height=50)
    header.pack(fill="x")
    header.pack_propagate(False)
    ctk.CTkLabel(
        header,
        text="Descarga de estados financieros",
        font=ctk.CTkFont(family="Segoe UI Semibold", size=18),
        text_color="#FFFFFF",
    ).pack(side="left", padx=16, pady=8)
    ctk.CTkLabel(
        header,
        text="Superintendencia de Compañías",
        font=ctk.CTkFont(family="Segoe UI", size=12),
        text_color="#B8D0E2",
    ).pack(side="right", padx=16)

    body = ctk.CTkFrame(self, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=12, pady=10)
    body.grid_columnconfigure(0, weight=2)
    body.grid_columnconfigure(1, weight=3)
    body.grid_rowconfigure(0, weight=1)

    left = ctk.CTkFrame(
        body,
        fg_color=COLOR_CARD,
        corner_radius=10,
        border_width=1,
        border_color=COLOR_BORDER,
    )
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    right = ctk.CTkFrame(
        body,
        fg_color=COLOR_CARD,
        corner_radius=10,
        border_width=1,
        border_color=COLOR_BORDER,
    )
    right.grid(row=0, column=1, sticky="nsew")

    self._build_config(left)
    self._build_progress(right)

  def _section(self, parent, title: str) -> ctk.CTkFrame:
    box = ctk.CTkFrame(parent, fg_color="transparent")
    box.pack(fill="x", padx=12, pady=(8, 0))
    ctk.CTkLabel(
        box,
        text=title,
        font=ctk.CTkFont(family="Segoe UI Semibold", size=12),
        text_color=COLOR_PRIMARY,
        anchor="w",
    ).pack(fill="x")
    return box

  def _build_config(self, parent: ctk.CTkFrame) -> None:
    ctk.CTkLabel(
        parent,
        text="Configuración",
        font=ctk.CTkFont(family="Segoe UI Semibold", size=15),
        text_color=COLOR_TEXT,
        anchor="w",
    ).pack(fill="x", padx=12, pady=(10, 2))

    # Carpeta
    sec = self._section(parent, "Carpeta de descarga")
    row = ctk.CTkFrame(sec, fg_color="transparent")
    row.pack(fill="x", pady=(3, 0))
    self.var_carpeta = ctk.StringVar(value=DEFAULT_CARPETA)
    ctk.CTkEntry(
        row,
        textvariable=self.var_carpeta,
        placeholder_text="Selecciona una carpeta para guardar las descargas...",
        height=30,
        font=ctk.CTkFont(size=11),
    ).pack(side="left", fill="x", expand=True, padx=(0, 6))
    ctk.CTkButton(
        row,
        text="Examinar",
        width=85,
        height=30,
        fg_color=COLOR_PRIMARY,
        hover_color="#0A2F4A",
        command=self._elegir_carpeta,
    ).pack(side="right")

    # Contenedor fila para Período y Navegadores juntos (ahorro de espacio)
    row_params = ctk.CTkFrame(parent, fg_color="transparent")
    row_params.pack(fill="x", padx=12, pady=(6, 0))
    row_params.grid_columnconfigure(0, weight=1)
    row_params.grid_columnconfigure(1, weight=1)

    # Período
    col_f = ctk.CTkFrame(row_params, fg_color="transparent")
    col_f.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    ctk.CTkLabel(
        col_f,
        text="Período (AAAA-MM)",
        font=ctk.CTkFont(family="Segoe UI Semibold", size=12),
        text_color=COLOR_PRIMARY,
        anchor="w",
    ).pack(fill="x")
    hoy = datetime.now()
    sugerida = f"{hoy.year}-{hoy.month:02d}"
    self.var_fecha = ctk.StringVar(value="2026-07")
    ctk.CTkEntry(
        col_f,
        textvariable=self.var_fecha,
        height=30,
        placeholder_text=sugerida,
        font=ctk.CTkFont(size=12),
    ).pack(fill="x", pady=(3, 0))

    # Navegadores
    col_w = ctk.CTkFrame(row_params, fg_color="transparent")
    col_w.grid(row=0, column=1, sticky="ew", padx=(6, 0))
    top_w = ctk.CTkFrame(col_w, fg_color="transparent")
    top_w.pack(fill="x")
    ctk.CTkLabel(
        top_w,
        text="Navegadores",
        font=ctk.CTkFont(family="Segoe UI Semibold", size=12),
        text_color=COLOR_PRIMARY,
        anchor="w",
    ).pack(side="left")
    self.lbl_workers = ctk.CTkLabel(
        top_w,
        text="1",
        font=ctk.CTkFont(size=11),
        text_color=COLOR_MUTED,
    )
    self.lbl_workers.pack(side="right")
    self.var_workers = ctk.IntVar(value=1)
    ctk.CTkSlider(
        col_w,
        from_=1,
        to=4,
        number_of_steps=3,
        variable=self.var_workers,
        progress_color=COLOR_ACCENT,
        button_color=COLOR_ACCENT,
        button_hover_color="#156357",
        command=lambda v: self.lbl_workers.configure(text=str(int(float(v)))),
    ).pack(fill="x", pady=(5, 0))

    ctk.CTkLabel(
        col_w,
        text="Navegador",
        font=ctk.CTkFont(family="Segoe UI Semibold", size=12),
        text_color=COLOR_PRIMARY,
        anchor="w",
    ).pack(fill="x", pady=(8, 0))
    self.var_navegador = ctk.StringVar(value="Google Chrome")
    ctk.CTkOptionMenu(
        col_w,
        variable=self.var_navegador,
        values=list(NAVEGADORES_UI),
        height=30,
        font=ctk.CTkFont(size=12),
        fg_color=COLOR_PRIMARY,
        button_color=COLOR_PRIMARY,
        button_hover_color="#0A2F4A",
    ).pack(fill="x", pady=(3, 0))

    ctk.CTkLabel(
        parent,
        text=(
            "Más de 1 navegador a la vez puede hacer que la Supercias "
            "bloquee tu acceso de forma temporal."
        ),
        font=ctk.CTkFont(size=11),
        text_color=COLOR_WARN,
        wraplength=340,
        justify="left",
        anchor="w",
    ).pack(fill="x", padx=12, pady=(8, 0))

    # Casas
    sec = self._section(parent, "Casas de valores")
    tools = ctk.CTkFrame(sec, fg_color="transparent")
    tools.pack(fill="x", pady=(4, 2))
    ctk.CTkButton(
        tools,
        text="Todas",
        width=60,
        height=24,
        font=ctk.CTkFont(size=11),
        fg_color=COLOR_ACCENT,
        hover_color="#156357",
        command=lambda: self._set_casas(True),
    ).pack(side="left", padx=(0, 4))
    ctk.CTkButton(
        tools,
        text="Ninguna",
        width=65,
        height=24,
        font=ctk.CTkFont(size=11),
        fg_color="#6B7C8C",
        hover_color="#556473",
        command=lambda: self._set_casas(False),
    ).pack(side="left")

    scroll = ctk.CTkScrollableFrame(
        parent,
        fg_color="#F8FAFC",
        corner_radius=6,
        border_width=1,
        border_color=COLOR_BORDER,
        height=150,  # Compactado
    )
    scroll.pack(fill="both", expand=True, padx=12, pady=(4, 8))
    scroll.grid_columnconfigure(0, weight=1)
    scroll.grid_columnconfigure(1, weight=1)

    # Distribución en 2 columnas para optimizar espacio
    for idx, casa in enumerate(CASAS_DEFAULT):
      var = ctk.BooleanVar(value=True)
      self._casa_vars[casa] = var
      chk = ctk.CTkCheckBox(
          scroll,
          text=casa,
          variable=var,
          font=ctk.CTkFont(size=11),
          text_color=COLOR_TEXT,
          fg_color=COLOR_ACCENT,
          hover_color="#156357",
          border_color="#9AA8B5",
      )
      chk.grid(row=idx // 2, column=idx % 2, sticky="w", pady=1, padx=3)

    # Botones acción
    actions = ctk.CTkFrame(parent, fg_color="transparent")
    actions.pack(fill="x", padx=12, pady=(0, 10))
    self.btn_iniciar = ctk.CTkButton(
        actions,
        text="Iniciar descarga",
        height=36,
        font=ctk.CTkFont(family="Segoe UI Semibold", size=13),
        fg_color=COLOR_ACCENT,
        hover_color="#156357",
        command=self._iniciar,
    )
    self.btn_iniciar.pack(side="left", fill="x", expand=True, padx=(0, 6))
    self.btn_detener = ctk.CTkButton(
        actions,
        text="Detener",
        height=36,
        width=95,
        font=ctk.CTkFont(size=12),
        fg_color="#8B1E1E",
        hover_color="#6F1717",
        state="disabled",
        command=self._detener,
    )
    self.btn_detener.pack(side="right")

  def _build_progress(self, parent: ctk.CTkFrame) -> None:
    ctk.CTkLabel(
        parent,
        text="Progreso y resultados",
        font=ctk.CTkFont(family="Segoe UI Semibold", size=15),
        text_color=COLOR_TEXT,
        anchor="w",
    ).pack(fill="x", padx=12, pady=(10, 4))

    self.lbl_estado = ctk.CTkLabel(
        parent,
        text="Listo para iniciar",
        font=ctk.CTkFont(size=12),
        text_color=COLOR_MUTED,
        anchor="w",
    )
    self.lbl_estado.pack(fill="x", padx=12)

    self.progress = ctk.CTkProgressBar(
        parent,
        height=10,
        progress_color=COLOR_ACCENT,
        fg_color="#E2E8F0",
    )
    self.progress.pack(fill="x", padx=12, pady=(4, 2))
    self.progress.set(0)

    # Conteo y resumen en la misma fila
    stats_row = ctk.CTkFrame(parent, fg_color="transparent")
    stats_row.pack(fill="x", padx=12, pady=(2, 4))
    self.resumen = ctk.CTkLabel(
        stats_row,
        text="OK: 0   ·   Otros: 0",
        font=ctk.CTkFont(size=11),
        text_color=COLOR_TEXT,
        anchor="w",
    )
    self.resumen.pack(side="left")
    self.lbl_conteo = ctk.CTkLabel(
        stats_row,
        text="0 / 0",
        font=ctk.CTkFont(size=11),
        text_color=COLOR_MUTED,
        anchor="e",
    )
    self.lbl_conteo.pack(side="right")

    # Log de actividad
    ctk.CTkLabel(
        parent,
        text="Actividad",
        font=ctk.CTkFont(family="Segoe UI Semibold", size=12),
        text_color=COLOR_PRIMARY,
        anchor="w",
    ).pack(fill="x", padx=12)
    self.txt_log = ctk.CTkTextbox(
        parent,
        height=85,  # Compactado
        font=ctk.CTkFont(family="Consolas", size=11),
        fg_color="#0F172A",
        text_color="#E2E8F0",
        corner_radius=6,
    )
    self.txt_log.pack(fill="x", padx=12, pady=(3, 6))
    self.txt_log.configure(state="disabled")

    # Tabla resultados
    ctk.CTkLabel(
        parent,
        text="Resultados",
        font=ctk.CTkFont(family="Segoe UI Semibold", size=12),
        text_color=COLOR_PRIMARY,
        anchor="w",
    ).pack(fill="x", padx=12)

    self.tbl = ctk.CTkScrollableFrame(
        parent,
        fg_color="#F8FAFC",
        corner_radius=6,
        border_width=1,
        border_color=COLOR_BORDER,
    )
    self.tbl.pack(fill="both", expand=True, padx=12, pady=(3, 8))

    # Botones inferiores
    footer = ctk.CTkFrame(parent, fg_color="transparent")
    footer.pack(fill="x", padx=12, pady=(0, 10))
    ctk.CTkButton(
        footer,
        text="Abrir carpeta",
        height=32,
        font=ctk.CTkFont(size=12),
        fg_color=COLOR_PRIMARY,
        hover_color="#0A2F4A",
        command=self._abrir_carpeta,
    ).pack(side="left")
    ctk.CTkButton(
        footer,
        text="Exportar reporte Excel",
        height=32,
        font=ctk.CTkFont(size=12),
        fg_color="#334155",
        hover_color="#1E293B",
        command=self._exportar,
    ).pack(side="right")

  # -------------------------------------------------------------- helpers
  def _elegir_carpeta(self) -> None:
    ruta = filedialog.askdirectory(
        initialdir=self.var_carpeta.get() or os.path.expanduser("~")
    )
    if ruta:
      self.var_carpeta.set(ruta)

  def _set_casas(self, valor: bool) -> None:
    for var in self._casa_vars.values():
      var.set(valor)

  def _casas_seleccionadas(self) -> list[str]:
    return [c for c, v in self._casa_vars.items() if v.get()]

  def _log(self, msg: str) -> None:
    self._msg_queue.put(("log", msg))

  def _push_result(self, res: dict) -> None:
    self._msg_queue.put(("result", res))

  def _drain_queue(self) -> None:
    try:
      while True:
        kind, payload = self._msg_queue.get_nowait()
        if kind == "log":
          self._append_log(payload)
        elif kind == "result":
          self._add_result_row(payload)
        elif kind == "done":
          self._on_done(payload)
        elif kind == "status":
          self.lbl_estado.configure(text=payload)
    except queue.Empty:
      pass
    self.after(120, self._drain_queue)

  def _append_log(self, msg: str) -> None:
    self.txt_log.configure(state="normal")
    self.txt_log.insert("end", msg + "\n")
    self.txt_log.see("end")
    self.txt_log.configure(state="disabled")

  def _add_result_row(self, res: dict) -> None:
    self._resultados.append(res)
    self._hechos += 1
    if self._total:
      self.progress.set(self._hechos / self._total)
    self.lbl_conteo.configure(text=f"{self._hechos} / {self._total}")

    ok = sum(1 for r in self._resultados if r.get("estado") == "OK")
    otros = len(self._resultados) - ok
    self.resumen.configure(text=f"OK: {ok}   ·   Otros: {otros}")

    estado = res.get("estado", "")
    color = (
        COLOR_OK
        if estado == "OK"
        else (COLOR_WARN if estado.startswith("NO_") else COLOR_ERR)
    )
    row = ctk.CTkFrame(self.tbl, fg_color="transparent")
    row.pack(fill="x", pady=1)
    ctk.CTkLabel(
        row,
        text=res.get("casa", ""),
        width=130,
        anchor="w",
        font=ctk.CTkFont(size=11),
        text_color=COLOR_TEXT,
    ).pack(side="left")
    ctk.CTkLabel(
        row,
        text=estado,
        width=140,
        anchor="w",
        font=ctk.CTkFont(family="Segoe UI Semibold", size=11),
        text_color=color,
    ).pack(side="left")
    err = res.get("error") or ""
    if len(err) > 40:
      err = err[:37] + "…"
    ctk.CTkLabel(
        row,
        text=err,
        anchor="w",
        font=ctk.CTkFont(size=11),
        text_color=COLOR_MUTED,
    ).pack(side="left", fill="x", expand=True)

  def _limpiar_resultados(self) -> None:
    self._resultados.clear()
    self._hechos = 0
    for child in self.tbl.winfo_children():
      child.destroy()
    self.progress.set(0)
    self.resumen.configure(text="OK: 0   ·   Otros: 0")
    self.txt_log.configure(state="normal")
    self.txt_log.delete("1.0", "end")
    self.txt_log.configure(state="disabled")

  # -------------------------------------------------------------- run
  def _validar(self) -> tuple[str, str, list[str], int, str] | None:
    carpeta = self.var_carpeta.get().strip()
    fecha = self.var_fecha.get().strip()
    casas = self._casas_seleccionadas()
    workers = int(self.var_workers.get())

    if not carpeta:
      messagebox.showwarning(
          "Carpeta requerida",
          "Por favor selecciona una carpeta de descarga antes de iniciar.",
      )
      return None
    try:
      os.makedirs(carpeta, exist_ok=True)
    except Exception as e:
      messagebox.showerror(
          "Carpeta no válida",
          f"No se puede acceder o crear la carpeta indicada:\n{carpeta}\n\nDetalle: {e}",
      )
      return None
    if not re.fullmatch(r"\d{4}-\d{2}", fecha):
      messagebox.showwarning(
          "Fecha inválida", "Usa el formato AAAA-MM (ejemplo: 2026-07)."
      )
      return None
    mes = fecha.split("-")[1]
    if mes not in {f"{i:02d}" for i in range(1, 13)}:
      messagebox.showwarning("Mes inválido", "El mes debe estar entre 01 y 12.")
      return None
    if not casas:
      messagebox.showwarning(
          "Sin casas", "Selecciona al menos una casa de valores."
      )
      return None
    navegador = NAVEGADORES_UI.get(self.var_navegador.get())
    if navegador is None:
      messagebox.showwarning(
          "Navegador", "Elige Chrome, Edge o Chromium."
      )
      return None
    return carpeta, fecha, casas, workers, navegador

  def _iniciar(self) -> None:
    datos = self._validar()
    if not datos:
      return
    if self._worker and self._worker.is_alive():
      return

    carpeta, fecha, casas, workers, navegador = datos
    if workers > 1 and not messagebox.askokcancel(
        "Riesgo de bloqueo",
        "Vas a abrir más de un navegador a la vez.\n\n"
        "La Supercias puede bloquear tu acceso de forma temporal.\n\n"
        "¿Quieres continuar de todos modos?",
    ):
      return
    self._stop_flag.clear()
    self._limpiar_resultados()
    self._total = len(casas)
    self.lbl_conteo.configure(text=f"0 / {self._total}")
    self.lbl_estado.configure(text="Descargando… no cierres la ventana")
    self.btn_iniciar.configure(state="disabled")
    self.btn_detener.configure(state="normal")

    def runner() -> None:
      try:
        df = ejecutar_lote(
            casas=casas,
            fechas=[fecha],
            carpeta_base=carpeta,
            max_workers=workers,
            navegador=navegador,
            log=self._log,
            on_result=self._push_result,
            should_stop=self._stop_flag.is_set,
        )
        self._msg_queue.put(("done", df))
      except Exception as e:
        self._msg_queue.put(("log", f"Error general: {e}"))
        self._msg_queue.put(("done", None))

    self._worker = threading.Thread(target=runner, daemon=True)
    self._worker.start()

  def _detener(self) -> None:
    self._stop_flag.set()
    self.lbl_estado.configure(text="Deteniendo al terminar la tarea actual…")
    self._log("Solicitud de detención enviada")

  def _on_done(self, df) -> None:
    self.btn_iniciar.configure(state="normal")
    self.btn_detener.configure(state="disabled")
    if df is None:
      self.lbl_estado.configure(text="Finalizó con error")
      return
    ok = (
        int((df["estado"] == "OK").sum())
        if not df.empty and "estado" in df.columns
        else 0
    )
    self.lbl_estado.configure(text=f"Listo · {ok} Excel descargados")
    self._log(
        f"Proceso terminado. OK={ok} de {len(df) if df is not None else 0}"
    )
    self._last_df = df

  def _abrir_carpeta(self) -> None:
    carpeta = self.var_carpeta.get().strip()
    fecha = self.var_fecha.get().strip()
    destino = carpeta
    if re.fullmatch(r"\d{4}-\d{2}", fecha):
      from supercias_core import carpeta_para_fecha

      sub = carpeta_para_fecha(carpeta, fecha)
      if os.path.isdir(sub):
        destino = sub
    if not os.path.isdir(destino):
      messagebox.showinfo(
          "Carpeta", "La carpeta aún no existe. Ejecuta una descarga primero."
      )
      return
    if sys.platform == "win32":
      os.startfile(destino)  # type: ignore[attr-defined]
    else:
      subprocess.Popen(["xdg-open", destino])

  def _exportar(self) -> None:
    df = getattr(self, "_last_df", None)
    if df is None or df.empty:
      if self._resultados:
        import pandas as pd

        df = pd.DataFrame(self._resultados)
      else:
        messagebox.showinfo(
            "Sin datos", "Aún no hay resultados para exportar."
        )
        return
    periodo = self.var_fecha.get().strip() or "SinPeriodo"
    num_casas = len(df)
    fecha_hora = datetime.now().strftime("%Y%m%d-%H%M%S")
    nombre_sugerido = f"Reporte-{periodo}-{num_casas}-casas-{fecha_hora}.xlsx"

    ruta = filedialog.asksaveasfilename(
        defaultextension=".xlsx",
        filetypes=[("Excel", "*.xlsx")],
        initialfile=nombre_sugerido,
        initialdir=self.var_carpeta.get() or os.path.dirname(__file__),
    )
    if not ruta:
      return
    guardar_reporte(df, ruta)
    messagebox.showinfo("Reporte", f"Guardado en:\n{ruta}")


def main() -> None:
  app = App()
  app.mainloop()


if __name__ == "__main__":
  main()