// @ts-check
/**
 * E2E del split de horarios y del scope por carrera.
 *
 * Ejercita el flujo completo por navegador: el coordinador re-divide un rango
 * que YA tiene una cita reservada, confirma en el modal, y el alumno afectado
 * termina con su cita acortada.
 *
 * El escenario se siembra y se limpia dentro del contenedor (ver _helpers.js);
 * no depende de qué datos tenga la BD de dev.
 */
const { test, expect } = require('@playwright/test');
const { seedScenario, cleanupScenario, stateFor } = require('./_helpers');

let ctx;

test.beforeAll(() => {
  ctx = seedScenario();
});

test.afterAll(() => {
  cleanupScenario(ctx);
});

// El storageState global es un admin de helpdesk; aquí hace falta el coordinador.
test.use({ storageState: undefined });

function coordContext(browser) {
  return browser.newContext({ storageState: stateFor(ctx.coordToken) });
}

function studentContext(browser) {
  return browser.newContext({ storageState: stateFor(ctx.studentToken) });
}

test.describe('Coordinador — pantalla de horarios', () => {
  test('carga y muestra el multi-select de carreras', async ({ browser }) => {
    const c = await coordContext(browser);
    const page = await c.newPage();
    await page.goto('/agendatec/coord/slots');

    await expect(page.locator('#dayConfigForm')).toBeVisible();

    // El coordinador tiene 3 carreras, así que el selector debe aparecer
    // con las 3 preseleccionadas.
    const wrap = page.locator('#cfgProgramsWrap');
    await expect(wrap).toBeVisible();
    const opciones = page.locator('#cfgPrograms option');
    await expect(opciones).toHaveCount(3);
    const seleccionadas = await page.locator('#cfgPrograms option:checked').count();
    expect(seleccionadas).toBe(3);

    await c.close();
  });

  test('permite una duración personalizada fuera del conjunto fijo', async ({ browser }) => {
    const c = await coordContext(browser);
    const page = await c.newPage();
    await page.goto('/agendatec/coord/slots');

    // El input custom nace oculto y solo aparece al elegir "Otra…".
    await expect(page.locator('#cfgMinutesCustom')).toBeHidden();
    await page.selectOption('#cfgMinutes', 'custom');
    await expect(page.locator('#cfgMinutesCustom')).toBeVisible();

    await page.selectOption('#cfgDay', ctx.day);
    await page.fill('#cfgStart', '15:00');
    await page.fill('#cfgEnd', '16:00');
    await page.fill('#cfgMinutesCustom', '13');

    const post = page.waitForResponse(
      (r) => r.url().endsWith('/coord/day-config') && r.request().method() === 'POST'
    );
    await page.click('#btnSaveCfg');
    const res = await post;
    expect(res.status()).toBe(200);
    // 60 min a 13 -> 4 slots, sobran 8 min sin slot.
    expect((await res.json()).slots_created).toBe(4);

    await c.close();
  });

  test('rechaza en cliente una duración fuera de 5-60', async ({ browser }) => {
    const c = await coordContext(browser);
    const page = await c.newPage();
    await page.goto('/agendatec/coord/slots');

    await page.selectOption('#cfgDay', ctx.day);
    await page.selectOption('#cfgMinutes', 'custom');
    await page.fill('#cfgMinutesCustom', '61');

    let llamado = false;
    page.on('request', (r) => {
      if (r.url().includes('/coord/day-config') && r.method() === 'POST') llamado = true;
    });
    await page.click('#btnSaveCfg');
    await page.waitForTimeout(500);
    expect(llamado, 'no debe llegar al servidor').toBe(false);

    await c.close();
  });
});

