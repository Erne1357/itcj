/**
 * incidents/incidents.js — configuración de INCIDENCIAS sobre `work/work-items.js`.
 *
 * Expone SOLO `window.AdhocIncidents` (IIFE, sin globales sueltas). Toda la
 * mecánica —listar, filtrar, paginar, alta masiva, edición, borrado— vive en la
 * base compartida; aquí queda únicamente lo que distingue a una incidencia de
 * un evento de programa, que en la práctica es: **nada**. Es el caso extremo
 * del colapso de duplicación del plan §6.5, y por eso este archivo cabe en una
 * pantalla mientras su equivalente legacy (`IncidenciasManager`) tenía 255
 * líneas casi idénticas a las 280 de `ProgramasManager`.
 *
 * Contrato consumido (`page_data`, lo arma `pages/incidents.py`):
 *   api        = /api/adhoc/v2/incidents
 *   tasks_url  = /adhoc/incidencias/{id}/tareas
 *   query_map  = {search: 'q', date_from: 'commitment_from', date_to: 'commitment_to'}
 *
 * Alta masiva: `POST /incidents` con `{"items": [...]}` (JSON). El legacy
 * mandaba diez listas paralelas por formulario y las recorría por índice, con
 * un índice 1-based solo para `priorities`.
 */
(function () {
    'use strict';

    var Base = window.AdhocWorkItems;

    if (!Base || typeof Base.register !== 'function') {
        console.error('[adhoc] incidents.js: falta work/work-items.js');
        return;
    }

    var instances = Base.register({
        kind: 'incident',

        // Sin campos extra: los doce del formulario base son exactamente los de
        // una incidencia. `location` y los adjuntos son cosa de programas.
        extraFields: [],

        // Sin acciones extra: editar / ver tareas / eliminar los pone la base.
        // (Duplicar y archivos solo existen en eventos de programa.)
        actions: function () { return []; }
    });

    window.AdhocIncidents = { instances: instances };
})();
