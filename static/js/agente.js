/* ============================================================================
   agente.js — el cajón del asistente.

   Reglas que sigue este fichero:
     · El servidor manda. Aquí no se decide nada sobre el portal: se pinta lo
       que devuelve /agente/... y se piden las cosas con el token CSRF.
     · Nada de innerHTML con texto del modelo. Todo lo que viene de fuera pasa
       por escapar() o por textContent: el agente lee webs ajenas y su texto no
       es de fiar.
     · Si algo falla, se dice en el hilo; el portal sigue funcionando.
   ========================================================================== */

(function () {
  'use strict';

  const panel = document.getElementById('agente');
  if (!panel) return;

  /* -------------------------------------------------------------- accesos

     El cajón tiene dos accesos según el rol: «Enlaces» (el asistente) y
     «Servidor» (la consola, solo admin). Este fichero lleva el cajón y las
     pestañas; consola.js pinta el acceso «Servidor» cuando se le avisa. */

  const modos = Array.from(panel.querySelectorAll('.agente-modo'));
  const pestanasModo = Array.from(panel.querySelectorAll('.agente-modos [data-modo]'));
  const anchoBtn = document.getElementById('agente-ancho');
  const nuevaBtn = document.getElementById('agente-nueva');
  const estadoSub = document.getElementById('agente-estado');
  let modo = modos.length ? modos.find(m => !m.hidden)?.dataset.modo || modos[0].dataset.modo : 'enlaces';
  try {
    const guardado = sessionStorage.getItem('agente-modo');
    if (guardado && modos.some(m => m.dataset.modo === guardado)) modo = guardado;
  } catch (e) { /* nada */ }

  function ponerAncho(ancho) {
    panel.classList.toggle('agente--ancho', ancho);
    if (anchoBtn) anchoBtn.setAttribute('aria-pressed', ancho ? 'true' : 'false');
    window.dispatchEvent(new Event('resize'));
  }

  function elegirModo(nuevo) {
    modo = nuevo;
    modos.forEach(m => { m.hidden = m.dataset.modo !== modo; });
    pestanasModo.forEach(b => b.setAttribute('aria-selected', b.dataset.modo === modo ? 'true' : 'false'));
    const esServidor = modo === 'servidor';
    if (nuevaBtn) nuevaBtn.hidden = esServidor;
    if (anchoBtn) anchoBtn.hidden = !esServidor;
    panel.classList.toggle('agente--servidor', esServidor);
    if (estadoSub) estadoSub.textContent = esServidor ? 'consola del servidor' : 'lee enlaces y propone';
    try { sessionStorage.setItem('agente-modo', modo); } catch (e) { /* nada */ }
    if (!panel.hidden) avisarModo();
  }

  function avisarModo() {
    if (modo === 'servidor') {
      window.dispatchEvent(new CustomEvent('consola:mostrar'));
    } else if (hayAgente) {
      cargarHistorial().then(() => { alFinal(); texto.focus(); });
    }
  }

  pestanasModo.forEach(b => b.addEventListener('click', () => elegirModo(b.dataset.modo)));
  if (anchoBtn) anchoBtn.addEventListener('click', () => ponerAncho(!panel.classList.contains('agente--ancho')));

  const hilo = document.getElementById('agente-hilo');
  const form = document.getElementById('agente-form');
  const texto = document.getElementById('agente-texto');
  const enviarBtn = document.getElementById('agente-enviar');
  const estado = document.getElementById('agente-estado');
  const abrirBtn = document.getElementById('abrir-agente');
  const cabecera = window.CSRF || '';
  const hayAgente = !!hilo;

  let cargado = false;
  let ocupado = false;
  const propuestas = {};   // id -> {plan, estado}

  /* ------------------------------------------------------------- utilidades */

  function escapar(t) {
    return String(t == null ? '' : t)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // Markdown mínimo y seguro: negritas, `código`, listas y saltos de línea.
  function formatear(t) {
    let salida = escapar(t);
    salida = salida.replace(/`([^`]+)`/g, '<code>$1</code>');
    salida = salida.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    salida = salida.replace(/^\s*[-*]\s+(.*)$/gm, '· $1');
    return salida.replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>');
  }

  function alFinal() {
    hilo.scrollTop = hilo.scrollHeight;
  }

  async function pedir(url, opciones = {}) {
    const respuesta = await fetch(url, {
      ...opciones,
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': cabecera,
        ...(opciones.headers || {}),
      },
      credentials: 'same-origin',
    });
    let datos = {};
    try { datos = await respuesta.json(); } catch (e) { /* respuesta vacía */ }
    if (!respuesta.ok && !datos.error) {
      datos.error = `Error ${respuesta.status}`;
    }
    return datos;
  }

  /* --------------------------------------------------------------- pinta */

  function burbuja(rol, contenido) {
    const div = document.createElement('div');
    div.className = 'agente-msg agente-msg--' + rol;
    const cuerpo = document.createElement('div');
    cuerpo.className = 'agente-burbuja';
    if (rol === 'assistant') {
      cuerpo.innerHTML = formatear(contenido);
    } else {
      cuerpo.textContent = contenido;
    }
    div.appendChild(cuerpo);
    hilo.appendChild(div);
    return div;
  }

  function lineaTraza(traza) {
    const pasos = (traza || []).filter(p => p && p.resumen);
    if (!pasos.length) return null;
    const p = document.createElement('p');
    p.className = 'agente-traza';
    p.textContent = pasos.map(x => x.resumen).join(' · ');
    return p;
  }

  function chipUrl(url) {
    const etiqueta = url.etiqueta || url.valor;
    const tipo = url.tipo === 'internal_app' ? 'puerto '
      : url.tipo === 'subdomain' ? '' : '';
    return `<span class="plan-chip" title="${escapar(url.tipo)}: ${escapar(url.valor)}">`
      + `${escapar(tipo + etiqueta)}</span>`;
  }

  function tarjetaPropuesta(id, plan, estadoActual) {
    const caja = document.createElement('div');
    caja.className = 'plan';
    caja.dataset.propuesta = id;

    const secciones = (plan.secciones_nuevas || []).map(n =>
      `<span class="plan-seccion">nueva sección: ${escapar(n)}</span>`).join('');

    const entradas = (plan.entradas || []).map(e => `
      <li class="plan-entrada">
        <div class="plan-entrada-cab">
          <strong>${escapar(e.titulo)}</strong>
          <span class="plan-donde">${escapar(e.seccion)}${e.dentro_de ? ' › ' + escapar(e.dentro_de) : ''}</span>
        </div>
        ${e.descripcion ? `<p class="plan-desc">${escapar(e.descripcion)}</p>` : ''}
        <div class="plan-chips">${(e.urls || []).map(chipUrl).join('')}</div>
      </li>`).join('');

    const movimientos = (plan.movimientos || []).map(m => `
      <li class="plan-movimiento">mover <strong>${escapar(m.entrada)}</strong> a
        <strong>${escapar(m.seccion_destino)}</strong></li>`).join('');

    caja.innerHTML = `
      <div class="plan-cab">
        <span class="plan-titulo">Propuesta</span>
        <span class="plan-estado" data-estado>${escapar(estadoActual || 'pendiente')}</span>
      </div>
      ${plan.resumen ? `<p class="plan-resumen">${escapar(plan.resumen)}</p>` : ''}
      ${secciones ? `<div class="plan-secciones">${secciones}</div>` : ''}
      ${entradas ? `<ul class="plan-entradas">${entradas}</ul>` : ''}
      ${movimientos ? `<ul class="plan-movimientos">${movimientos}</ul>` : ''}
      <div class="plan-pie">
        <button type="button" class="boton boton--principal" data-accion="aplicar">Aplicar</button>
        <button type="button" class="boton" data-accion="descartar">Descartar</button>
        <button type="button" class="boton boton--plano plan-ver" data-accion="json">Ver JSON</button>
      </div>
      <div class="plan-json" hidden>
        <div class="plan-json-cab">
          <span>Esto es exactamente lo que se va a guardar</span>
          <button type="button" class="boton boton--plano" data-accion="copiar">Copiar</button>
        </div>
        <pre class="plan-json-codigo"></pre>
      </div>
      <p class="plan-resultado" hidden></p>`;

    // El JSON se pinta con textContent, nunca con innerHTML: viene del modelo.
    caja.querySelector('.plan-json-codigo').textContent = JSON.stringify(plan, null, 2);

    if (estadoActual && estadoActual !== 'pendiente') {
      marcarResuelta(caja, estadoActual);
    }
    caja.addEventListener('click', (ev) => {
      const boton = ev.target.closest('[data-accion]');
      if (!boton) return;
      const accion = boton.dataset.accion;
      if (accion === 'aplicar') aplicar(caja, id);
      else if (accion === 'descartar') descartar(caja, id);
      else if (accion === 'json') {
        const bloque = caja.querySelector('.plan-json');
        bloque.hidden = !bloque.hidden;
        boton.textContent = bloque.hidden ? 'Ver JSON' : 'Ocultar JSON';
      } else if (accion === 'copiar') {
        const texto = caja.querySelector('.plan-json-codigo').textContent;
        const hecho = () => { boton.textContent = 'Copiado'; setTimeout(() => { boton.textContent = 'Copiar'; }, 1400); };
        if (navigator.clipboard) navigator.clipboard.writeText(texto).then(hecho).catch(() => {});
        else hecho();
      }
    });
    return caja;
  }

  function marcarResuelta(caja, estadoTexto) {
    const etiqueta = caja.querySelector('[data-estado]');
    if (etiqueta) etiqueta.textContent = estadoTexto;
    caja.dataset.resuelta = estadoTexto;
    // Solo se bloquean las dos acciones que deciden; «Ver JSON» debe seguir
    // funcionando para poder revisar qué se aplicó.
    caja.querySelectorAll('.plan-pie [data-accion="aplicar"], .plan-pie [data-accion="descartar"]')
      .forEach(b => { b.disabled = true; });
  }

  /* --------------------------------------------------------------- acciones */

  async function aplicar(caja, id) {
    if (caja.dataset.resuelta) return;
    const pie = caja.querySelector('.plan-pie');
    const decidir = () => pie.querySelectorAll('[data-accion="aplicar"], [data-accion="descartar"]');
    decidir().forEach(b => { b.disabled = true; });
    const nota = caja.querySelector('.plan-resultado');
    nota.hidden = false;
    nota.textContent = 'Aplicando…';

    const datos = await pedir(`/agente/aplicar/${encodeURIComponent(id)}`, { method: 'POST', body: '{}' });
    if (!datos.ok) {
      nota.className = 'plan-resultado mal';
      nota.textContent = datos.error || 'No se pudo aplicar.';
      decidir().forEach(b => { b.disabled = false; });
      return;
    }

    const trozos = [];
    if (datos.secciones && datos.secciones.length) trozos.push(`${datos.secciones.length} sección(es) nueva(s)`);
    if (datos.entradas && datos.entradas.length) trozos.push(`${datos.entradas.length} entrada(s)`);
    if (datos.movidas && datos.movidas.length) trozos.push(`${datos.movidas.length} movimiento(s)`);
    if (datos.omitidas && datos.omitidas.length) trozos.push(`${datos.omitidas.length} omitida(s)`);
    nota.className = 'plan-resultado ok';
    nota.textContent = 'Aplicado: ' + (trozos.join(' · ') || 'sin cambios')
      + ((datos.avisos && datos.avisos.length) ? ' · ' + datos.avisos.join('; ') : '')
      + ' — recargando…';
    marcarResuelta(caja, 'aplicada');

    // La portada se recarga para que la sección nueva aparezca ya colocada.
    try { sessionStorage.setItem('agente-abierto', '1'); } catch (e) { /* nada */ }
    setTimeout(() => window.location.reload(), 1500);
  }

  async function descartar(caja, id) {
    if (caja.dataset.resuelta) return;
    const datos = await pedir(`/agente/descartar/${encodeURIComponent(id)}`, { method: 'POST', body: '{}' });
    const nota = caja.querySelector('.plan-resultado');
    nota.hidden = false;
    if (datos.ok) {
      nota.className = 'plan-resultado tenue';
      nota.textContent = 'Descartada. No se ha tocado nada.';
      marcarResuelta(caja, 'descartada');
    } else {
      nota.className = 'plan-resultado mal';
      nota.textContent = datos.error || 'No se pudo descartar.';
    }
  }

  /* ----------------------------------------------------------------- envío */

  function indicador() {
    const div = document.createElement('div');
    div.className = 'agente-msg agente-msg--assistant';
    div.innerHTML = '<div class="agente-escribiendo"><span></span><span></span><span></span></div>';
    hilo.appendChild(div);
    alFinal();
    return div;
  }

  async function enviar(mensaje) {
    if (ocupado) return;
    const limpio = (mensaje || '').trim();
    if (!limpio) return;

    ocupado = true;
    enviarBtn.disabled = true;
    texto.value = '';
    texto.style.height = 'auto';
    burbuja('user', limpio);
    const espera = indicador();
    estado.textContent = 'pensando…';

    const datos = await pedir('/agente/mensaje', {
      method: 'POST',
      body: JSON.stringify({ mensaje: limpio }),
    });
    espera.remove();
    estado.textContent = 'lee enlaces y propone';

    const respuesta = datos.respuesta || datos.error;
    if (!respuesta) {
      burbuja('assistant', 'No he obtenido respuesta. Inténtalo otra vez.');
    } else {
      const nodo = burbuja('assistant', respuesta);
      const traza = lineaTraza(datos.traza);
      if (traza) nodo.appendChild(traza);
      if (datos.propuesta_id && datos.propuesta) {
        propuestas[datos.propuesta_id] = datos.propuesta;
        nodo.appendChild(tarjetaPropuesta(datos.propuesta_id, datos.propuesta, 'pendiente'));
      }
      if (!datos.ok) nodo.classList.add('agente-msg--error');
    }
    alFinal();
    ocupado = false;
    enviarBtn.disabled = false;
    texto.focus();
  }

  function nodoClaseError() {
    const ultimo = hilo.lastElementChild;
    if (ultimo) ultimo.classList.add('agente-msg--error');
  }

  /* -------------------------------------------------------------- historial */

  // Una sola carga a la vez: abrir() y el atajo del monitor la piden casi juntas
  let cargando = null;
  function cargarHistorial() {
    if (!cargando) cargando = cargarHistorialAhora().finally(() => { cargando = null; });
    return cargando;
  }

  async function cargarHistorialAhora() {
    if (cargado) return;
    const datos = await pedir('/agente/historial', { method: 'GET' });
    if (!datos.ok) {
      burbuja('assistant', 'No he podido cargar la conversación: ' + (datos.error || 'error'));
      return;
    }
    (datos.propuestas || []).forEach(p => { propuestas[p.id] = { plan: p.plan, estado: p.estado }; });

    if (!datos.mensajes || !datos.mensajes.length) {
      const bienvenida = document.createElement('div');
      bienvenida.className = 'agente-vacio';
      bienvenida.innerHTML =
        '<p class="agente-vacio-titulo">Pega enlaces y yo los coloco.</p>'
        + '<p>Cuéntame qué son o déjame leerlos. Te propongo sección, título y agrupación, '
        + 'y tú decides con un botón.</p>'
        + '<div class="agente-ejemplos">'
        + '<button type="button" class="agente-ejemplo" data-texto="Mira estos enlaces y añádelos donde encajen: ">'
        + '«Añade estos enlaces»</button>'
        + '<button type="button" class="agente-ejemplo" data-texto="Revisa el portal y propón una agrupación mejor de las secciones que hay.">'
        + '«Reordena el portal»</button>'
        + '<button type="button" class="agente-ejemplo" data-texto="Quiero una sección nueva para mis herramientas de IA. Te paso enlaces: ">'
        + '«Sección nueva»</button>'
        + '<button type="button" class="agente-ejemplo" data-texto="Resúmeme los últimos cortes de luz y reinicios del servidor y dame un diagnóstico.">'
        + '«¿Ha habido cortes?»</button>'
        + '</div>';
      hilo.appendChild(bienvenida);
      hilo.addEventListener('click', (ev) => {
        const b = ev.target.closest('.agente-ejemplo');
        if (!b) return;
        texto.value = b.dataset.texto;
        texto.focus();
        autoAlto();
      });
      cargado = true;
      return;
    }

    (datos.mensajes || []).forEach(m => {
      const nodo = burbuja(m.rol, m.contenido);
      const traza = lineaTraza(m.traza);
      if (traza) nodo.appendChild(traza);
      const idPropuesta = (m.traza || []).map(t => t && t.propuesta_id).find(Boolean);
      if (idPropuesta && propuestas[idPropuesta]) {
        nodo.appendChild(tarjetaPropuesta(idPropuesta, propuestas[idPropuesta].plan,
          propuestas[idPropuesta].estado));
      }
    });
    // propuestas que no cuelgan de un mensaje concreto (no debería haber, pero
    // así ninguna queda invisible)
    Object.keys(propuestas).forEach(id => {
      if (hilo.querySelector(`[data-propuesta="${id}"]`)) return;
      hilo.appendChild(tarjetaPropuesta(id, propuestas[id].plan, propuestas[id].estado));
    });
    cargado = true;
    alFinal();
  }

  /* ----------------------------------------------------------------- panel */

  function abrir() {
    // El cajón es el mismo sitio que el del monitor: si está abierto, se cierra
    // para no apilar dos paneles a la derecha.
    const monitorAbierto = document.getElementById('monitor');
    if (monitorAbierto && !monitorAbierto.hidden) {
      const cerrarMonitor = document.getElementById('monitor-cerrar');
      if (cerrarMonitor) cerrarMonitor.click();
    }

    panel.hidden = false;
    document.body.classList.add('agente-abierto');
    if (abrirBtn) abrirBtn.setAttribute('aria-expanded', 'true');
    avisarModo();
    try { sessionStorage.setItem('agente-abierto', '1'); } catch (e) { /* nada */ }
  }

  function cerrar() {
    panel.hidden = true;
    document.body.classList.remove('agente-abierto');
    if (abrirBtn) abrirBtn.setAttribute('aria-expanded', 'false');
    try { sessionStorage.setItem('agente-abierto', '0'); } catch (e) { /* nada */ }
  }

  function autoAlto() {
    if (!texto) return;
    texto.style.height = 'auto';
    texto.style.height = Math.min(texto.scrollHeight, 160) + 'px';
  }

  /* --------------------------------------------------------------- arranque */

  if (abrirBtn) abrirBtn.addEventListener('click', () => (panel.hidden ? abrir() : cerrar()));
  document.getElementById('agente-cerrar').addEventListener('click', cerrar);
  elegirModo(modo);

  // Escape cierra el cajón, como los diálogos del portal (no dentro de una terminal).
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape' || panel.hidden || document.querySelector('.dialogo:not([hidden])')) return;
    const foco = document.activeElement;
    if (foco && foco.closest('.xterm')) return;   // en la terminal, Esc es de la terminal
    if (panel.contains(foco) || foco === document.body || foco === abrirBtn) {
      cerrar();
      if (abrirBtn) abrirBtn.focus();
    }
  });

  try {
    if (sessionStorage.getItem('agente-abierto') === '1') abrir();
  } catch (e) { /* nada */ }

  if (!hayAgente) return;   // solo consola: lo de abajo es del asistente de enlaces

  // Para el botón «Pedir diagnóstico» del monitor: abre el cajón y envía.
  window.preguntarAsistente = async (pregunta) => {
    if (modo !== 'enlaces') elegirModo('enlaces');
    if (panel.hidden) abrir();
    await cargarHistorial();
    enviar(pregunta);
  };

  nuevaBtn.addEventListener('click', async () => {
    const datos = await pedir('/agente/nueva', { method: 'POST', body: '{}' });
    if (!datos.ok) return;
    hilo.innerHTML = '';
    Object.keys(propuestas).forEach(k => delete propuestas[k]);
    cargado = false;
    await cargarHistorial();
    alFinal();
  });

  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    enviar(texto.value);
  });

  texto.addEventListener('input', autoAlto);
  texto.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      enviar(texto.value);
    }
  });

})();