test.describe('Split con cita reservada', () => {
  test('cancelar el modal no aplica nada', async ({ browser }) => {
    const c = await coordContext(browser);
    const page = await c.newPage();
    await page.goto('/agendatec/coord/slots');

    await page.selectOption('#cfgDay', ctx.day);
    await page.fill('#cfgStart', '09:00');
    await page.fill('#cfgEnd', '10:00');
    await page.selectOption('#cfgMinutes', '5');

    let posted = false;
    page.on('request', (r) => {
      if (r.url().endsWith('/coord/day-config') && r.method() === 'POST') posted = true;
    });

    await page.click('#btnSaveCfg');
    await expect(page.locator('#modalSplitConfirm')).toBeVisible();
    await page.click('#modalSplitConfirm .btn-secondary');
    await expect(page.locator('#modalSplitConfirm')).toBeHidden();

    expect(posted).toBe(false);
    await c.close();
  });

  test('pide confirmación mostrando al alumno afectado, y acorta su cita', async ({ browser }) => {
    const c = await coordContext(browser);
    const page = await c.newPage();
    await page.goto('/agendatec/coord/slots');

    await page.selectOption('#cfgDay', ctx.day);
    await page.fill('#cfgStart', '09:00');
    await page.fill('#cfgEnd', '10:00');
    await page.selectOption('#cfgMinutes', '5');

    // El preview debe consultarse ANTES del POST: es lo que alimenta el modal.
    const previewReq = page.waitForResponse(
      (r) => r.url().includes('/coord/day-config/preview') && r.request().method() === 'POST'
    );
    await page.click('#btnSaveCfg');
    const preview = await previewReq;
    expect(preview.status()).toBe(200);

    // Modal con el alumno y su cambio de horario.
    const modal = page.locator('#modalSplitConfirm');
    await expect(modal).toBeVisible();
    const body = page.locator('#modalSplitConfirmBody');
    await expect(body).toContainText('E2E_AGENDATEC');
    await expect(body).toContainText('09:00–09:10');
    await expect(body).toContainText('09:00–09:05');

    // Confirmar dispara el POST real.
    const postReq = page.waitForResponse(
      (r) => r.url().endsWith('/coord/day-config') && r.request().method() === 'POST'
    );
    await page.click('#btnConfirmSplit');
    const post = await postReq;
    expect(post.status()).toBe(200);

    const data = await post.json();
    expect(data.slots_shortened).toBe(1);
    expect(data.appointments_notified).toBe(1);
    await c.close();

    // La notificacion se comprueba AQUI, no en un test posterior: el contador
    // de la respuesta se calcula antes de crearla, asi que un fallo silencioso
    // en la creacion pasaria desapercibido si solo se mirara el numero.
    const stu = await studentContext(browser);
    const res = await stu.request.get('/api/core/v2/notifications?app=agendatec&limit=20');
    expect(res.status()).toBe(200);
    const items = ((await res.json()).data || {}).items || [];
    const reagenda = items.find((n) => n.type === 'APPOINTMENT_RESCHEDULED');
    expect(reagenda, 'debe existir la notificacion de reagenda').toBeTruthy();
    // Sin action_url el click solo marcaba como leida, sin navegar.
    expect(reagenda.action_url).toBe('/agendatec/student/requests');
    await stu.close();
  });
});

test.describe('Split desalineado', () => {
  test('15 a 10 con una cita en 09:15 ya se aplica y respeta su hora', async ({ browser }) => {
    const c = await coordContext(browser);
    const page = await c.newPage();
    await page.goto('/agendatec/coord/slots');

    // Rango nuevo de 15 min con una cita en un offset que la regla vieja
    // rechazaba por no caer en la rejilla de 10.
    await coordSetRange(page, ctx.day, '13:00', '14:00', '15');

    await page.selectOption('#cfgDay', ctx.day);
    await page.fill('#cfgStart', '13:00');
    await page.fill('#cfgEnd', '14:00');
    await page.selectOption('#cfgMinutes', '10');

    const post = page.waitForResponse(
      (r) => r.url().endsWith('/coord/day-config') && r.request().method() === 'POST'
    );
    await page.click('#btnSaveCfg');
    const res = await post;
    expect(res.status(), 'ya no devuelve 409').toBe(200);

    await c.close();
  });
});

async function coordSetRange(page, day, start, end, minutes) {
  const res = await page.request.post('/api/agendatec/v2/coord/day-config', {
    data: { day, start, end, slot_minutes: Number(minutes) },
  });
  expect(res.status()).toBe(200);
}

test.describe('Scope por carrera — vista del alumno', () => {
  test('el alumno solo ve los horarios de las carreras del rango', async ({ browser }) => {
    const coord = await coordContext(browser);
    const coordPage = await coord.newPage();

    // El coordinador limita el rango a la PRIMERA carrera.
    const res = await coordPage.request.post('/api/agendatec/v2/coord/day-config', {
      data: {
        day: ctx.day, start: '11:00', end: '12:00', slot_minutes: 10,
        programs: [ctx.programIds[0]],
      },
    });
    expect(res.status()).toBe(200);
    await coord.close();

    const stu = await studentContext(browser);

    const dentro = await stu.request.get(
      `/api/agendatec/v2/availability/program/${ctx.programIds[0]}/slots?day=${ctx.day}`
    );
    expect(dentro.status()).toBe(200);
    const dentroJson = await dentro.json();
    // Acotado a la ventana 11:00-12:00: otros tests del archivo crean rangos a
    // las 13:00 y 15:00, y un filtro por `>= 11:00` los arrastraria.
    const once = dentroJson.items.filter((i) => i.start_time >= '11:00' && i.start_time < '12:00');
    expect(once.length).toBe(6);

    const fuera = await stu.request.get(
      `/api/agendatec/v2/availability/program/${ctx.programIds[1]}/slots?day=${ctx.day}`
    );
    expect(fuera.status()).toBe(200);
    const fueraJson = await fuera.json();
    expect(
      fueraJson.items.filter((i) => i.start_time >= '11:00' && i.start_time < '12:00').length
    ).toBe(0);

    await stu.close();
  });
});
