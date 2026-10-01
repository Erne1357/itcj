# `static/js/vendor/` — dependencias de terceros de Calidad

Se sirven **desde este host**, nunca desde un CDN. Cada archivo lleva la versión
en el nombre; actualizar = añadir el archivo nuevo, cambiar la referencia en el
template y borrar el viejo.

## `xlsx-0.20.3.mini.min.js`

* **Qué es:** SheetJS Community Edition, build *mini* (lee/escribe XLSX; no trae
  los formatos heredados ni las tablas de codepage del build `full`).
* **Origen:** `https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.mini.min.js`
* **Descargado:** 2026-08-25
* **SHA-256:** `0cb353f830d7288385492c83d277b058ddeac664ca51cf1393aa1fd3e2b70939`
* **Tamaño:** 279 523 bytes
* **Lo usa:** `js/reports/report-view.js` (`XLSX.utils.table_to_book` +
  `XLSX.writeFile`), cargado solo en `/adhoc/reportes/{tipo}`.

**Por qué está aquí y no en un CDN.** Los cinco reportes del legacy lo cargaban
de `https://cdn.sheetjs.com/xlsx-latest/package/dist/xlsx.full.min.js`: la
etiqueta **`latest`**, sin versión fija y sin SRI. Cualquier cambio en ese
recurso —legítimo o no— se ejecutaba con la sesión del usuario que abriera un
reporte, y la política de CSP del proyecto no lo cubría. Con el archivo en el
propio host la versión es reproducible, el hash es verificable y la página deja
de tener una dependencia de red externa.

Se eligió el build **mini** (280 KB) sobre el **full** (952 KB): las dos
funciones que se usan están en los dos, y el reporte no lee archivos ni maneja
formatos antiguos.
