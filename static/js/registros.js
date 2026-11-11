/* registros.js — visor de logs: copiar al portapapeles, confirmar borrados
   y mostrar las fechas en la hora local del navegador. */
(() => {
  'use strict';

  async function copiar(texto) {
    try {
      await navigator.clipboard.writeText(texto);
      return true;
    } catch (e) {
      // Fallback para navegadores sin Clipboard API o fuera de HTTPS.
      const area = document.createElement('textarea');
      area.value = texto;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (err) { /* nada */ }
      area.remove();
      return ok;
    }
  }

  document.addEventListener('click', async (e) => {
    const boton = e.target.closest('[data-copiar]');
    if (boton) {
      const destino = document.getElementById(boton.dataset.copiar);
      if (!destino) return;
      const texto = 'value' in destino ? destino.value : destino.textContent;
      const original = boton.textContent;
      const ok = await copiar(texto);
      boton.textContent = ok ? 'Copiado' : 'No se pudo copiar';
      setTimeout(() => { boton.textContent = original; }, 1400);
      return;
    }

    const cerrarAviso = e.target.closest('.aviso button');
    if (cerrarAviso) cerrarAviso.closest('.aviso').remove();
  });

  document.addEventListener('submit', (e) => {
    const formulario = e.target.closest('form[data-confirmar]');
    if (formulario && !window.confirm(formulario.dataset.confirmar)) {
      e.preventDefault();
    }
  });

  // El servidor guarda en UTC; aquí se enseña la hora local de quien mira.
  document.querySelectorAll('time[data-ts]').forEach((el) => {
    const fecha = new Date(Number(el.dataset.ts) * 1000);
    if (!Number.isNaN(fecha.getTime())) {
      el.textContent = fecha.toLocaleString('es-ES', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      });
    }
  });
})();
