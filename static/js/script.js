/* ============================================================================
   LinkManager — interfaz
   Sin jQuery ni Bootstrap: diálogos, buscador, arrastre, subdivisiones y
   preferencias con JS del navegador. Animaciones solo de transform/opacity
   (guía 08 del kit de diseño).
   ========================================================================== */
// Los datos del portal llegan como JSON (la CSP no admite <script> en línea).
(() => {
  try {
    const datos = JSON.parse(document.getElementById('datos-portal')?.textContent || '{}');
    Object.assign(window, datos);
  } catch (e) { /* sin datos: el portal funciona en modo lectura */ }
})();

(() => {
  'use strict';

  const $  = (sel, raiz = document) => raiz.querySelector(sel);
  const $$ = (sel, raiz = document) => Array.from(raiz.querySelectorAll(sel));

  const escapar = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const guardar = (clave, valor) => { try { localStorage.setItem(clave, valor); } catch (e) { /* privacidad */ } };
  const leer    = (clave, porDefecto = null) => { try { return localStorage.getItem(clave) ?? porDefecto; } catch (e) { return porDefecto; } };

  let sortables = [];

  /* --------------------------------------------------- empaquetado (masonry)

     La rejilla usa filas de 8px. Aquí se mide cada tarjeta y se le dice
     cuántas filas ocupa, para que las de distinta altura se empaqueten sin
     dejar huecos (una con portada al lado de otra sin ella dejaba un boquete).
     El alto de una tarjeta no depende de su span (la rejilla alinea arriba),
     así que medir y aplicar no se realimenta. */

  const FILA = 8;      // alto de fila en el CSS
  const HUECO = 12;    // separación de la rejilla
  const PASO = FILA + HUECO;
  let empaquetadoPendiente = false;

  function empaquetar() {
    empaquetadoPendiente = false;
    $$('.rejilla').forEach((rejilla) => {
      Array.from(rejilla.children).forEach((item) => {
        if (item.hidden) return;
        const alto = item.getBoundingClientRect().height;
        if (!alto) return;
        const span = `span ${Math.ceil((alto + HUECO) / PASO)}`;
        if (item.style.gridRowEnd !== span) item.style.gridRowEnd = span;
      });
    });
  }

  function pedirEmpaquetado() {
    if (empaquetadoPendiente) return;
    empaquetadoPendiente = true;
    requestAnimationFrame(empaquetar);
  }

  if (typeof ResizeObserver !== 'undefined') {
    const observador = new ResizeObserver(pedirEmpaquetado);
    $$('.rejilla > *').forEach((el) => observador.observe(el));
  }
  window.addEventListener('resize', pedirEmpaquetado);
  window.addEventListener('load', pedirEmpaquetado);
  pedirEmpaquetado();

  /* ----------------------------------------------------------- diálogos */

  // Al cerrar un diálogo el foco vuelve a lo que lo abrió (teclado y lectores de pantalla).
  const origenDialogo = new WeakMap();

  function abrir(id) {
    const dlg = document.getElementById(id);
    if (!dlg) return;
    if (dlg.hidden && document.activeElement && document.activeElement !== document.body) {
      origenDialogo.set(dlg, document.activeElement);
    }
    dlg.hidden = false;
    document.body.style.overflow = 'hidden';
    // primero el campo a rellenar; el botón de cerrar va antes en el HTML pero no es lo que se busca
    const primero = dlg.querySelector('input:not([type=hidden]):not([type=file]),select,textarea') || dlg.querySelector('button');
    if (primero) setTimeout(() => primero.focus(), 40);
  }

  function cerrar(dlg) {
    if (!dlg) return;
    dlg.hidden = true;
    if (!$('.dialogo:not([hidden])')) document.body.style.overflow = '';
    const origen = origenDialogo.get(dlg);
    origenDialogo.delete(dlg);
    if (origen && origen.isConnected) origen.focus();
  }

  /* -------------------------------------------- acciones extra en el móvil

     En teléfonos estrechos (≤480px) los accesos secundarios se pliegan tras
     «Más acciones»: así los botones conservan un tamaño táctil cómodo. */

  const masAcciones = $('#cabecera-mas');
  const accionesExtra = $('#cabecera-extra');
  const menuAbierto = () => !!accionesExtra?.classList.contains('abierta');

  function cerrarMenu(devolverFoco) {
    if (!menuAbierto()) return false;
    accionesExtra.classList.remove('abierta');
    masAcciones?.setAttribute('aria-expanded', 'false');
    if (devolverFoco) masAcciones?.focus();
    return true;
  }

  if (masAcciones && accionesExtra) {
    masAcciones.addEventListener('click', () => {
      if (menuAbierto()) { cerrarMenu(true); return; }
      accionesExtra.classList.add('abierta');
      masAcciones.setAttribute('aria-expanded', 'true');
      const primero = accionesExtra.querySelector('button, a');
      if (primero) setTimeout(() => primero.focus(), 30);
    });
    accionesExtra.addEventListener('click', (e) => {
      const accion = e.target.closest('button, a');
      if (!accion) return;
      // Si abre un diálogo, el foco vuelve a «Más acciones» al cerrarlo:
      // el botón original queda oculto al plegar el menú.
      if (accion.matches('[data-abrir]')) masAcciones.focus();
      cerrarMenu(false);
    });
    document.addEventListener('click', (e) => {
      if (menuAbierto() && !accionesExtra.contains(e.target) && !masAcciones.contains(e.target)) {
        cerrarMenu(false);
      }
    });
    window.addEventListener('resize', () => { if (window.innerWidth > 480) cerrarMenu(false); });
  }

  document.addEventListener('click', (e) => {
    const abridor = e.target.closest('[data-abrir]');
    if (abridor) { e.preventDefault(); abrir(abridor.dataset.abrir); return; }

    const fechar = e.target.closest('.fechar');
    if (fechar) { e.preventDefault(); cerrar(fechar.closest('.dialogo')); return; }

    if (e.target.classList.contains('dialogo')) cerrar(e.target);

    const cerrarAviso = e.target.closest('.aviso button');
    if (cerrarAviso) cerrarAviso.closest('.aviso').remove();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (cerrarMenu(true)) { e.preventDefault(); return; }
      const abierto = $$('.dialogo:not([hidden])').pop();
      if (abierto) { cerrar(abierto); return; }
    }
    const escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (e.key === '/' && !escribiendo) { e.preventDefault(); $('#buscador')?.focus(); return; }
    if (!window.LOGUEADO || escribiendo) return;
    if (e.key.toLowerCase() === 'n') { e.preventDefault(); abrir('dlg-nueva-entrada'); }
    if (e.key.toLowerCase() === 's') { e.preventDefault(); abrir('dlg-nueva-seccion'); }
  });

  /* ------------------------------------------------- subdivisiones (grupos)

     Una carpeta se abre en un panel flotante, por encima de la rejilla: abrirla
     no empuja ni recoloca ninguna otra tarjeta. Su contenido (.rejilla-hijos)
     se mueve al panel al abrir y vuelve a su sitio al cerrar. Solo al buscar
     se enseñan los hijos que coinciden dentro de la propia sección. */

  (function grupos() {
    const velo = document.getElementById('carpeta-velo');
    if (!velo) return;
    const caja = $('.carpeta-flotante', velo);
    const cuerpo = document.getElementById('carpeta-cuerpo');
    const titulo = document.getElementById('carpeta-titulo');
    const sub = document.getElementById('carpeta-sub');
    let abierta = null;   // { tarjeta, contenido, hueco, boton }

    const panelDe = (tarjeta) => document.getElementById('hijos-' + tarjeta.dataset.padre);

    function abrirCarpeta(tarjeta, boton) {
      if (abierta) cerrarCarpeta(false);
      const panel = panelDe(tarjeta);
      const contenido = panel && $('.rejilla-hijos', panel);
      if (!contenido) return;

      // un hueco marca dónde vuelve el contenido al cerrar
      const hueco = document.createComment('carpeta');
      contenido.before(hueco);
      cuerpo.appendChild(contenido);
      panel.hidden = true;
      // al abrir desde una búsqueda se enseña la carpeta entera
      $$('.tarjeta', contenido).forEach((h) => { h.hidden = false; });

      const n = $$('.tarjeta', contenido).length;
      titulo.textContent = ($('.tarjeta-titulo', tarjeta) || {}).textContent || 'Carpeta';
      const desc = ($('.tarjeta-desc', tarjeta) || {}).textContent || '';
      sub.textContent = `${n} ${n === 1 ? 'enlace' : 'enlaces'}${desc ? ' · ' + desc : ''}`;

      // la carpeta crece desde donde está su tarjeta
      const r = tarjeta.getBoundingClientRect();
      caja.style.setProperty('--origen-x', `${r.left + r.width / 2}px`);
      caja.style.setProperty('--origen-y', `${r.top + r.height / 2}px`);

      abierta = { tarjeta, contenido, hueco, boton: boton || $('.grupo-pie', tarjeta) };
      tarjeta.dataset.abierto = '1';
      if (abierta.boton) abierta.boton.setAttribute('aria-expanded', 'true');
      velo.classList.remove('cerrando');
      velo.hidden = false;
      document.body.style.overflow = 'hidden';
      document.getElementById('carpeta-cerrar').focus({ preventScroll: true });
    }

    function cerrarCarpeta(devolverFoco = true) {
      if (!abierta) return;
      const { tarjeta, contenido, hueco, boton } = abierta;
      abierta = null;
      hueco.replaceWith(contenido);
      tarjeta.dataset.abierto = '0';
      if (boton) boton.setAttribute('aria-expanded', 'false');
      if (!$('.dialogo:not([hidden])')) document.body.style.overflow = '';
      if (devolverFoco && boton) boton.focus({ preventScroll: true });

      const fin = () => { velo.hidden = true; velo.classList.remove('cerrando'); };
      if (!devolverFoco) { fin(); return; }
      velo.classList.add('cerrando');
      setTimeout(fin, 160);
      // si había una búsqueda, se vuelve a aplicar sobre el contenido devuelto
      const buscador = $('#buscador');
      if (buscador && buscador.value.trim()) buscador.dispatchEvent(new Event('input'));
    }

    document.addEventListener('click', (e) => {
      const boton = e.target.closest('.grupo-pie');
      const mosaico = !boton && e.target.closest('.tarjeta--grupo .tarjeta-mosaico');
      if (boton || mosaico) {
        e.preventDefault();
        const tarjeta = (boton || mosaico).closest('.tarjeta');
        if (abierta && abierta.tarjeta === tarjeta) cerrarCarpeta();
        else abrirCarpeta(tarjeta, boton);
        return;
      }
      if (e.target.closest('#carpeta-cerrar') || e.target === velo) cerrarCarpeta();
    });

    document.addEventListener('keydown', (e) => {
      // con un diálogo encima (editar una tarjeta de la carpeta), Esc cierra
      // primero el diálogo
      if (e.key === 'Escape' && abierta && !$('.dialogo:not([hidden])')) cerrarCarpeta();
    }, true);   // en captura: decide antes de que el otro Esc cierre el diálogo

    // la búsqueda trabaja sobre la rejilla: antes de filtrar, se cierra
    document.addEventListener('lm:cerrar-carpeta', () => cerrarCarpeta(false));
  })();

  /* ------------------------------------------ doble confirmación al eliminar

     Nada se borra al primer clic: el botón se convierte en una pregunta roja y
     solo el segundo clic envía el formulario. Si pasa un rato sin confirmar,
     el botón vuelve solo a su sitio. Vale para entradas y para secciones. */

  (function confirmarBorrados() {
    let pendiente = null;

    function reposar(boton) {
      if (!boton || boton.dataset.listo !== '1') return;
      clearTimeout(boton._reposo);
      boton.classList.remove('confirmando');
      if (boton.dataset.icono) boton.innerHTML = boton.dataset.icono;
      boton.dataset.listo = '';
      boton.title = 'Eliminar';
      if (pendiente === boton) pendiente = null;
    }

    document.addEventListener('click', (e) => {
      const form = e.target.closest('form[data-confirmar]');
      if (!form) return;
      const boton = e.target.closest('button');
      if (!boton) return;
      if (boton.dataset.listo === '1') return;   // segundo clic: pasa el envío

      e.preventDefault();
      if (pendiente && pendiente !== boton) reposar(pendiente);
      if (!boton.dataset.icono) boton.dataset.icono = boton.innerHTML;
      boton.dataset.listo = '1';
      boton.classList.add('confirmando');
      boton.textContent = '¿Eliminar?';
      boton.title = `Pulsa otra vez para confirmar: ${form.dataset.confirmar || ''}`;
      pendiente = boton;
      boton._reposo = setTimeout(() => reposar(boton), 4000);
    });
  })();

  /* ------------------------------------------------------- buscador */

  (function buscador() {
    const input = $('#buscador');
    if (!input) return;
    const contador = $('#contador');
    const sinNada = $('#sin-resultados');
    const todas = $$('.tarjeta');
    const principales = $$('.tarjeta:not(.tarjeta--hijo)');

    function filtrar() {
      document.dispatchEvent(new Event('lm:cerrar-carpeta'));
      const q = input.value.trim().toLowerCase();
      let visibles = 0;

      todas.forEach((t) => {
        const coincide = !q || (t.dataset.buscar || '').includes(q);
        t.hidden = !coincide;
        if (coincide && !t.classList.contains('tarjeta--hijo')) visibles++;
      });

      // un grupo se abre si la coincidencia está dentro; al limpiar, vuelve
      // a como lo hubiera dejado el usuario
      $$('.grupo-hijos').forEach((panel) => {
        const padre = document.querySelector(`.tarjeta[data-padre="${panel.dataset.padre}"]`);
        if (q) {
          const hay = $$('.tarjeta--hijo', panel).some((h) => !h.hidden);
          panel.hidden = !hay;
          if (hay && padre) { padre.hidden = false; visibles++; }
        } else {
          panel.hidden = true;
        }
      });

      $$('.seccion').forEach((s) => {
        s.hidden = !s.querySelector('.tarjeta:not([hidden])');
      });

      if (contador) contador.textContent = q ? `${visibles} de ${principales.length}` : '';
      if (sinNada) sinNada.hidden = !(q && visibles === 0);
      pedirEmpaquetado();
    }

    input.addEventListener('input', filtrar);
    input.value = '';
    filtrar();
  })();

  /* --------------------------------------------------- vista y modo edición */

  const btnVista = $('#cambiar-vista');
  function fijarVista(portada) {
    document.body.classList.toggle('vista-portada', portada);
    if (btnVista) btnVista.setAttribute('aria-pressed', String(portada));
    guardar('lm-vista', portada ? 'portada' : 'compacta');
    pedirEmpaquetado();
  }

  const btnEdicion = $('#modo-edicion');
  function fijarEdicion(activo) {
    document.body.classList.toggle('modo-edicion', activo);
    if (btnEdicion) btnEdicion.setAttribute('aria-pressed', String(activo));
    guardar('lm-edicion', activo ? '1' : '0');
    sortables.forEach((s) => s.option('disabled', !activo));
  }

  /* ------------------------------------------------------ secciones plegables */

  function plegarSeccion(seccion, plegada) {
    seccion.dataset.plegada = plegada ? '1' : '0';
    guardar('lm-plegada-' + seccion.dataset.id, plegada ? '1' : '0');
  }

  $$('.seccion').forEach((s) => {
    const boton = $('.seccion-plegar', s);
    if (!boton) return;
    plegarSeccion(s, leer('lm-plegada-' + s.dataset.id, '0') === '1');
    boton.addEventListener('click', () => {
      plegarSeccion(s, s.dataset.plegada !== '1');
      pedirEmpaquetado();
    });
  });

  const btnPlegarTodo = $('#plegar-todo');
  function rotularPlegarTodo() {
    if (!btnPlegarTodo) return;
    const hayAbiertas = $$('.seccion').some((s) => s.dataset.plegada !== '1');
    const texto = $('span', btnPlegarTodo);
    if (texto) texto.textContent = hayAbiertas ? 'Plegar todo' : 'Desplegar todo';
    btnPlegarTodo.setAttribute('aria-pressed', String(!hayAbiertas));
  }
  if (btnPlegarTodo) {
    rotularPlegarTodo();
    btnPlegarTodo.addEventListener('click', () => {
      const hayAbiertas = $$('.seccion').some((s) => s.dataset.plegada !== '1');
      $$('.seccion').forEach((s) => plegarSeccion(s, hayAbiertas));
      rotularPlegarTodo();
      pedirEmpaquetado();
    });
  }

  /* -------------------------------------------------- selector de entorno */

  const segmentado = $('#entorno');
  function construirEnlaces(entorno) {
    const base = window.APP_DOMAINS?.[entorno];
    $$('.dynamic-link').forEach((a) => {
      const tipo = a.dataset.linkType;
      try {
        if (tipo === 'external_url') { a.href = a.dataset.value; return; }
        if (!base) { a.href = '#'; return; }

        const u = new URL(base);
        if (tipo === 'internal_app') {
          const puerto = String(a.dataset.port);
          const esquema = ['443', '8443', '9443', '10000'].includes(puerto) ? 'https:' : u.protocol;
          a.href = `${esquema}//${u.hostname}:${puerto}`;
        } else if (tipo === 'subdomain') {
          a.href = entorno === 'public' && window.APP_DOMAINS.public
            ? `${u.protocol}//${a.dataset.subdomain}.${u.hostname}`
            : '#';
        }
      } catch (err) {
        console.error('URL base inválida:', base);
        a.href = '#';
      }
    });
  }

  if (segmentado) {
    const botones = $$('button', segmentado);
    const fijarEntorno = (entorno) => {
      botones.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.entorno === entorno)));
      construirEnlaces(entorno);
      guardar('lm-entorno', entorno);
    };
    botones.forEach((b) => b.addEventListener('click', () => fijarEntorno(b.dataset.entorno)));
    fijarEntorno(leer('lm-entorno', 'public'));
  }

  /* -------------------------------------------------------------- arrastre */

  function montarArrastre() {
    if (!window.LOGUEADO || typeof Sortable === 'undefined') return;

    // Solo los hijos DIRECTOS de la rejilla: los que cuelgan de un grupo van
    // dentro de su panel y no deben entrar en el orden de la sección.
    const idsDe = (rejilla) => Array.from(rejilla.children)
      .filter((el) => el.classList.contains('tarjeta'))
      .map((t) => t.dataset.id);

    const mandarOrden = (tipo, orden, seccion = null, entrada = null) => {
      const cuerpo = { type: tipo, order: orden };
      if (seccion) cuerpo.section_id = seccion;
      if (entrada) cuerpo.entry_id = entrada;
      fetch('/update_order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.CSRF },
        body: JSON.stringify(cuerpo),
      }).catch((e) => console.error('No se pudo guardar el orden:', e));
    };

    const lista = $('.contenido');
    if (lista) {
      sortables.push(new Sortable(lista, {
        animation: 160,
        draggable: '.seccion',
        handle: '.seccion-plegar',
        ghostClass: 'arrastrando',
        disabled: true,
        onEnd(evt) {
          mandarOrden('sections', $$('.seccion', evt.to).map((s) => s.dataset.id));
        },
      }));
    }

    $$('.rejilla').forEach((rejilla) => {
      sortables.push(new Sortable(rejilla, {
        group: 'tarjetas',
        animation: 160,
        draggable: '.tarjeta',
        handle: '.tarjeta-asa',
        ghostClass: 'arrastrando',
        disabled: true,
        onEnd(evt) {
          mandarOrden('entries', idsDe(evt.to), evt.to.dataset.seccion, evt.item.dataset.id);
          if (evt.from !== evt.to) mandarOrden('entries', idsDe(evt.from), evt.from.dataset.seccion);
          pedirEmpaquetado();
        },
      }));
    });
  }

  montarArrastre();

  if (btnVista) {
    fijarVista(leer('lm-vista', 'portada') === 'portada');
    btnVista.addEventListener('click', () => fijarVista(!document.body.classList.contains('vista-portada')));
  }
  if (btnEdicion) {
    fijarEdicion(leer('lm-edicion', '0') === '1');
    btnEdicion.addEventListener('click', () => fijarEdicion(!document.body.classList.contains('modo-edicion')));
  }

  /* ------------------------------------------------------- formulario de enlaces */

  if (!window.LOGUEADO) return;

  let contadorEnlaces = 0;

  function campoValor(indice, tipo, valor) {
    const v = escapar(valor);
    if (tipo === 'internal_app') {
      return `<label>Puerto</label><input type="number" name="urls[${indice}][value]" placeholder="8096" value="${v}" required>`;
    }
    if (tipo === 'subdomain') {
      return `<label>Subdominio</label><input type="text" name="urls[${indice}][value]" placeholder="jellyfin" value="${v}" required>`;
    }
    return `<label>Dirección</label><input type="url" name="urls[${indice}][value]" placeholder="https://ejemplo.com" value="${v}" required>`;
  }

  function bloqueEnlace(indice, enlace = null) {
    const tipo  = enlace ? enlace.link_type : 'internal_app';
    const valor = enlace ? enlace.value : '';
    const label = enlace ? enlace.label : '';
    const id    = enlace ? enlace.id : 'new';
    const opcion = (t, texto) => `<label><input type="radio" name="urls[${indice}][type]" value="${t}"
        ${tipo === t ? 'checked' : ''}> ${texto}</label>`;

    return `<div class="grupo-enlace" data-indice="${indice}">
      <input type="hidden" name="urls[${indice}][id]" value="${escapar(id)}">
      <div class="tipos">
        ${opcion('internal_app', 'Puerto interno')}
        ${opcion('subdomain', 'Subdominio')}
        ${opcion('external_url', 'Dirección externa')}
      </div>
      <div class="fila">
        <div class="campo"><label>Etiqueta <small>(opcional)</small></label>
          <input type="text" name="urls[${indice}][label]" placeholder="Web" value="${escapar(label)}"></div>
        <div class="campo campo-valor">${campoValor(indice, tipo, valor)}</div>
      </div>
      <button type="button" class="boton boton--plano boton--peligro quitar-enlace" style="justify-self:start">Quitar</button>
    </div>`;
  }

  document.addEventListener('change', (e) => {
    const radio = e.target.closest('input[type=radio][name^="urls"]');
    if (!radio) return;
    const bloque = radio.closest('.grupo-enlace');
    $('.campo-valor', bloque).innerHTML = campoValor(bloque.dataset.indice, radio.value, '');
  });

  document.addEventListener('click', (e) => {
    const quitar = e.target.closest('.quitar-enlace');
    if (quitar) { quitar.closest('.grupo-enlace').remove(); return; }
    if (e.target.closest('#anadir-enlace-nueva')) {
      $('#enlaces-nueva').insertAdjacentHTML('beforeend', bloqueEnlace(contadorEnlaces++));
    }
    if (e.target.closest('#anadir-enlace-editar')) {
      $('#enlaces-editar').insertAdjacentHTML('beforeend', bloqueEnlace(contadorEnlaces++));
    }
  });

  const zonaNueva = $('#zona-nueva');
  if (zonaNueva && !$('#enlaces-nueva').children.length) {
    $('#enlaces-nueva').insertAdjacentHTML('beforeend', bloqueEnlace(contadorEnlaces++));
  }

  /* ------------------------------------------- «Dentro de» filtrado por sección

     Un padre tiene que estar en la misma sección, así que la lista se filtra
     sola al cambiar de sección en lugar de dejar elegir algo que no vale. */

  const selectPadres = $('#padre-nueva');
  function filtrarPadres() {
    if (!selectPadres) return;
    const seccion = $('#sec-nueva')?.value;
    const elegido = selectPadres.value;
    let sigueValiendo = false;
    $$('option', selectPadres).forEach((o) => {
      const esMarcador = !o.value;
      const vale = esMarcador || o.dataset.seccion === String(seccion);
      o.hidden = !vale;
      o.disabled = !vale;
      if (vale && o.value === elegido) sigueValiendo = true;
    });
    if (!sigueValiendo) selectPadres.value = '';
  }

  const secNueva = $('#sec-nueva');
  if (secNueva) {
    filtrarPadres();
    secNueva.addEventListener('change', filtrarPadres);
  }

  /* ------------------------------------------------------- zona de imagen */

  function prepararZona(zona) {
    if (!zona) return;
    const entrada = $('input[type=file]', zona);
    const previa = $('.vista-previa', zona);
    const indicacion = $('.indicacion', zona);

    function pintar(archivo) {
      if (!archivo || !archivo.type.startsWith('image/')) return;
      const dt = new DataTransfer();
      dt.items.add(archivo);
      entrada.files = dt.files;
      const lector = new FileReader();
      lector.onload = () => {
        previa.innerHTML = `<img src="${lector.result}" alt="">`;
        if (indicacion) indicacion.hidden = true;
      };
      lector.readAsDataURL(archivo);
    }

    zona.addEventListener('click', () => entrada.click());
    entrada.addEventListener('change', () => entrada.files[0] && pintar(entrada.files[0]));
    zona.addEventListener('dragover', (e) => { e.preventDefault(); zona.classList.add('encima'); });
    zona.addEventListener('dragleave', () => zona.classList.remove('encima'));
    zona.addEventListener('drop', (e) => {
      e.preventDefault(); zona.classList.remove('encima');
      if (e.dataTransfer.files[0]) pintar(e.dataTransfer.files[0]);
    });
    zona.pintar = pintar;
  }
  prepararZona(zonaNueva);

  document.addEventListener('paste', (e) => {
    const dlg = $('.dialogo:not([hidden])');
    if (!dlg) return;
    const zona = $('.zona-imagen', dlg);
    if (zona && zona.pintar && e.clipboardData.files[0]) {
      e.preventDefault();
      zona.pintar(e.clipboardData.files[0]);
    }
  });

  /* --------------------------------------------------- editar una entrada */

  function formularioEdicion(d) {
    const opciones = d.all_sections.map((s) =>
      `<option value="${escapar(s.id)}" ${String(s.id) === String(d.section_id) ? 'selected' : ''}>${escapar(s.name)}</option>`).join('');

    contadorEnlaces = 0;
    const enlaces = d.urls.map((u) => bloqueEnlace(contadorEnlaces++, u)).join('');
    const src = d.image_url
      ? (d.image_url.startsWith('uploads/') ? `/uploads/${encodeURIComponent(d.image_url.slice(8))}` : d.image_url)
      : '';
    const previa = src ? `<img src="${escapar(src)}" alt="">` : '';
    const borrarImagen = d.image_url
      ? `<label style="font-size:.78rem;color:var(--suave)">
           <input type="checkbox" name="delete_current_image"> Eliminar la imagen actual</label>`
      : '';
    const padres = (d.posibles_padres || []).map((p) =>
      `<option value="${escapar(p.id)}" ${String(p.id) === String(d.parent_id) ? 'selected' : ''}>${escapar(p.title)}</option>`).join('');

    return `<form method="post" action="/edit_link_entry/${encodeURIComponent(d.id)}" enctype="multipart/form-data">
      <input type="hidden" name="_csrf" value="${escapar(window.CSRF)}">
      <div class="dialogo-cabecera">
        <h3>Editar «${escapar(d.title)}»</h3>
        <button type="button" class="boton-icono fechar" aria-label="Cerrar">&#10005;</button>
      </div>
      <div class="dialogo-cuerpo">
        <div class="fila">
          <div class="campo"><label>Título</label>
            <input type="text" name="link_title" value="${escapar(d.title || '')}" required></div>
          <div class="campo"><label>Sección</label>
            <select name="section_id" required>${opciones}</select></div>
        </div>
        <div class="campo"><label>Descripción</label>
          <textarea name="link_description" rows="2">${escapar(d.description || '')}</textarea></div>
        <div class="campo">
          <label>Dentro de <small>(opcional: déjala dentro de otra entrada)</small></label>
          <select name="parent_id">
            <option value="">— Nada, es un enlace principal —</option>${padres}
          </select>
        </div>
        <div class="campo">
          <label>Imagen propia <small>(si no pones ninguna, se busca una del servicio)</small></label>
          <div class="zona-imagen" id="zona-editar">
            <div class="vista-previa">${previa}</div>
            <span class="indicacion" ${previa ? 'hidden' : ''}>Arrastra, pega o haz clic para cambiar la imagen</span>
            <input type="file" name="custom_image_file" accept="image/*">
          </div>
          ${borrarImagen}
        </div>
        <div class="campo">
          <label>Enlaces</label>
          <div id="enlaces-editar">${enlaces}</div>
          <button type="button" class="boton" id="anadir-enlace-editar" style="justify-self:start">+ Añadir enlace</button>
        </div>
      </div>
      <div class="dialogo-pie">
        <button type="button" class="boton fechar">Cancelar</button>
        <button type="submit" class="boton boton--principal">Guardar cambios</button>
      </div>
    </form>`;
  }

  document.addEventListener('click', async (e) => {
    const boton = e.target.closest('.editar-entrada');
    if (!boton) return;
    e.preventDefault();
    try {
      const r = await fetch(`/get_entry_details/${boton.dataset.entrada}`, {
        headers: { 'X-CSRF-Token': window.CSRF },
      });
      const datos = await r.json();
      if (datos.error) { alert(datos.error); return; }
      $('#contenido-editar').innerHTML = formularioEdicion(datos);
      prepararZona($('#zona-editar'));
      abrir('dlg-editar-entrada');
    } catch (err) {
      console.error('No se pudieron cargar los detalles:', err);
    }
  });
})();
