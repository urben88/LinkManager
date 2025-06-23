document.addEventListener('DOMContentLoaded', function() {
    // --- Selectores Globales ---
    const modals = {
        addSectionModal: document.getElementById('addSectionModal'),
        editSectionModal: document.getElementById('editSectionModal'),
        addLinkModal: document.getElementById('addLinkModal'),
        editLinkEntryModal: document.getElementById('editLinkEntryModal')
    };

    const addLinkForm = document.getElementById('addLinkForm');
    const editSectionForm = document.getElementById('editSectionForm');
    const editLinkForm = document.getElementById('editLinkForm');

    // --- Contadores y Almacenamiento de Archivos ---
    let addUrlFieldIndex = 0; // Se inicializará a 1 si el primer campo está presente
    let editUrlFieldIndex = 0;
    let addPastedImageFile = null;
    let editPastedImageFile = null;

    // --- Selectores Formulario "Añadir Entrada" ---
    const addImagePreviewContainer = document.getElementById('imagePreviewContainer');
    const addPastedImagePreview = document.getElementById('pastedImagePreview');
    const addPasteHelperText = document.getElementById('pasteHelperText');
    const addClearPastedImageBtn = document.getElementById('clearPastedImageBtn');
    const addUrlMetadataPreviewDiv = document.getElementById('urlMetadataPreview');
    const addUrlMetadataImagePreview = document.getElementById('urlMetadataImagePreview');
    const addUrlMetadataTitlePreview = document.getElementById('urlMetadataTitlePreview');
    const addUrlMetadataDescriptionPreview = document.getElementById('urlMetadataDescriptionPreview');
    const addUrlFieldsContainerModal = document.getElementById('urlFieldsContainerModal');

    // --- Selectores Formulario "Editar Entrada" ---
    const editImagePreviewContainer = document.getElementById('editImagePreviewContainer');
    const editPastedImagePreview = document.getElementById('editPastedImagePreview');
    const editPasteHelperText = document.getElementById('editPasteHelperText');
    const editClearPastedImageBtn = document.getElementById('editClearPastedImageBtn');
    const editDeleteCurrentImageCheckbox = document.getElementById('delete_current_image_checkbox');
    const editUrlFieldsContainerModal = document.getElementById('editUrlFieldsContainerModal');


    // --- MANEJO GENERAL DE MODALES ---
    function openModal(modalId) {
        if (modals[modalId]) modals[modalId].style.display = 'block';
    }
    function closeModal(modalId) {
        if (modals[modalId]) modals[modalId].style.display = 'none';
    }

    document.querySelectorAll('.close-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const modalId = btn.dataset.modalId;
            closeModal(modalId);
            if (modalId === 'addLinkModal') resetAddLinkForm();
            if (modalId === 'editLinkEntryModal') resetEditLinkForm();
            if (modalId === 'editSectionModal') editSectionForm?.reset();
        });
    });

    window.addEventListener('click', (event) => {
        if (event.target.classList.contains('modal')) {
            const modalId = event.target.id;
            closeModal(modalId);
            if (modalId === 'addLinkModal') resetAddLinkForm();
            if (modalId === 'editLinkEntryModal') resetEditLinkForm();
            if (modalId === 'editSectionModal') editSectionForm?.reset();
        }
    });

    // --- AÑADIR/EDITAR SECCIÓN ---
    document.getElementById('openAddSectionModalBtn')?.addEventListener('click', () => {
        modals.addSectionModal.querySelector('form')?.reset(); // Resetear antes de abrir
        openModal('addSectionModal');
    });

    document.querySelectorAll('.edit-section-btn').forEach(button => {
        button.addEventListener('click', function() {
            const sectionId = this.dataset.sectionId;
            const sectionName = this.dataset.sectionName;
            
            const idField = document.getElementById('edit_section_id_field');
            const nameField = document.getElementById('edit_section_name_field');
            
            if (idField) idField.value = sectionId;
            if (nameField) nameField.value = sectionName;
            if (editSectionForm) editSectionForm.action = `/edit_section/${sectionId}`;
            
            openModal('editSectionModal');
        });
    });
    // Nota: El envío de editSectionForm se maneja por el action/method del HTML directamente.

    // --- FUNCIONES COMUNES PARA CAMPOS DE URL DINÁMICOS ---
    function addDynamicUrlField(container, templateId, namePrefix, currentIndex, data = {}, isEditMode = false) {
        const template = document.getElementById(templateId);
        if (!template || !container) return currentIndex;

        const clone = template.content.cloneNode(true);
        const urlGroup = clone.querySelector('.url-field-group');
        
        // Actualizar nombres y IDs de los campos
        clone.querySelectorAll('[name*="[INDEX]"]').forEach(el => {
            el.name = el.name.replace('[INDEX]', `[${currentIndex}]`);
        });
        clone.querySelectorAll('[class*="-number"]').forEach(el => {
            el.textContent = currentIndex + 1;
        });
        // Configurar IDs únicos para labels y inputs
        const urlInput = clone.querySelector('.url-input-field, .edit-url-input-field');
        const labelInput = clone.querySelector('.label-input-field, .edit-label-input-field');
        const urlIdInput = clone.querySelector('.url-id-field, .edit-url-id-field');

        if (urlInput) urlInput.id = `${namePrefix}_${currentIndex}_url`;
        if (labelInput) labelInput.id = `${namePrefix}_${currentIndex}_label`;
        
        // Ponerles 'for' a los labels
        const urlLabelFor = clone.querySelector(`label[for$="_url"]`);
        if(urlLabelFor && urlInput) urlLabelFor.htmlFor = urlInput.id;
        const textLabelFor = clone.querySelector(`label[for$="_label"]`);
        if(textLabelFor && labelInput) textLabelFor.htmlFor = labelInput.id;


        // Rellenar datos si se proporcionan (para edición o al añadir un campo pre-rellenado)
        if (urlIdInput && data.id) urlIdInput.value = data.id;
        if (urlInput) urlInput.value = data.url || '';
        if (labelInput) labelInput.value = data.label || '';
        
        // Adjuntar listener de preview solo al primer campo del formulario "Añadir"
        if (!isEditMode && namePrefix === 'urls' && currentIndex === 0 && urlInput) {
            urlInput.removeEventListener('input', handleAddUrlMetadataPreviewInput); // Evitar duplicados
            urlInput.addEventListener('input', handleAddUrlMetadataPreviewInput);
        }
        
        container.appendChild(clone);
        return currentIndex + 1; // Devolver el siguiente índice a usar
    }

    function setupDynamicUrlFieldRemoval(containerSelector) {
        const container = document.querySelector(containerSelector);
        if (container) {
            container.addEventListener('click', function(event) {
                const removeButton = event.target.closest('.removeUrlFieldBtn, .removeEditUrlFieldBtn');
                if (removeButton) {
                    removeButton.closest('.url-field-group').remove();
                    // Si se elimina el primer campo del formulario de "Añadir", re-adjuntar listener
                    if (container === addUrlFieldsContainerModal) {
                        attachAddUrlMetadataPreviewListener();
                    }
                }
            });
        }
    }
    setupDynamicUrlFieldRemoval('#urlFieldsContainerModal');
    setupDynamicUrlFieldRemoval('#editUrlFieldsContainerModal');


    // --- AÑADIR ENTRADA DE ENLACE ---
    document.getElementById('openAddLinkModalBtn')?.addEventListener('click', () => {
        resetAddLinkForm();
        openModal('addLinkModal');
    });

    document.getElementById('addUrlFieldBtnModal')?.addEventListener('click', function() {
        addUrlFieldIndex = addDynamicUrlField(addUrlFieldsContainerModal, 'urlFieldTemplate', 'urls', addUrlFieldIndex, {}, false);
    });

    addImagePreviewContainer?.addEventListener('paste', (event) => handleImagePaste(event, addPastedImagePreview, addPasteHelperText, addClearPastedImageBtn, (file) => { addPastedImageFile = file; hideAddUrlMetadataPreview(); }));
    addClearPastedImageBtn?.addEventListener('click', () => {
        addPastedImageFile = null;
        clearImagePreview(addPastedImagePreview, addPasteHelperText, addClearPastedImageBtn);
        triggerAddUrlMetadataPreview();
    });

    addLinkForm?.addEventListener('submit', function(event) {
        event.preventDefault();
        const formData = new FormData(addLinkForm);
        if (addPastedImageFile) {
            formData.append('custom_image_file', addPastedImageFile, addPastedImageFile.name || `pasted_image.${addPastedImageFile.type.split('/')[1] || 'png'}`);
        }
        submitFormData(addLinkForm.action, formData);
    });
    
    // --- EDITAR ENTRADA DE ENLACE ---
    document.querySelectorAll('.edit-entry-btn').forEach(button => {
        button.addEventListener('click', async function() {
            const entryId = this.dataset.entryId;
            resetEditLinkForm(); // Limpiar antes de poblar
            try {
                const response = await fetch(`/get_entry_details/${entryId}`);
                if (!response.ok) throw new Error(`Error al obtener detalles: ${response.statusText}`);
                const entryData = await response.json();
                if (entryData.error) throw new Error(entryData.error);
                
                populateEditLinkForm(entryData, entryId);
                openModal('editLinkEntryModal');
            } catch (error) {
                console.error("Error al cargar datos para editar:", error);
                alert("No se pudieron cargar los datos de la entrada para editar.");
            }
        });
    });

    function populateEditLinkForm(entryData, entryId) {
        const idField = document.getElementById('edit_entry_id_field');
        const titleField = document.getElementById('editLinkTitleInputModal');
        const descriptionField = document.getElementById('editLinkDescriptionInputModal');
        const sectionSelect = document.getElementById('editSectionSelectModal');

        if (idField) idField.value = entryId;
        if (titleField) titleField.value = entryData.title || '';
        if (descriptionField) descriptionField.value = entryData.description || '';
        if (sectionSelect) sectionSelect.value = entryData.section_id;
        if (editLinkForm) editLinkForm.action = `/edit_link_entry/${entryId}`;

        if (editUrlFieldsContainerModal) editUrlFieldsContainerModal.innerHTML = ''; // Limpiar URLs previas
        editUrlFieldIndex = 0; // Resetear índice para este formulario
        entryData.urls?.forEach(urlItem => {
            editUrlFieldIndex = addDynamicUrlField(editUrlFieldsContainerModal, 'editUrlFieldTemplate', 'edit_urls', editUrlFieldIndex, urlItem, true);
        });
        
        // Manejar imagen actual
        if (editPastedImagePreview) {
            editPastedImagePreview.dataset.originalUrl = ''; // Limpiar por si acaso
            if (entryData.image_url) {
                const imgSrc = entryData.image_url.startsWith('http') ? entryData.image_url : `/static/${entryData.image_url}`;
                editPastedImagePreview.src = imgSrc;
                editPastedImagePreview.style.display = 'block';
                editPastedImagePreview.dataset.originalUrl = imgSrc; // Guardar para restaurar
                if (editPasteHelperText) editPasteHelperText.style.display = 'none';
            } else {
                editPastedImagePreview.style.display = 'none';
                if (editPasteHelperText) editPasteHelperText.style.display = 'block';
            }
        }
        if (editDeleteCurrentImageCheckbox) editDeleteCurrentImageCheckbox.checked = false;
        if (editClearPastedImageBtn) editClearPastedImageBtn.style.display = 'none';
        editPastedImageFile = null;
    }

    document.getElementById('addEditUrlFieldBtnModal')?.addEventListener('click', function() {
        editUrlFieldIndex = addDynamicUrlField(editUrlFieldsContainerModal, 'editUrlFieldTemplate', 'edit_urls', editUrlFieldIndex, {}, true);
    });
    
    editImagePreviewContainer?.addEventListener('paste', (event) => handleImagePaste(event, editPastedImagePreview, editPasteHelperText, editClearPastedImageBtn, (file) => { editPastedImageFile = file; if (editDeleteCurrentImageCheckbox) editDeleteCurrentImageCheckbox.checked = false; }));
    editClearPastedImageBtn?.addEventListener('click', () => {
        editPastedImageFile = null;
        clearImagePreview(editPastedImagePreview, editPasteHelperText, editClearPastedImageBtn);
        // Al limpiar, si había imagen original y no está marcado para borrar, mostrarla
        const originalImageUrl = editPastedImagePreview?.dataset.originalUrl;
        if (originalImageUrl && !editDeleteCurrentImageCheckbox?.checked) {
            editPastedImagePreview.src = originalImageUrl;
            editPastedImagePreview.style.display = 'block';
            if (editPasteHelperText) editPasteHelperText.style.display = 'none';
        }
    });
     if (editDeleteCurrentImageCheckbox) {
        editDeleteCurrentImageCheckbox.addEventListener('change', function() {
            if (this.checked && !editPastedImageFile) {
                if (editPastedImagePreview) editPastedImagePreview.style.display = 'none';
                if (editPasteHelperText) editPasteHelperText.style.display = 'block';
            } else if (!this.checked && !editPastedImageFile) {
                 const originalImageUrl = editPastedImagePreview?.dataset.originalUrl;
                 if (originalImageUrl) {
                    editPastedImagePreview.src = originalImageUrl;
                    editPastedImagePreview.style.display = 'block';
                    if(editPasteHelperText) editPasteHelperText.style.display = 'none';
                 }
            }
        });
    }

    editLinkForm?.addEventListener('submit', function(event) {
        event.preventDefault();
        const formData = new FormData(editLinkForm);
        if (editPastedImageFile) {
            formData.append('edit_custom_image_file', editPastedImageFile, editPastedImageFile.name || `pasted_edit.${editPastedImageFile.type.split('/')[1] || 'png'}`);
        }
        submitFormData(editLinkForm.action, formData);
    });

    // --- FUNCIONES AUXILIARES GENÉRICAS ---
    function handleImagePaste(event, imgPreviewEl, helperTextEl, clearBtnEl, fileSetterCallback, postPasteCallback = () => {}) {
        const items = (event.clipboardData || event.originalEvent.clipboardData)?.items;
        if (!items) return;
        for (let i = 0; i < items.length; i++) {
            if (items[i].type.indexOf('image') !== -1) {
                event.preventDefault();
                const blob = items[i].getAsFile();
                if (blob) {
                    fileSetterCallback(blob); // Guardar el archivo/blob
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        if (imgPreviewEl) { imgPreviewEl.src = e.target.result; imgPreviewEl.style.display = 'block'; }
                        if (helperTextEl) helperTextEl.style.display = 'none';
                        if (clearBtnEl) clearBtnEl.style.display = 'inline-block';
                        postPasteCallback(); // Callback adicional si es necesario
                    };
                    reader.readAsDataURL(blob);
                }
                break;
            }
        }
    }

    function clearImagePreview(imgPreviewEl, helperTextEl, clearBtnEl) {
        if (imgPreviewEl) { imgPreviewEl.src = '#'; imgPreviewEl.style.display = 'none'; }
        if (helperTextEl) helperTextEl.style.display = 'block';
        if (clearBtnEl) clearBtnEl.style.display = 'none';
    }

    function submitFormData(url, formData) {
        fetch(url, { method: 'POST', body: formData })
            .then(response => {
                if (response.ok) {
                    if (response.redirected) window.location.href = response.url;
                    else window.location.reload();
                } else {
                    response.text().then(text => {
                        alert("Error: " + (text.length > 200 ? text.substring(0,200) + "..." : text));
                        console.error("Error del servidor:", text);
                    });
                }
            })
            .catch(error => { console.error('Error de red:', error); alert("Error de red."); });
    }

    // --- PREVISUALIZACIÓN DE METADATOS (SOLO PARA "AÑADIR ENTRADA") ---
    let addUrlDebounceTimer;
    function hideAddUrlMetadataPreview() { if (addUrlMetadataPreviewDiv) addUrlMetadataPreviewDiv.style.display = 'none'; }
    
    function attachAddUrlMetadataPreviewListener() {
        const firstUrlInput = addUrlFieldsContainerModal?.querySelector('input[name="urls[0][url]"]');
        if (firstUrlInput) {
            firstUrlInput.removeEventListener('input', handleAddUrlMetadataPreviewInput);
            firstUrlInput.addEventListener('input', handleAddUrlMetadataPreviewInput);
        } else {
            hideAddUrlMetadataPreview();
        }
    }

    function handleAddUrlMetadataPreviewInput(event) {
        if (addPastedImageFile) { hideAddUrlMetadataPreview(); return; }
        clearTimeout(addUrlDebounceTimer);
        const url = event.target.value.trim();
        if (!isValidHttpUrl(url)) { hideAddUrlMetadataPreview(); return; }

        if (addUrlMetadataPreviewDiv) addUrlMetadataPreviewDiv.style.display = 'flex';
        if (addUrlMetadataTitlePreview) addUrlMetadataTitlePreview.textContent = 'Cargando...';
        if (addUrlMetadataDescriptionPreview) addUrlMetadataDescriptionPreview.textContent = '';
        if (addUrlMetadataImagePreview) { addUrlMetadataImagePreview.src = '#'; addUrlMetadataImagePreview.style.display = 'none'; }

        addUrlDebounceTimer = setTimeout(() => {
            fetch(`/get_link_preview?url=${encodeURIComponent(url)}`)
                .then(response => response.json())
                .then(data => {
                    if (addPastedImageFile) { hideAddUrlMetadataPreview(); return; }
                    if (data.error) {
                        if (addUrlMetadataTitlePreview) addUrlMetadataTitlePreview.textContent = 'No se pudo obtener.';
                    } else {
                        if (addUrlMetadataTitlePreview) addUrlMetadataTitlePreview.textContent = data.title || url;
                        if (addUrlMetadataDescriptionPreview) addUrlMetadataDescriptionPreview.textContent = data.description ? data.description.substring(0,100) + '...' : '';
                        if (addUrlMetadataImagePreview && data.image_url) {
                            addUrlMetadataImagePreview.src = data.image_url;
                            addUrlMetadataImagePreview.style.display = 'block';
                        } else if (addUrlMetadataImagePreview) {
                            addUrlMetadataImagePreview.style.display = 'none';
                        }
                    }
                })
                .catch(error => { console.error('Error preview URL:', error); if (addUrlMetadataTitlePreview) addUrlMetadataTitlePreview.textContent = 'Error.'; });
        }, 750);
    }

    function triggerAddUrlMetadataPreview() {
        if (addPastedImageFile) { hideAddUrlMetadataPreview(); return; }
        const firstUrlInput = addUrlFieldsContainerModal?.querySelector('input[name="urls[0][url]"]');
        if (firstUrlInput && firstUrlInput.value.trim() !== '') {
            firstUrlInput.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
        } else {
            hideAddUrlMetadataPreview();
        }
    }

    // --- RESETEAR FORMULARIOS ---
    function resetAddLinkForm() {
        addLinkForm?.reset();
        if (addUrlFieldsContainerModal) { // Limpiar campos dinámicos
            const dynamicGroups = addUrlFieldsContainerModal.querySelectorAll('.url-field-group');
            dynamicGroups.forEach((group, index) => { if (index > 0) group.remove(); });
            const firstGroup = addUrlFieldsContainerModal.querySelector('.url-field-group');
            if (firstGroup) { // Resetear el primer campo que queda
                firstGroup.querySelector('input[name="urls[0][url]"]').value = '';
                firstGroup.querySelector('input[name="urls[0][label]"]').value = '';
            }
        }
        addUrlFieldIndex = 1; // Para el siguiente campo a añadir (después del 0)
        addPastedImageFile = null;
        clearImagePreview(addPastedImagePreview, addPasteHelperText, addClearPastedImageBtn);
        hideAddUrlMetadataPreview();
        if (addUrlMetadataTitlePreview) addUrlMetadataTitlePreview.textContent = 'Título...';
        if (addUrlMetadataDescriptionPreview) addUrlMetadataDescriptionPreview.textContent = 'Descripción...';
        attachAddUrlMetadataPreviewListener();
    }

    function resetEditLinkForm() {
        editLinkForm?.reset();
        if (editUrlFieldsContainerModal) editUrlFieldsContainerModal.innerHTML = '';
        editUrlFieldIndex = 0;
        editPastedImageFile = null;
        clearImagePreview(editPastedImagePreview, editPasteHelperText, editClearPastedImageBtn);
        if (editDeleteCurrentImageCheckbox) editDeleteCurrentImageCheckbox.checked = false;
        if (editPastedImagePreview) editPastedImagePreview.dataset.originalUrl = ''; // Limpiar URL original guardada
    }

    function isValidHttpUrl(string) {
        if (!string) return false;
        let url;
        try {
            const urlToTest = string.startsWith('http://') || string.startsWith('https://') ? string : 'http://' + string;
            url = new URL(urlToTest);
        } catch (_) { return false; }
        return url.hostname && url.hostname.includes('.');
    }

    // --- INICIALIZACIÓN ---
    attachAddUrlMetadataPreviewListener(); // Para el primer campo de URL en "Añadir Entrada"
    // Asegurar que al menos un campo de URL esté presente al cargar para "Añadir Entrada"
    if (addUrlFieldsContainerModal && addUrlFieldsContainerModal.children.length === 0) {
        addUrlFieldIndex = addDynamicUrlField(addUrlFieldsContainerModal, 'urlFieldTemplate', 'urls', 0, {}, false);
    } else if (addUrlFieldsContainerModal && addUrlFieldsContainerModal.children.length > 0) {
        // Si ya hay un campo (desde el HTML), el índice para el siguiente dinámico es 1
        addUrlFieldIndex = 1;
    }


});