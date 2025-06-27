document.addEventListener('DOMContentLoaded', function() {
    
    // --- LÓGICA MODO EDICIÓN ---
    const editModeCheckbox = document.getElementById('edit-mode-checkbox');
    let sortableSections, sortableGrids = [];

    function toggleEditMode(isEditMode) {
        document.body.classList.toggle('edit-mode', isEditMode);
        // Habilitar/deshabilitar drag & drop
        if (sortableSections) {
            sortableSections.option("disabled", !isEditMode);
        }
        sortableGrids.forEach(s => s.option("disabled", !isEditMode));
    }

    if (editModeCheckbox) {
        editModeCheckbox.addEventListener('change', (e) => toggleEditMode(e.target.checked));
        // Iniciar siempre en modo no-edición
        editModeCheckbox.checked = false;
        toggleEditMode(false);
    }

    // --- LÓGICA DRAG & DROP ---
    function initDragAndDrop() {
        const sectionsContainer = document.getElementById('sections-container');
        if (sectionsContainer) {
            sortableSections = new Sortable(sectionsContainer, {
                animation: 150,
                handle: '.handle-icon',
                ghostClass: 'sortable-ghost',
                disabled: true, // Iniciar deshabilitado
                onEnd: function (evt) {
                    const order = Array.from(evt.to.children).map(el => el.dataset.id).filter(id => id);
                    sendOrderUpdate('sections', order);
                },
            });
        }

        document.querySelectorAll('.link-entries-grid').forEach(grid => {
            const s = new Sortable(grid, {
                group: 'shared', // Permite mover tarjetas entre secciones
                animation: 150,
                ghostClass: 'sortable-ghost',
                disabled: true, // Iniciar deshabilitado
                onEnd: function (evt) {
                    const entryId = evt.item.dataset.id;
                    const toSectionId = evt.to.dataset.sectionId;
                    const toOrder = Array.from(evt.to.children).map(el => el.dataset.id);
                    sendOrderUpdate('entries', toOrder, toSectionId, entryId);

                    // Si se movió a una sección diferente, actualizar el orden de la sección de origen también
                    if (evt.from !== evt.to) {
                        const fromOrder = Array.from(evt.from.children).map(el => el.dataset.id);
                        sendOrderUpdate('entries', fromOrder, evt.from.dataset.sectionId);
                    }
                },
            });
            sortableGrids.push(s);
        });
    }

    function sendOrderUpdate(type, order, sectionId = null, entryId = null) {
        const payload = { type, order };
        if (sectionId) payload.section_id = sectionId;
        if (entryId) payload.entry_id = entryId; // Para actualizar el section_id de la entrada

        fetch('/update_order', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status !== 'success') console.error('Error al reordenar:', data.message);
        })
        .catch(error => console.error('Error de red al reordenar:', error));
    }

    // --- LÓGICA PREVISUALIZACIÓN DE IMAGEN ---
    function setupImageDropZone(formPrefix) {
        const dropZone = document.getElementById(`${formPrefix}-image-drop-zone`);
        if (!dropZone) return;
        
        const fileInput = dropZone.querySelector('.image-file-input');
        const previewContainer = dropZone.querySelector(`#${formPrefix}-image-preview-container`);
        const prompt = previewContainer.querySelector('.drop-zone-prompt');

        const handleFile = (file) => {
            if (file && file.type.startsWith('image/')) {
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(file);
                fileInput.files = dataTransfer.files;

                const reader = new FileReader();
                reader.onload = () => {
                    if (prompt) prompt.style.display = 'none';
                    let img = previewContainer.querySelector('img');
                    if (!img) {
                        img = document.createElement('img');
                        previewContainer.appendChild(img);
                    }
                    img.src = reader.result;
                };
                reader.readAsDataURL(file);
            }
        };

        dropZone.addEventListener('click', (e) => { if(e.target.tagName !== 'INPUT') fileInput.click(); });
        fileInput.addEventListener('change', () => handleFile(fileInput.files[0]));
        
        document.addEventListener('paste', e => {
            const activeModal = document.querySelector('.modal.show');
            if (activeModal && activeModal.contains(dropZone)) {
                 const file = e.clipboardData.files[0];
                 if (file && file.type.startsWith('image/')) {
                    handleFile(file);
                 }
            }
        });

        dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.style.borderColor = 'var(--primary-blue)'; });
        dropZone.addEventListener('dragleave', () => { dropZone.style.borderColor = 'var(--border-color)'; });
        dropZone.addEventListener('drop', e => { e.preventDefault(); dropZone.style.borderColor = 'var(--border-color)'; handleFile(e.dataTransfer.files[0]); });
    }

    // --- LÓGICA SELECTOR DE ENTORNO ---
    const environmentSelector = document.getElementById('environment-selector');
    function updateLinkHrefs(environment) {
        if (!environment || !APP_DOMAINS) return;
        const baseUrl = APP_DOMAINS[environment];

        document.querySelectorAll('.dynamic-link').forEach(link => {
            const linkType = link.dataset.linkType;
            if (linkType === 'internal_app') {
                const port = link.dataset.port;
                try {
                    const urlObject = new URL(baseUrl);
                    const finalUrl = `${urlObject.protocol}//${urlObject.hostname}:${port}`;
                    link.href = finalUrl;
                    link.textContent = finalUrl;
                } catch (e) {
                    link.textContent = "URL base inválida";
                }
            }
        });
    }

    if (environmentSelector) {
        environmentSelector.addEventListener('change', (e) => updateLinkHrefs(e.target.value));
        updateLinkHrefs(environmentSelector.value);
    }
    
    // --- LÓGICA COMPARTIDA DE FORMULARIO DE ENLACES ---
    function getUrlFieldHtml(index, url = null, formPrefix = 'add') {
        const isInternal = url ? url.link_type === 'internal_app' : true;
        const value = url ? url.value : '';
        const label = url ? url.label : '';
        const id = url ? url.id : 'new';
        
        let valueFieldHtml;
        if (isInternal) {
            valueFieldHtml = `<label>Puerto</label><input type="number" name="urls[${index}][value]" class="form-control" placeholder="8096" value="${value}" required>`;
        } else {
            valueFieldHtml = `<label>URL Completa</label><input type="url" name="urls[${index}][value]" class="form-control" placeholder="https://github.com" value="${value}" required>`;
        }

        return `
            <div class="url-field-group mb-3 p-3" id="${formPrefix}-link-field-${index}" style="background-color: #202124; border-radius: 8px;">
                <input type="hidden" name="urls[${index}][id]" value="${id}">
                <div class="form-group">
                    <div class="form-check form-check-inline">
                        <input class="form-check-input link-type-radio" type="radio" name="urls[${index}][type]" id="${formPrefix}-type-internal-${index}" value="internal_app" ${isInternal ? 'checked' : ''}>
                        <label class="form-check-label" for="${formPrefix}-type-internal-${index}">App Interna (por puerto)</label>
                    </div>
                    <div class="form-check form-check-inline">
                        <input class="form-check-input link-type-radio" type="radio" name="urls[${index}][type]" id="${formPrefix}-type-external-${index}" value="external_url" ${!isInternal ? 'checked' : ''}>
                        <label class="form-check-label" for="${formPrefix}-type-external-${index}">URL Externa</label>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group col-md-6">
                        <label>Etiqueta</label>
                        <input type="text" name="urls[${index}][label]" class="form-control" placeholder="Ej: Jellyfin" value="${label}" required>
                    </div>
                    <div class="form-group col-md-6 value-field-container">
                        ${valueFieldHtml}
                    </div>
                </div>
                <button type="button" class="btn btn-sm btn-danger remove-url-field">Eliminar</button>
            </div>`;
    }

    function updateValueField(radio) {
        const group = radio.closest('.url-field-group');
        const container = group.querySelector('.value-field-container');
        const indexMatch = group.id.match(/(\d+)$/);
        if (!indexMatch) return;
        const index = indexMatch[0];
        const linkType = radio.value;
        if (linkType === 'internal_app') {
            container.innerHTML = `<label>Puerto</label><input type="number" name="urls[${index}][value]" class="form-control" placeholder="8096" required>`;
        } else {
            container.innerHTML = `<label>URL Completa</label><input type="url" name="urls[${index}][value]" class="form-control" placeholder="https://github.com" required>`;
        }
    }
    
    // Asigna el evento de actualización de campo de valor a un contenedor padre estático
    document.body.addEventListener('change', e => {
        if (e.target.classList.contains('link-type-radio')) {
            updateValueField(e.target);
        }
    });

    document.body.addEventListener('click', e => {
        if (e.target.classList.contains('remove-url-field')) {
            e.target.closest('.url-field-group').remove();
        }
    });

    // --- LÓGICA MODAL AÑADIR ENTRADA ---
    let addUrlCounter = 0;
    const addModal = document.getElementById('addLinkEntryModal');
    if (addModal) {
        const container = addModal.querySelector('#urls-container-add');
        const addButton = addModal.querySelector('#add-new-link-field');
        $(addModal).on('show.bs.modal', function () {
            container.innerHTML = '';
            addUrlCounter = 0;
            container.insertAdjacentHTML('beforeend', getUrlFieldHtml(addUrlCounter++, null, 'add'));
        });
        addButton.addEventListener('click', () => {
            container.insertAdjacentHTML('beforeend', getUrlFieldHtml(addUrlCounter++, null, 'add'));
        });
    }

    // --- INICIO DE LA NUEVA LÓGICA PARA EDITAR ---
    let editUrlCounter = 0;

    function buildEditModalContent(data) {
        const sectionsOptions = data.all_sections.map(s => 
            `<option value="${s.id}" ${s.id === data.section_id ? 'selected' : ''}>${s.name}</option>`
        ).join('');

        let urlsHtml = '';
        editUrlCounter = 0;
        data.urls.forEach(url => {
            urlsHtml += getUrlFieldHtml(editUrlCounter++, url, 'edit');
        });

        const imagePreview = data.image_url 
            ? `<img src="${data.image_url.startsWith('uploads/') ? `/${data.image_url}` : data.image_url}" alt="Vista previa" onerror="this.style.display='none'; this.nextElementSibling.style.display='block';">
               <span class="drop-zone-prompt" style="display: none;">Arrastra, pega o haz clic</span>`
            : `<span class="drop-zone-prompt">Arrastra, pega (Ctrl+V) o haz clic</span>`;
        
        const deleteImageCheckbox = data.image_url
            ? `<div class="form-group form-check">
                   <input type="checkbox" class="form-check-input" name="delete_current_image" id="delete_current_image">
                   <label class="form-check-label" for="delete_current_image">Eliminar imagen actual</label>
               </div>`
            : '';

        return `
            <form id="editLinkForm" action="/edit_link_entry/${data.id}" method="post" enctype="multipart/form-data">
                <div class="modal-header">
                    <h5 class="modal-title">Editar Entrada: ${data.title}</h5>
                    <button type="button" class="close" data-dismiss="modal">×</button>
                </div>
                <div class="modal-body">
                    <div class="form-group"><label>Título</label><input type="text" class="form-control" name="link_title" value="${data.title || ''}"></div>
                    <div class="form-group"><label>Descripción</label><textarea class="form-control" name="link_description" rows="2">${data.description || ''}</textarea></div>
                    <div class="form-row">
                        <div class="form-group col-md-6"><label>Sección</label><select class="form-control" name="section_id" required>${sectionsOptions}</select></div>
                        <div class="form-group col-md-6">
                            <label>Imagen Personalizada</label>
                            <div class="image-drop-zone" id="edit-image-drop-zone">
                                <div id="edit-image-preview-container" class="image-preview-container">${imagePreview}</div>
                                <input type="file" class="form-control-file image-file-input" name="custom_image_file" accept="image/*">
                            </div>
                            ${deleteImageCheckbox}
                        </div>
                    </div>
                    <hr><h6>Enlaces</h6>
                    <div id="urls-container-edit">${urlsHtml}</div>
                    <button type="button" id="edit-add-new-link-field" class="btn btn-secondary mt-2"><i class="fas fa-plus"></i> Añadir Enlace</button>
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancelar</button>
                    <button type="submit" class="btn btn-primary">Guardar Cambios</button>
                </div>
            </form>`;
    }

    document.body.addEventListener('click', function(e) {
        const editButton = e.target.closest('.edit-entry-btn');
        if (editButton) {
            const entryId = editButton.dataset.entryId;
            fetch(`/get_entry_details/${entryId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.error) {
                        alert(data.error);
                        return;
                    }
                    const modalContentContainer = document.querySelector('#editLinkEntryModal .modal-content');
                    modalContentContainer.innerHTML = buildEditModalContent(data);
                    
                    // Inicializar la zona de drop para la nueva imagen
                    setupImageDropZone('edit');
                    
                    // Añadir evento al nuevo botón "Añadir Enlace"
                    document.getElementById('edit-add-new-link-field').addEventListener('click', () => {
                         document.getElementById('urls-container-edit').insertAdjacentHTML('beforeend', getUrlFieldHtml(editUrlCounter++, null, 'edit'));
                    });

                    // Mostrar el modal
                    $('#editLinkEntryModal').modal('show');
                })
                .catch(error => console.error('Error al obtener detalles de la entrada:', error));
        }
    });
    // --- FIN DE LA NUEVA LÓGICA ---

    // Inicializar todas las funcionalidades
    initDragAndDrop();
    setupImageDropZone('add');
});