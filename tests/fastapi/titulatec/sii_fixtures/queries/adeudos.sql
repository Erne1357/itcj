-- Adeudos vigentes (esquema inventado, solo pruebas).
SELECT d.concepto, d.monto
  FROM adeudos d
 WHERE d.no_de_control = ?
   AND d.pagado = 'N'
