/* ============================================================================
   monitor.js — el panel de estado del ordenador.

   Pinta lo que devuelve /monitor/datos (que a su vez lee de Glances). Es solo
   lectura: aquí no hay ninguna orden, ningún botón que cambie nada y ninguna
   consola. Lo único que hace es pedir cifras cada 2 s y dibujarlas.

   · La primera vez construye el esqueleto; después solo actualiza valores, para
     que no parpadee.
   · Si el panel está cerrado o la pestaña en segundo plano, deja de pedir: un
     monitor que vigila no debe ser lo que más consume.
   · La pestaña «Cortes y registros» lee /monitor/vigilante y /monitor/registro:
     lo que escribe el vigilante del servidor (~/watchdog). Se pide cada 15 s y
     solo mientras esa pestaña está a la vista.
   ========================================================================== */

(function () {
  'use strict';

  const panel = document.getElementById('monitor');
  if (!panel) return;

  const hilo = document.getElementById('monitor-hilo');
  const sub = document.getElementById('monitor-sub');
  const botonAbrir = document.getElementById('abrir-monitor');
  const botonCerrar = document.getElementById('monitor-cerrar');

  const INTERVALO = 2500;
  const MAX_MUESTRAS = 60;          // 60 × 2,5 s ≈ 2 minutos de historia
  const historial = { cpu: [], ram: [] };

  let temporizador = null;
  let montado = false;
  let cerrado = false;
  let pestana = 'ahora';            // 'ahora' (Glances) o 'vigilante'

  /* ---------------------------------------------------------- utilidades */

  function esc(t) {
    return String(t == null ? '' : t)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function num(valor, decimales) {
    if (valor === null || valor === undefined || Number.isNaN(Number(valor))) return '—';
    return Number(valor).toLocaleString('es-ES', {
      minimumFractionDigits: decimales || 0,
      maximumFractionDigits: decimales || 0,
    });
  }

  function nivel(pct, umbrales, prefijo) {
    if (pct === null || pct === undefined) return 'ok';
    if (pct >= umbrales[prefijo + '_alto']) return 'alto';
    if (pct >= umbrales[prefijo + '_atencion']) return 'atencion';
    return 'ok';
  }

  // "17 days, 15:37:11" → "17 d 15 h 37 min"
  function arranque(txt) {
    const m = /^(\d+)\s+days?,\s*(\d+):(\d+):/.exec(txt || '');
    if (m) return `${m[1]} d ${m[2]} h ${m[3]} min`;
    const h = /^(\d+):(\d+):(\d+)$/.exec(txt || '');
    if (h) return `${Number(h[1])} h ${h[2]} min`;
    return txt || '—';
  }

  /* ------------------------------------------------------------ esqueleto */

  function medidor(id, nombre) {
    return `
      <div class="medidor" id="m-${id}">
        <div class="medidor-cab">
          <span class="medidor-nombre">${nombre}</span>
          <span class="medidor-valor" id="m-${id}-val">—</span>
        </div>
        <div class="medidor-barra"><i id="m-${id}-barra" style="width:0%"></i></div>
        <div class="medidor-pie" id="m-${id}-pie"></div>
      </div>`;
  }

  function montar() {
    hilo.innerHTML = `
      <div class="monitor-estado" id="m-estado" data-nivel="ok">
        <span class="monitor-punto"></span>
        <strong id="m-estado-texto">todo en orden</strong>
        <span class="monitor-hora" id="m-hora"></span>
      </div>

      <div class="monitor-tarjetas">
        ${medidor('cpu', 'CPU')}
        <div class="monitor-nucleos" id="m-nucleos" aria-label="Uso por núcleo"></div>
        ${medidor('ram', 'Memoria')}
        ${medidor('gpu', 'GPU')}
        ${medidor('disco', 'Disco')}
      </div>

      <div class="monitor-grafica">
        <svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
          <polyline id="m-trazo-ram" class="trazo trazo--ram" points=""></polyline>
          <polyline id="m-trazo-cpu" class="trazo trazo--cpu" points=""></polyline>
        </svg>
        <div class="monitor-leyenda">
          <span class="punto punto--cpu"></span> CPU
          <span class="punto punto--ram"></span> memoria
          <span class="monitor-leyenda-nota">últimos 2 minutos</span>
        </div>
      </div>

      <p class="monitor-error" id="m-error" hidden></p>`;
    montado = true;
  }

  /* --------------------------------------------------------------- pintar */

  function barra(id, pct, nivelActual) {
    const relleno = document.getElementById(`m-${id}-barra`);
    const caja = document.getElementById(`m-${id}`);
    if (relleno) relleno.style.width = Math.max(0, Math.min(100, pct || 0)) + '%';
    if (caja) caja.dataset.nivel = nivelActual;
  }

  function trazo(id, valores, colorClase) {
    const polilinea = document.getElementById(id);
    if (!polilinea) return;
    if (valores.length < 2) { polilinea.setAttribute('points', ''); return; }
    const n = valores.length;
    const puntos = valores.map((v, i) => {
      const x = (i / (n - 1)) * 100;
      const y = 30 - (Math.max(0, Math.min(100, v)) / 100) * 30;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    polilinea.setAttribute('points', puntos.join(' '));
    polilinea.setAttribute('class', 'trazo ' + colorClase);
  }

  function pintar(d) {
    const umbrales = d.umbrales || {};

    // estado
    const estado = d.estado || { nivel: 'ok', texto: 'todo en orden' };
    const cajaEstado = document.getElementById('m-estado');
    if (cajaEstado) cajaEstado.dataset.nivel = estado.nivel;
    document.getElementById('m-estado-texto').textContent = estado.texto;
    document.getElementById('m-hora').textContent =
      'actualizado ' + new Date((d.tomado || Date.now() / 1000) * 1000)
        .toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    // cabecera
    sub.textContent = `${d.equipo.nombre} · ${d.equipo.so} · ${d.equipo.nucleos} núcleos`;
    const pie = document.getElementById('monitor-pie');
    if (pie && d.equipo.arranque && pestana === 'ahora') {
      pie.textContent = `Encendido ${arranque(d.equipo.arranque)} · medidas de Glances, solo lectura`;
    }

    // CPU
    const cpu = d.cpu || {};
    document.getElementById('m-cpu-val').textContent = num(cpu.pct, 0) + ' %';
    barra('cpu', cpu.pct, nivel(cpu.pct, umbrales, 'cpu'));
    const carga = (cpu.carga || []).map(v => num(v, 2)).join(' · ');
    document.getElementById('m-cpu-pie').textContent =
      (cpu.temp != null ? num(cpu.temp, 0) + ' °C · ' : '') + 'carga ' + carga;

    // núcleos
    const cajaNucleos = document.getElementById('m-nucleos');
    const nucleos = cpu.nucleos || [];
    if (cajaNucleos.childElementCount !== nucleos.length) {
      cajaNucleos.innerHTML = nucleos.map(() => '<i></i>').join('');
    }
    Array.from(cajaNucleos.children).forEach((barraNucleo, i) => {
      const v = nucleos[i] || 0;
      barraNucleo.style.height = Math.max(6, Math.min(100, v)) + '%';
      barraNucleo.dataset.nivel = nivel(v, umbrales, 'cpu');
      barraNucleo.title = `núcleo ${i}: ${num(v, 0)} %`;
    });

    // Memoria
    const ram = d.ram || {};
    document.getElementById('m-ram-val').textContent = num(ram.pct, 0) + ' %';
    barra('ram', ram.pct, nivel(ram.pct, umbrales, 'ram'));
    document.getElementById('m-ram-pie').textContent =
      `${num(ram.usada_gb, 1)} / ${num(ram.total_gb, 0)} GB`
      + (ram.swap_pct > 0 ? ` · swap ${num(ram.swap_gb, 1)} GB` : '');

    // GPU
    const gpu = d.gpu;
    if (gpu) {
      document.getElementById('m-gpu').hidden = false;
      document.getElementById('m-gpu-val').textContent =
        gpu.pct == null ? '—' : num(gpu.pct, 0) + ' %';
      barra('gpu', gpu.pct, nivel(gpu.pct, umbrales, 'cpu'));
      document.getElementById('m-gpu-pie').textContent =
        [gpu.nombre, gpu.temp != null ? num(gpu.temp, 0) + ' °C' : null]
          .filter(Boolean).join(' · ');
    } else {
      document.getElementById('m-gpu').hidden = true;
    }

    // Disco
    const disco = d.disco || {};
    document.getElementById('m-disco-val').textContent =
      disco.pct == null ? '—' : num(disco.pct, 0) + ' %';
    barra('disco', disco.pct, nivel(disco.pct, umbrales, 'disco'));
    document.getElementById('m-disco-pie').textContent =
      disco.usado_gb != null
        ? `${num(disco.usado_gb, 0)} / ${num(disco.total_gb, 0)} GB`
        : 'sin datos';

    // historia
    if (cpu.pct != null) {
      historial.cpu.push(cpu.pct);
      historial.ram.push(ram.pct || 0);
      if (historial.cpu.length > MAX_MUESTRAS) { historial.cpu.shift(); historial.ram.shift(); }
      trazo('m-trazo-cpu', historial.cpu, 'trazo--cpu');
      trazo('m-trazo-ram', historial.ram, 'trazo--ram');
    }

    const aviso = document.getElementById('m-error');
    if (aviso) aviso.hidden = true;
    // al volver los datos, reaparecen los medidores que escondió el error
    document.querySelectorAll('.monitor-tarjetas, .monitor-grafica').forEach((el) => { el.hidden = false; });
  }

  function pintarError(motivo) {
    if (!montado) montar();
    // Sin datos no se puede dejar «todo en orden» con el semáforo verde: se
    // apaga el indicador y se esconden los medidores, que estarían a cero.
    const cajaEstado = document.getElementById('m-estado');
    if (cajaEstado) cajaEstado.dataset.nivel = 'sin-datos';
    const texto = document.getElementById('m-estado-texto');
    if (texto) texto.textContent = 'sin datos';
    const hora = document.getElementById('m-hora');
    if (hora) hora.textContent = '';
    document.querySelectorAll('.monitor-tarjetas, .monitor-grafica').forEach((el) => { el.hidden = true; });

    const aviso = document.getElementById('m-error');
    if (!aviso) return;
    aviso.hidden = false;
    aviso.textContent = motivo || 'No se pudo leer el estado del servidor.';
    sub.textContent = 'sin datos';
  }

  /* ---------------------------------------------------------------- pedir */

  async function pedir() {
    try {
      const respuesta = await fetch('/monitor/datos', {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'X-CSRF-Token': window.CSRF || '' },
      });
      const datos = await respuesta.json().catch(() => ({}));
      if (!datos || datos.disponible === false) {
        pintarError(datos && datos.motivo ? datos.motivo : 'El monitor no responde.');
        return;
      }
      if (!montado) montar();
      pintar(datos);
    } catch (error) {
      pintarError('No se pudo leer el estado del servidor (' + error.message + ').');
    }
  }

  /* ----------------------------------------------------------------- bucle */

  function pedirActual() {
    return pestana === 'vigilante' ? pedirVigilante() : pedir();
  }

  function programar() {
    clearTimeout(temporizador);
    if (cerrado) return;
    temporizador = setTimeout(async () => {
      await pedirActual();
      programar();
    }, pestana === 'vigilante' ? INTERVALO_VIGILANTE : INTERVALO);
  }

  async function abrir() {
    // El cajón es el mismo sitio que el del asistente: se cierra el otro para
    // que no se apilen dos paneles a la derecha.
    const asistente = document.getElementById('agente');
    if (asistente && !asistente.hidden) {
      const cerrarAsistente = document.getElementById('agente-cerrar');
      if (cerrarAsistente) cerrarAsistente.click();
    }

    panel.hidden = false;
    cerrado = false;
    document.body.classList.add('monitor-abierto');
    if (botonAbrir) botonAbrir.setAttribute('aria-expanded', 'true');
    if (!montado) montar();
    await pedirActual();
    programar();
    try { sessionStorage.setItem('monitor-abierto', '1'); } catch (e) { /* nada */ }
  }

  function cerrar() {
    cerrado = true;
    clearTimeout(temporizador);
    panel.hidden = true;
    document.body.classList.remove('monitor-abierto');
    if (botonAbrir) botonAbrir.setAttribute('aria-expanded', 'false');
    try { sessionStorage.setItem('monitor-abierto', '0'); } catch (e) { /* nada */ }
  }

  /* ------------------------------------------------- cortes y registros

     Lo que cuenta el vigilante: si late, desde cuándo está encendido el
     equipo y conectado el router, el último corte y la lista de sucesos.
     Debajo, la cola de cualquiera de sus tres logs, tal cual. */

  const cajaVigilante = document.getElementById('monitor-vigilante');
  const botonAhora = document.getElementById('pestana-ahora');
  const botonVigilante = document.getElementById('pestana-vigilante');
  const avisoPestana = document.getElementById('pestana-vigilante-aviso');

  const INTERVALO_VIGILANTE = 15000;
  const REGISTROS = {
    events: 'Sucesos',
    health: 'Latido (1 min)',
    fastbeat: 'Pulso fino (10 s)',
  };
  const ETIQUETAS = {
    'CORTE-DE-LUZ?': 'Posible corte de luz',
    'CORTE-DE-LUZ': 'Corte de luz',
    'POST-MORTEM': 'Post-mortem',
    'REINICIO': 'Reinicio',
    'SALTO-DE-RELOJ': 'Hueco sin latidos',
    'TEMPERATURA-ALTA': 'Temperatura alta',
    'JOURNAL-GRANDE': 'Journal grande',
    'BUCLE-CONTENEDOR': 'bucles de contenedor',
    'REINICIOS-DOCKER': 'subidas del contador de reinicios de Docker',
  };

  let vigilanteMontado = false;
  let registroActual = 'events';
  let filtroSucesos = 'importantes';   // 'importantes' | 'cortes'

  function duracion(segundos) {
    if (segundos == null || Number.isNaN(Number(segundos))) return '—';
    let s = Math.max(0, Math.round(Number(segundos)));
    const d = Math.floor(s / 86400); s -= d * 86400;
    const h = Math.floor(s / 3600); s -= h * 3600;
    const m = Math.floor(s / 60);
    if (d) return `${d} d ${h} h`;
    if (h) return `${h} h ${m} min`;
    if (m) return `${m} min`;
    return `${s} s`;
  }

  function haceDesde(iso) {
    const t = Date.parse(iso || '');
    if (Number.isNaN(t)) return '—';
    return 'hace ' + duracion((Date.now() - t) / 1000);
  }

  function fecha(isoOEpoch) {
    const t = typeof isoOEpoch === 'number' ? isoOEpoch * 1000 : Date.parse(isoOEpoch || '');
    if (Number.isNaN(t)) return '—';
    return new Date(t).toLocaleString('es-ES', {
      day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    });
  }

  function montarVigilante() {
    cajaVigilante.innerHTML = `
      <div class="monitor-estado" id="v-estado" data-nivel="ok">
        <span class="monitor-punto"></span>
        <strong id="v-estado-texto">—</strong>
        <span class="monitor-hora" id="v-latido"></span>
      </div>

      <div class="vigilante-datos">
        <div class="vigilante-dato">
          <span class="medidor-nombre">Encendido</span>
          <strong id="v-encendido">—</strong>
          <span class="medidor-pie" id="v-encendido-pie"></span>
        </div>
        <div class="vigilante-dato">
          <span class="medidor-nombre">Router conectado</span>
          <strong id="v-router">—</strong>
          <span class="medidor-pie" id="v-router-pie"></span>
        </div>
        <div class="vigilante-dato">
          <span class="medidor-nombre">Último corte</span>
          <strong id="v-corte">—</strong>
          <span class="medidor-pie" id="v-corte-pie"></span>
        </div>
        <div class="vigilante-dato">
          <span class="medidor-nombre">Últimos 30 días</span>
          <strong id="v-cuentas">—</strong>
          <span class="medidor-pie" id="v-cuentas-pie"></span>
        </div>
      </div>

      <div class="vigilante-veredicto" id="v-veredicto" hidden></div>

      ${window.AGENTE ? `
      <button type="button" class="vigilante-diagnostico" id="v-diagnostico">
        <span>Pedir diagnóstico al asistente</span>
        <small>resume los cortes y explica la causa más probable</small>
      </button>` : ''}

      <section class="vigilante-seccion">
        <div class="vigilante-seccion-cab">
          <h3>Sucesos</h3>
          <div class="vigilante-segmentos" role="group" aria-label="Qué sucesos ver">
            <button type="button" data-filtro="importantes" aria-pressed="true">Todos</button>
            <button type="button" data-filtro="cortes" aria-pressed="false">Solo cortes</button>
          </div>
        </div>
        <ol class="vigilante-sucesos" id="v-sucesos"></ol>
        <p class="medidor-pie" id="v-ruido" hidden></p>
      </section>

      <section class="vigilante-seccion">
        <div class="vigilante-seccion-cab">
          <h3>Registros</h3>
          <div class="vigilante-segmentos" role="group" aria-label="Qué registro ver" id="v-registros">
            ${Object.entries(REGISTROS).map(([clave, nombre]) =>
              `<button type="button" data-registro="${clave}" aria-pressed="${clave === registroActual}">${nombre}</button>`
            ).join('')}
          </div>
        </div>
        <pre class="vigilante-log" id="v-log" tabindex="0" aria-label="Últimas líneas del registro">…</pre>
        <p class="medidor-pie" id="v-log-pie"></p>
      </section>

      <p class="monitor-error" id="v-error" hidden></p>`;

    cajaVigilante.querySelectorAll('[data-filtro]').forEach((b) => b.addEventListener('click', () => {
      filtroSucesos = b.dataset.filtro;
      cajaVigilante.querySelectorAll('[data-filtro]').forEach((o) =>
        o.setAttribute('aria-pressed', String(o === b)));
      if (ultimoVigilante) pintarSucesos(ultimoVigilante);
    }));
    cajaVigilante.querySelectorAll('[data-registro]').forEach((b) => b.addEventListener('click', () => {
      registroActual = b.dataset.registro;
      cajaVigilante.querySelectorAll('[data-registro]').forEach((o) =>
        o.setAttribute('aria-pressed', String(o === b)));
      pedirRegistro(true);
    }));
    const botonDiagnostico = document.getElementById('v-diagnostico');
    if (botonDiagnostico) botonDiagnostico.addEventListener('click', () => {
      if (typeof window.preguntarAsistente === 'function') {
        window.preguntarAsistente(
          'Hazme un resumen de los últimos cortes de luz, reinicios y sucesos del servidor '
          + 'y un pequeño diagnóstico: causa más probable y qué debería revisar.');
      }
    });
    vigilanteMontado = true;
  }

  let ultimoVigilante = null;

  function pintarSucesos(d) {
    const lista = document.getElementById('v-sucesos');
    const eventos = (d.eventos || []).filter((e) =>
      filtroSucesos === 'cortes' ? e.familia === 'corte' : true);
    if (!eventos.length) {
      lista.innerHTML = `<li class="vigilante-suceso vigilante-suceso--vacio">${
        filtroSucesos === 'cortes' ? 'No hay cortes registrados.' : 'Sin sucesos.'}</li>`;
    } else {
      lista.innerHTML = eventos.map((e) => {
        let chip = '';
        if (e.servidor_cayo === true) chip = '<span class="vigilante-chip vigilante-chip--alto">servidor apagado</span>';
        else if (e.servidor_cayo === false) chip = '<span class="vigilante-chip">servidor encendido</span>';
        const texto = e.tipo === 'POST-MORTEM'
          ? `<strong>${esc(e.veredicto)}</strong> · ${esc(e.explicacion)}`
          : esc(e.mensaje);
        return `
          <li class="vigilante-suceso" data-familia="${esc(e.familia)}">
            <div class="vigilante-suceso-cab">
              <span class="vigilante-suceso-titulo">
                <span class="vigilante-suceso-tipo">${esc(ETIQUETAS[e.tipo] || e.tipo)}</span>
                ${chip}
              </span>
              <time datetime="${esc(e.ts)}" title="${esc(e.ts)}">${esc(fecha(e.ts))}</time>
            </div>
            <p>${texto}</p>
          </li>`;
      }).join('');
    }

    const ruido = Object.entries(d.ruido_24h || {});
    const cajaRuido = document.getElementById('v-ruido');
    cajaRuido.hidden = !ruido.length;
    cajaRuido.textContent = ruido.length
      ? 'Últimas 24 h, sin listar: ' + ruido.map(([t, n]) => `${n} ${ETIQUETAS[t] || t}`).join(' · ')
        + '. Están en Registros → Sucesos.'
      : '';
  }

  function pintarVigilante(d) {
    ultimoVigilante = d;
    const estado = d.estado || { nivel: 'ok', texto: '' };
    document.getElementById('v-estado').dataset.nivel = estado.nivel;
    document.getElementById('v-estado-texto').textContent = estado.texto;
    const pulso = d.pulso || {};
    document.getElementById('v-latido').textContent =
      pulso.hace_s == null ? 'sin latidos' : `último latido hace ${duracion(pulso.hace_s)}`;

    const eq = d.equipo || {};
    document.getElementById('v-encendido').textContent = duracion(eq.uptime_s);
    document.getElementById('v-encendido-pie').textContent =
      eq.arranque ? 'desde ' + fecha(eq.arranque) : '';

    const r = d.router;
    document.getElementById('v-router').textContent = r ? duracion(r.conectado_s) : '—';
    document.getElementById('v-router-pie').textContent =
      r ? `desde ${fecha(r.desde)} · ${r.estado === 'Connected' ? 'conectado' : r.estado}` : 'sin datos del router';

    const c = d.ultimo_corte;
    document.getElementById('v-corte').textContent = c ? haceDesde(c.ts) : 'ninguno';
    document.getElementById('v-corte-pie').textContent = c
      ? fecha(c.ts) + (c.servidor_cayo === false ? ' · el servidor aguantó'
        : c.servidor_cayo === true ? ' · el servidor se apagó' : '')
      : 'sin cortes registrados';

    const n = d.cuentas_30d || {};
    document.getElementById('v-cuentas').textContent =
      `${n.cortes || 0} ${n.cortes === 1 ? 'corte' : 'cortes'}`;
    document.getElementById('v-cuentas-pie').textContent =
      `${n.reinicios || 0} ${n.reinicios === 1 ? 'reinicio' : 'reinicios'} · `
      + `${n.paradas || 0} ${n.paradas === 1 ? 'hueco' : 'huecos'} sin latidos`;

    const v = d.ultimo_veredicto;
    const cajaVeredicto = document.getElementById('v-veredicto');
    cajaVeredicto.hidden = !v;
    if (v) {
      cajaVeredicto.dataset.familia = v.familia;
      cajaVeredicto.innerHTML = `
        <span class="medidor-nombre">Último post-mortem · ${esc(fecha(v.ts))}</span>
        <strong>${esc(v.veredicto)}</strong>
        <p>${esc(v.explicacion)}</p>`;
    }

    pintarSucesos(d);

    // Un punto en la pestaña si hubo corte o reinicio en las últimas 24 h
    avisoPestana.hidden = estado.nivel === 'ok';
    avisoPestana.dataset.nivel = estado.nivel;

    document.getElementById('v-error').hidden = true;
  }

  function errorVigilante(motivo) {
    if (!vigilanteMontado) montarVigilante();
    document.getElementById('v-estado').dataset.nivel = 'sin-datos';
    document.getElementById('v-estado-texto').textContent = 'sin datos';
    const aviso = document.getElementById('v-error');
    aviso.hidden = false;
    aviso.textContent = motivo || 'No se pudo leer el vigilante.';
  }

  async function pedirRegistro(bajarAlFinal) {
    const caja = document.getElementById('v-log');
    if (!caja) return;
    // si el usuario subió a leer, no se le mueve al refrescar
    const alFinal = bajarAlFinal || caja.scrollHeight - caja.scrollTop - caja.clientHeight < 24;
    try {
      const resp = await fetch(`/monitor/registro/${registroActual}?lineas=120`, {
        credentials: 'same-origin', cache: 'no-store',
      });
      const d = await resp.json().catch(() => ({}));
      caja.textContent = d.disponible ? d.lineas.join('\n') : (d.motivo || 'Sin datos.');
      document.getElementById('v-log-pie').textContent = d.disponible
        ? `${d.fichero} · últimas ${d.lineas.length} líneas · ~/watchdog/logs`
        : '';
      if (alFinal) caja.scrollTop = caja.scrollHeight;
    } catch (error) {
      caja.textContent = 'No se pudo leer el registro (' + error.message + ').';
    }
  }

  async function pedirVigilante() {
    try {
      const resp = await fetch('/monitor/vigilante', { credentials: 'same-origin', cache: 'no-store' });
      const d = await resp.json().catch(() => ({}));
      if (!vigilanteMontado) montarVigilante();
      if (!d || d.disponible === false) {
        errorVigilante(d && d.motivo ? d.motivo : 'El vigilante no responde.');
        return;
      }
      pintarVigilante(d);
      await pedirRegistro(false);
    } catch (error) {
      errorVigilante('No se pudo leer el vigilante (' + error.message + ').');
    }
  }

  function cambiarPestana(nueva, sinPedir) {
    pestana = nueva;
    const esVigilante = nueva === 'vigilante';
    botonAhora.setAttribute('aria-selected', String(!esVigilante));
    botonVigilante.setAttribute('aria-selected', String(esVigilante));
    hilo.hidden = esVigilante;
    cajaVigilante.hidden = !esVigilante;
    const pie = document.getElementById('monitor-pie');
    if (pie) {
      pie.innerHTML = esVigilante
        ? 'Logs del <strong>vigilante</strong> (~/watchdog) · solo lectura · cada 15 s'
        : 'Medidas de <strong>Glances</strong> · solo lectura · se actualiza cada 2 s';
    }
    try { sessionStorage.setItem('monitor-pestana', nueva); } catch (e) { /* nada */ }
    if (sinPedir || cerrado || panel.hidden) return;
    pedirActual().then(programar);
  }

  /* ------------------------------------------------------------- arranque */

  if (botonAbrir) botonAbrir.addEventListener('click', () => (panel.hidden ? abrir() : cerrar()));
  if (botonCerrar) botonCerrar.addEventListener('click', cerrar);
  const botonRefrescar = document.getElementById('monitor-refrescar');
  botonRefrescar.addEventListener('click', async () => {
    botonRefrescar.classList.add('girando');
    await pedirActual();
    setTimeout(() => botonRefrescar.classList.remove('girando'), 450);
  });

  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape' || panel.hidden || document.querySelector('.dialogo:not([hidden])')) return;
    const foco = document.activeElement;
    const enPanel = panel.contains(foco);
    if (enPanel || foco === document.body || foco === botonAbrir) {
      cerrar();
      if (botonAbrir) botonAbrir.focus();   // el foco no se pierde al cerrar
    }
  });

  // Con la pestaña en segundo plano no se pide nada; al volver, se reanuda.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      clearTimeout(temporizador);
    } else if (!panel.hidden && !cerrado) {
      pedirActual().then(programar);
    }
  });

  botonAhora.addEventListener('click', () => cambiarPestana('ahora'));
  botonVigilante.addEventListener('click', () => cambiarPestana('vigilante'));

  try {
    if (sessionStorage.getItem('monitor-pestana') === 'vigilante') cambiarPestana('vigilante', true);
    if (sessionStorage.getItem('monitor-abierto') === '1') abrir();
  } catch (e) { /* nada */ }
})();
