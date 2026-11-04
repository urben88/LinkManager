/* ============================================================================
   monitor.js — el panel de estado del ordenador.

   Pinta lo que devuelve /monitor/datos (que a su vez lee de Glances). Es solo
   lectura: aquí no hay ninguna orden, ningún botón que cambie nada y ninguna
   consola. Lo único que hace es pedir cifras cada 2 s y dibujarlas.

   · La primera vez construye el esqueleto; después solo actualiza valores, para
     que no parpadee.
   · Si el panel está cerrado o la pestaña en segundo plano, deja de pedir: un
     monitor que vigila no debe ser lo que más consume.
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
    if (pie && d.equipo.arranque) {
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

  function programar() {
    clearTimeout(temporizador);
    if (cerrado) return;
    temporizador = setTimeout(async () => {
      await pedir();
      programar();
    }, INTERVALO);
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
    await pedir();
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

  /* ------------------------------------------------------------- arranque */

  if (botonAbrir) botonAbrir.addEventListener('click', () => (panel.hidden ? abrir() : cerrar()));
  if (botonCerrar) botonCerrar.addEventListener('click', cerrar);
  document.getElementById('monitor-refrescar').addEventListener('click', pedir);

  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !panel.hidden && document.activeElement === document.body) cerrar();
  });

  // Con la pestaña en segundo plano no se pide nada; al volver, se reanuda.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      clearTimeout(temporizador);
    } else if (!panel.hidden && !cerrado) {
      pedir().then(programar);
    }
  });

  try {
    if (sessionStorage.getItem('monitor-abierto') === '1') abrir();
  } catch (e) { /* nada */ }
})();
