/* servidor.js — buscador y plegado de /servidor (antes iba en línea). */
  (function () {
    const f = document.getElementById('f');
    const filas = Array.from(document.querySelectorAll('tbody tr'));
    const secciones = Array.from(document.querySelectorAll('.seccion'));
    const sin = document.getElementById('sin');
    const contador = document.getElementById('contador');
    const btnTodo = document.getElementById('plegar-todo');
    if (!f) return;

    function filtrar() {
      const q = f.value.trim().toLowerCase();
      let visibles = 0;
      filas.forEach((tr) => {
        const coincide = !q || (tr.dataset.buscar || '').includes(q);
        tr.hidden = !coincide;
        if (coincide) visibles++;
      });
      secciones.forEach((s) => {
        const hay = s.querySelectorAll('tbody tr:not([hidden])').length > 0;
        s.hidden = !hay;
        if (q && hay) s.dataset.plegada = '0';
      });
      if (contador) contador.textContent = q ? `${visibles} de ${filas.length}` : '';
      if (sin) sin.hidden = !(q && visibles === 0);
    }

    f.addEventListener('input', filtrar);

    document.querySelectorAll('.seccion-plegar').forEach((b) => {
      b.addEventListener('click', () => {
        const s = b.closest('.seccion');
        s.dataset.plegada = s.dataset.plegada === '1' ? '0' : '1';
      });
    });

    if (btnTodo) {
      const rotular = () => {
        const hay = secciones.some((s) => s.dataset.plegada !== '1');
        btnTodo.querySelector('span').textContent = hay ? 'Plegar todo' : 'Desplegar todo';
      };
      rotular();
      btnTodo.addEventListener('click', () => {
        const hay = secciones.some((s) => s.dataset.plegada !== '1');
        secciones.forEach((s) => { s.dataset.plegada = hay ? '1' : '0'; });
        rotular();
      });
    }

    document.addEventListener('keydown', (e) => {
      const escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
      if (e.key === '/' && !escribiendo) { e.preventDefault(); f.focus(); }
    });

    filtrar();
  })();
