/* ============================================================================
   consola.js — acceso «Servidor» del asistente (solo admin).

   Terminales reales del servidor dibujadas con xterm.js. El navegador no
   decide nada: pide al portal un terminal de un TIPO (shell, claude,
   opencode), un ticket de un solo uso para conectarse, y se engancha por
   websocket. Los terminales viven en el servidor (consola-puente): cerrar la
   pestaña no los mata; al volver, se reengancha y se ve lo último.
   ========================================================================== */

(function () {
  'use strict';

  const raiz = document.getElementById('modo-servidor');
  if (!raiz || typeof window.Terminal !== 'function') return;

  const cerrojo = document.getElementById('consola-cerrojo');
  const cerrojoError = document.getElementById('consola-cerrojo-error');
  const sin2fa = document.getElementById('consola-sin2fa');
  const formCodigo = document.getElementById('consola-desbloquear');
  const inputCodigo = document.getElementById('consola-codigo');
  const trabajo = document.getElementById('consola-trabajo');
  const pestanas = document.getElementById('consola-pestanas');
  const pantalla = document.getElementById('consola-pantalla');
  const vacia = document.getElementById('consola-vacia');
  const carpeta = document.getElementById('consola-carpeta');
  const hastaTxt = document.getElementById('consola-hasta');
  const errorGlobal = document.getElementById('consola-error');
  const csrf = window.CSRF || '';

  const terminales = new Map();   // id -> {info, term, fit, caja, ws, pestana}
  let activa = null;
  let hasta = 0;
  let cargando = false;

  /* ------------------------------------------------------------- utilidades */

  async function pedir(url, opciones = {}) {
    const r = await fetch(url, {
      ...opciones,
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, ...(opciones.headers || {}) },
      credentials: 'same-origin',
    });
    let datos = {};
    try { datos = await r.json(); } catch (e) { /* vacío */ }
    if (r.status === 401 || r.redirected) datos = { ok: false, error: 'La sesión ha caducado. Vuelve a entrar.' };
    if (!r.ok && !datos.error) datos.error = `Error ${r.status}`;
    datos._estado = r.status;
    return datos;
  }

  function avisar(texto) {
    errorGlobal.textContent = texto || '';
    errorGlobal.hidden = !texto;
  }

  function hora(ts) {
    return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  const tema = {
    background: '#14161b', foreground: '#eceef1', cursor: '#8ab4f8', cursorAccent: '#14161b',
    selectionBackground: 'rgba(138,180,248,.32)',
    black: '#1c1e24', red: '#f28b82', green: '#81c995', yellow: '#fdd663',
    blue: '#8ab4f8', magenta: '#d7aefb', cyan: '#78d9ec', white: '#e8eaed',
    brightBlack: '#5f6368', brightRed: '#f6aea9', brightGreen: '#a8dab5', brightYellow: '#fde293',
    brightBlue: '#aecbfa', brightMagenta: '#e9d2fd', brightCyan: '#a1e4f2', brightWhite: '#ffffff',
  };

  /* ------------------------------------------------------------ estado */

  async function cargar() {
    if (cargando) return;
    cargando = true;
    try {
      const d = await pedir('/consola/estado');
      if (!d.ok && d._estado !== 403) { avisar(d.error); return; }
      avisar(d.error || '');
      if (!d.desbloqueada) {
        mostrarCerrojo(d.tiene_2fa);
        return;
      }
      hasta = d.hasta;
      hastaTxt.textContent = `Desbloqueada hasta las ${hora(hasta)}`;
      cerrojo.hidden = true;
      trabajo.hidden = false;
      sincronizar(d.terminales || []);
    } finally {
      cargando = false;
    }
  }

  function mostrarCerrojo(tiene2fa) {
    trabajo.hidden = true;
    cerrojo.hidden = false;
    sin2fa.hidden = !!tiene2fa;
    formCodigo.hidden = !tiene2fa;
    cerrojoError.hidden = true;
    terminales.forEach((t) => desconectar(t));
    if (tiene2fa) setTimeout(() => inputCodigo.focus(), 50);
  }

  formCodigo.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const boton = formCodigo.querySelector('button');
    boton.disabled = true;
    const d = await pedir('/consola/desbloquear', {
      method: 'POST', body: JSON.stringify({ codigo: inputCodigo.value }),
    });
    boton.disabled = false;
    inputCodigo.value = '';
    if (!d.ok) {
      cerrojoError.textContent = d.error || 'No se pudo desbloquear.';
      cerrojoError.hidden = false;
      inputCodigo.focus();
      return;
    }
    cargar();
  });

  /* --------------------------------------------------------- terminales */

  function sincronizar(lista) {
    const vivos = new Set(lista.map(t => t.id));
    terminales.forEach((t, id) => { if (!vivos.has(id)) quitar(id); });
    lista.forEach((info) => {
      if (!terminales.has(info.id)) crearVista(info);
      else terminales.get(info.id).info = info;
    });
    vacia.hidden = terminales.size > 0;
    if (!activa || !terminales.has(activa)) {
      const primero = lista.length ? lista[lista.length - 1].id : null;
      if (primero) enfocar(primero);
    } else {
      enfocar(activa);
    }
  }

  function crearVista(info) {
    const caja = document.createElement('div');
    caja.className = 'consola-term';
    caja.hidden = true;
    pantalla.appendChild(caja);

    const term = new window.Terminal({
      cursorBlink: true, fontSize: 13, lineHeight: 1.15, scrollback: 5000,
      fontFamily: '"JetBrains Mono", "Fira Code", ui-monospace, "SF Mono", Menlo, Consolas, monospace',
      theme: tema, allowProposedApi: false,
    });
    const fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(caja);

    const pestana = document.createElement('div');
    pestana.className = 'consola-pestana';
    pestana.setAttribute('role', 'tab');
    const nombre = document.createElement('button');
    nombre.type = 'button';
    nombre.className = 'consola-pestana-nombre';
    nombre.textContent = info.nombre;
    nombre.title = info.carpeta;
    nombre.addEventListener('click', () => enfocar(info.id));
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'consola-pestana-cerrar';
    x.title = 'Cerrar esta terminal (mata lo que esté corriendo)';
    x.setAttribute('aria-label', `Cerrar ${info.nombre}`);
    x.textContent = '×';
    x.addEventListener('click', () => cerrarTerminal(info.id, x));
    pestana.append(nombre, x);
    pestanas.appendChild(pestana);

    const t = { info, term, fit, caja, ws: null, pestana, reintentos: 0 };
    terminales.set(info.id, t);

    term.onData((datos) => {
      if (t.ws && t.ws.readyState === WebSocket.OPEN) t.ws.send(JSON.stringify({ i: datos }));
    });
    term.onResize(({ cols, rows }) => {
      if (t.ws && t.ws.readyState === WebSocket.OPEN) t.ws.send(JSON.stringify({ r: [cols, rows] }));
    });
    return t;
  }

  function enfocar(id) {
    activa = id;
    terminales.forEach((t, clave) => {
      const es = clave === id;
      t.caja.hidden = !es;
      t.pestana.setAttribute('aria-selected', es ? 'true' : 'false');
    });
    const t = terminales.get(id);
    if (!t) return;
    requestAnimationFrame(() => {
      ajustar(t);
      if (!t.ws || t.ws.readyState > WebSocket.OPEN) conectar(t);
      t.term.focus();
    });
  }

  function ajustar(t) {
    if (t.caja.hidden || !t.caja.offsetWidth) return;
    try { t.fit.fit(); } catch (e) { /* aún sin tamaño */ }
  }

  async function conectar(t) {
    if (t.conectando) return;
    t.conectando = true;
    t.desconectada = false;
    try {
      const d = await pedir(`/consola/terminales/${t.info.id}/ticket`, { method: 'POST', body: '{}' });
      if (!d.ok) {
        if (d.bloqueada) { cargar(); return; }
        t.term.writeln(`\r\n\x1b[31m${d.error || 'No se pudo conectar.'}\x1b[0m`);
        return;
      }
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const q = new URLSearchParams({ ticket: d.ticket, cols: t.term.cols, rows: t.term.rows });
      const ws = new WebSocket(`${proto}//${location.host}/consola/ws/${t.info.id}?${q}`);
      ws.binaryType = 'arraybuffer';
      t.ws = ws;
      ws.onopen = () => { t.reintentos = 0; t.pestana.classList.remove('consola-pestana--caida'); };
      ws.onmessage = (ev) => {
        if (typeof ev.data !== 'string') {
          t.term.write(new Uint8Array(ev.data));
          return;
        }
        let m = {};
        try { m = JSON.parse(ev.data); } catch (e) { return; }
        if (m.fin) {
          t.term.writeln(`\r\n\x1b[90m[la terminal terminó${m.fin.codigo != null ? ' con código ' + m.fin.codigo : ''}]\x1b[0m`);
          t.terminada = true;
          setTimeout(() => quitar(t.info.id), 1500);
        } else if (m.error) {
          t.term.writeln(`\r\n\x1b[31m${m.error}\x1b[0m`);
          t.terminada = /ya no existe/.test(m.error);
        }
      };
      ws.onclose = () => {
        t.pestana.classList.add('consola-pestana--caida');
        if (t.terminada || t.desconectada || !terminales.has(t.info.id)) return;
        // Corte de red: se reengancha (la terminal sigue viva en el servidor).
        if (t.reintentos < 5 && !raiz.hidden && !document.hidden) {
          t.reintentos += 1;
          setTimeout(() => { if (activa === t.info.id) conectar(t); }, 800 * t.reintentos);
        }
      };
    } finally {
      t.conectando = false;
    }
  }

  function desconectar(t) {
    t.desconectada = true;
    if (t.ws) try { t.ws.close(); } catch (e) { /* nada */ }
    t.ws = null;
  }

  function quitar(id) {
    const t = terminales.get(id);
    if (!t) return;
    t.terminada = true;
    if (t.ws) try { t.ws.close(); } catch (e) { /* nada */ }
    t.term.dispose();
    t.caja.remove();
    t.pestana.remove();
    terminales.delete(id);
    if (activa === id) {
      activa = null;
      const ultimo = Array.from(terminales.keys()).pop();
      if (ultimo) enfocar(ultimo);
    }
    vacia.hidden = terminales.size > 0;
  }

  async function cerrarTerminal(id, boton) {
    // Doble confirmación, como los borrados del portal: un clic avisa, el segundo cierra.
    if (!boton.dataset.armado) {
      boton.dataset.armado = '1';
      boton.textContent = '¿seguro?';
      boton.classList.add('consola-pestana-cerrar--armado');
      setTimeout(() => {
        delete boton.dataset.armado;
        boton.textContent = '×';
        boton.classList.remove('consola-pestana-cerrar--armado');
      }, 3000);
      return;
    }
    const d = await pedir(`/consola/terminales/${id}/cerrar`, { method: 'POST', body: '{}' });
    if (!d.ok) { avisar(d.error); return; }
    quitar(id);
  }

  async function lanzar(tipo, boton) {
    avisar('');
    boton.disabled = true;
    const t = activa && terminales.get(activa);
    const d = await pedir('/consola/terminales', {
      method: 'POST',
      body: JSON.stringify({
        tipo, carpeta: carpeta.value.trim() || '~',
        cols: t ? t.term.cols : 120, rows: t ? t.term.rows : 32,
      }),
    });
    boton.disabled = false;
    if (!d.ok) {
      if (d.bloqueada) { cargar(); return; }
      avisar(d.error || 'No se pudo abrir la terminal.');
      return;
    }
    crearVista(d.terminal);
    vacia.hidden = true;
    enfocar(d.terminal.id);
  }

  raiz.querySelectorAll('[data-lanzar]').forEach((b) => {
    b.addEventListener('click', () => lanzar(b.dataset.lanzar, b));
  });

  try {
    const c = localStorage.getItem('consola-carpeta');
    if (c) carpeta.value = c;
  } catch (e) { /* nada */ }
  carpeta.addEventListener('change', () => {
    try { localStorage.setItem('consola-carpeta', carpeta.value); } catch (e) { /* nada */ }
  });

  document.getElementById('consola-bloquear').addEventListener('click', async () => {
    await pedir('/consola/bloquear', { method: 'POST', body: '{}' });
    terminales.forEach((t) => desconectar(t));
    cargar();
  });

  document.getElementById('consola-otras').addEventListener('click', async (ev) => {
    const b = ev.currentTarget;
    const d = await pedir('/cuenta/cerrar-otras', { method: 'POST', body: '{}' });
    b.textContent = d.ok ? `Cerradas: ${d.cerradas}` : (d.error || 'Error');
    setTimeout(() => { b.textContent = 'Cerrar mis otras sesiones'; }, 4000);
  });

  // Caducidad del desbloqueo: al pasar la hora, se vuelve al cerrojo.
  setInterval(() => {
    if (hasta && Date.now() / 1000 > hasta && !trabajo.hidden) { hasta = 0; cargar(); }
  }, 30000);

  let temporizador = null;
  window.addEventListener('resize', () => {
    clearTimeout(temporizador);
    temporizador = setTimeout(() => { const t = terminales.get(activa); if (t) ajustar(t); }, 60);
  });
  if (window.ResizeObserver) {
    new ResizeObserver(() => { const t = terminales.get(activa); if (t) ajustar(t); }).observe(pantalla);
  }

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !raiz.hidden && activa) {
      const t = terminales.get(activa);
      if (t && (!t.ws || t.ws.readyState > WebSocket.OPEN)) { t.reintentos = 0; conectar(t); }
    }
  });

  window.addEventListener('consola:mostrar', () => cargar());
})();
