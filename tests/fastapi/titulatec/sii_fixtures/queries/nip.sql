-- NIP del alumno (esquema inventado, solo pruebas). Jamás alimenta reglas ni hechos.
SELECT n.nip
  FROM alumnos_nip n
 WHERE n.no_de_control = ?
