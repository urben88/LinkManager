// Pantalla de entrada: mostrar/ocultar contraseña y evitar el doble envío.
// Va en un fichero aparte porque la CSP no permite JavaScript en línea.
(function () {
  const ver = document.querySelector('[data-ver-clave]');
  const clave = document.getElementById('clave');
  if (ver && clave) {
    ver.hidden = false;   // sin JS no se enseña un botón que no haría nada
    ver.addEventListener('click', () => {
      const mostrar = clave.type === 'password';
      clave.type = mostrar ? 'text' : 'password';
      ver.textContent = mostrar ? 'Ocultar' : 'Mostrar';
      ver.setAttribute('aria-pressed', String(mostrar));
      clave.focus();
    });
  }

  const form = document.querySelector('[data-formulario-entrar]');
  if (form) {
    form.addEventListener('submit', (e) => {
      const boton = form.querySelector('button[type=submit]');
      if (boton.getAttribute('aria-busy') === 'true') { e.preventDefault(); return; }
      boton.setAttribute('aria-busy', 'true');
      boton.textContent = boton.textContent.trim() === 'Verificar' ? 'Verificando…' : 'Entrando…';
      if (clave) clave.type = 'password';   // que no quede a la vista al volver atrás
    });
  }

  // El código de 2FA: solo cifras, y se envía solo al llegar a 6.
  const codigo = document.getElementById('codigo');
  if (codigo && form) {
    codigo.addEventListener('input', () => {
      const limpio = codigo.value.replace(/\D/g, '').slice(0, 6);
      if (codigo.value !== limpio) codigo.value = limpio;
      if (limpio.length === 6) form.requestSubmit();
    });
  }
})();
