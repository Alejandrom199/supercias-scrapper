# Estados financieros Supercias

Programa de escritorio para descargar los estados financieros de las casas de valores desde el portal de la Superintendencia de Compañías.

## Advertencia

Usa **1 navegador**. Si abres más de uno a la vez, la Supercias puede bloquear tu acceso de forma temporal. La ventana arranca en 1 y pide confirmación si subes ese número.

## Qué descargar

En la release **1.1.1** descarga solo `Supercias-1.1.1.zip`. Al descomprimirlo queda la carpeta del programa, con `Abrir_Supercias.bat`, la guía, este README y `requirements_ui.txt`.

`app_supercias.py` y `supercias_core.py` van dentro de ese zip porque el `.bat` los abre. No hay un ejecutable aparte: el acceso directo lanza esos dos archivos.

## Instalación

Dentro de la carpeta descomprimida:

```
python -m pip install -r requirements_ui.txt
python -m playwright install chromium
```

El segundo comando hace falta si vas a usar la opción Chromium. Con Google Chrome o Microsoft Edge basta el primero, siempre que ese navegador esté instalado.

## Uso

1. Abre `Abrir_Supercias.bat`.
2. Elige la carpeta donde se guardarán los Excel.
3. Escribe el período como `AAAA-MM`. Ejemplo: `2026-10`.
4. Deja Navegadores en 1.
5. Elige Google Chrome, Microsoft Edge o Chromium.
6. Marca las casas y pulsa Iniciar descarga. No cierres la ventana mientras trabaja.

Los Excel quedan en una subcarpeta del mes, por ejemplo `Octubre_2026`.
