/* arranque.js — se carga en <head>, antes que cualquier imagen.

   La política de seguridad (CSP) no deja ejecutar JavaScript escrito dentro
   del HTML: ni <script> en línea ni atributos onerror="…". Con una consola del
   servidor detrás del login, un fallo de escapado no puede convertirse en
   código ejecutándose. Por eso lo que antes hacían los onerror lo hace este
   oyente, que mira el atributo data-si-falla de la imagen. */
(function () {
  'use strict';
  document.addEventListener('error', function (ev) {
    var img = ev.target;
    if (!img || img.tagName !== 'IMG' || !img.dataset) return;
    var modo = img.dataset.siFalla;
    if (modo === 'quitar') {
      img.remove();
    } else if (modo === 'portada') {
      var portada = img.closest('.tarjeta-portada');
      if (portada) portada.remove();
    } else if (modo === 'monograma') {
      var caja = img.parentElement;
      if (caja) {
        caja.classList.add('monograma');
        caja.textContent = img.dataset.iniciales || '?';
      }
    }
  }, true);
})();
