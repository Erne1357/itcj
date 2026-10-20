-- Datos académicos del alumno (esquema inventado, solo pruebas).
SELECT a.no_de_control,
       a.nombre, a.apellido_paterno, a.apellido_materno,
       a.carrera, a.anio_ingreso, a.estatus,
       a.creditos_aprobados, a.creditos_carrera,
       a.servicio_social, a.residencia
  FROM alumnos a
 WHERE a.no_de_control = ?
