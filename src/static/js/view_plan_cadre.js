// --- Fonctions pour le Toast UI Editor ---
// Vérifie si un élément est visible (utile pour les zones dans des accordéons masqués)
function isVisible(el) {
    return !!( el.offsetWidth || el.offsetHeight || el.getClientRects().length );
}

function initToastEditor(textarea) {
    const container = document.createElement('div');
    textarea.parentNode.insertBefore(container, textarea);
    textarea.style.display = 'none';

    const editor = new toastui.Editor({
        el: container,
        initialEditType: 'wysiwyg',
        initialValue: textarea.value || '',
        toolbarItems: [
            ['bold', 'italic'],
            ['ul', 'indent', 'outdent']
        ],
        usageStatistics: false,
        hideModeSwitch: true,
        autofocus: false,
        height: 'auto',
        minHeight: '100px',
        toolbarVisibleWithoutEditor: false,
        customKeyMap: {
            Tab: (editor, ev) => {
                ev.preventDefault();
                editor.exec('indent');
            },
            'Shift-Tab': (editor, ev) => {
                ev.preventDefault();
                editor.exec('outdent');
            }
        }
    });

    editor.on('change', () => {
        textarea.value = editor.getMarkdown();
    });

    textarea.classList.add('toast-initialized');
    
    const editorEl = container.querySelector('.toastui-editor');
    if (editorEl) {
        const observer = new ResizeObserver(() => {
            editor.setHeight('auto');
        });
        observer.observe(editorEl);
    }

    const toolbar = container.querySelector('.toastui-editor-toolbar');
    if (toolbar) {
        toolbar.style.display = 'none';
    }

    container.addEventListener('focusin', () => {
        if (toolbar) toolbar.style.display = 'block';
    });

    container.addEventListener('focusout', (e) => {
        if (!container.contains(e.relatedTarget) && toolbar) {
            const selection = window.getSelection();
            if (!selection.toString()) {
                toolbar.style.display = 'none';
            }
        }
    });
}

function initToastEditorWhenVisible(textarea) {
    // Si l'élément est déjà visible, l'initialiser immédiatement.
    if (isVisible(textarea)) {
         initToastEditor(textarea);
         return;
    }
    // Sinon, utiliser un IntersectionObserver pour attendre qu'il devienne visible.
    const observer = new IntersectionObserver((entries, observer) => {
         entries.forEach(entry => {
             if (entry.isIntersecting) {
                 initToastEditor(textarea);
                 observer.unobserve(textarea);
             }
         });
    }, { rootMargin: '100px' });
    observer.observe(textarea);
}

function initAllToastEditors() {
    document.querySelectorAll('textarea.use-toast').forEach(function(tx) {
        if (!tx.classList.contains('toast-initialized')) {
            initToastEditorWhenVisible(tx);
        }
    });
}

// --- Autres Fonctions d'Aide ---
function autoResize(element) {
    if (element.tagName.toLowerCase() === 'textarea') {
        element.style.height = 'auto';
        element.style.height = element.scrollHeight + 'px';
    }
}

function addItemWithDescription(containerId, fieldPrefix) {
    let container = document.getElementById(containerId);
    let index = container.querySelectorAll('.' + fieldPrefix + '-item').length;
    let html = `
        <div class="${fieldPrefix}-item mb-1">
            <div class="d-flex align-items-start">
                <div class="flex-fill me-2">
                    <input id="${fieldPrefix}-${index}-texte" name="${fieldPrefix}-${index}-texte"
                           class="form-control fw-bold mb-1 auto-resize border-0"
                           oninput="autoResize(this)"
                           style="overflow:hidden; resize:none;"
                           placeholder="Titre"
                           type="text">
                    <textarea id="${fieldPrefix}-${index}-texte_description" name="${fieldPrefix}-${index}-texte_description"
                              class="form-control auto-resize border-0"
                              oninput="autoResize(this)"
                              style="overflow:hidden; resize:none;"
                              placeholder="Description"></textarea>
                </div>
                <button type="button" class="btn btn-danger btn-sm remove-item-btn ms-auto"
                        style="border: none;" title="Supprimer">
                    <i class="bi bi-dash-circle"></i>
                </button>
            </div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
    
    const newTextArea = document.getElementById(`${fieldPrefix}-${index}-texte_description`);
    if (newTextArea && !newTextArea.classList.contains('toast-initialized')) {
        // Pour ces listes dynamiques, on ne souhaite PAS activer Toast UI Editor.
    }
    
    showFloatingButtons();
}

function addSavoirEtre() {
    let container = document.getElementById('savoir-etre-container');
    let index = container.querySelectorAll('.savoir-etre-item').length;
    let html = `
        <div class="savoir-etre-item mb-1">
            <div class="d-flex align-items-start">
                <div class="flex-fill me-2">
                    <input type="text" 
                           id="savoir_etre-${index}-texte" 
                           name="savoir_etre-${index}-texte" 
                           class="form-control fw-bold auto-resize border-0"
                           oninput="autoResize(this)"
                           style="overflow:hidden; resize:none;"
                           placeholder="Savoir-être (en gras)"
                           value="">
                </div>
                <button type="button" class="btn btn-danger btn-sm remove-item-btn ms-auto"
                        style="border: none;" title="Supprimer">
                    <i class="bi bi-dash-circle"></i>
                </button>
            </div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
    showFloatingButtons();
}

function addCapacite() {
    const container = document.getElementById('capacites-container');
    const index = container.querySelectorAll('.capacite-item').length + 1;
    
    const html = `
        <div class="capacite-item mb-4">
            <div class="accordion" id="capaciteAccordion${index}">
                <div class="accordion-item">
                    <h2 class="accordion-header d-flex justify-content-between align-items-center">
                        <button class="accordion-button collapsed flex-grow-1" type="button"
                                data-bs-toggle="collapse"
                                data-bs-target="#collapseCapacite${index}"
                                aria-expanded="false">
                            Nouvelle capacité
                        </button>
                        <button type="button" class="btn btn-danger btn-sm remove-capacite ms-2"
                                onclick="removeCapacite(this)" title="Supprimer cette capacité">
                            <i class="bi bi-trash"></i>
                        </button>
                    </h2>
                    <div id="collapseCapacite${index}" class="accordion-collapse collapse"
                         data-bs-parent="#capaciteAccordion${index}">
                        <div class="accordion-body">
                            <div class="mb-3">
                                <label class="fw-bold">Énoncé de la capacité</label>
                                <input type="text" name="capacites-${index}-capacite" 
                                       class="form-control fw-bold auto-resize border-0"
                                       oninput="autoResize(this)"
                                       style="overflow:hidden; resize:none;"
                                       placeholder="Capacité">
                            </div>
                            <div class="mb-3">
                                <label class="fw-bold">Description</label>
                                <textarea name="capacites-${index}-description_capacite" 
                                          class="form-control auto-resize border-0 use-toast"
                                          oninput="autoResize(this)"
                                          style="overflow:hidden; resize:none;"
                                          placeholder="Description"></textarea>
                            </div>
                            <div class="mb-3">
                                <label class="fw-bold">Pondération</label>
                                <div class="d-flex align-items-center">
                                    <span class="me-1">(</span>
                                    <input type="number" name="capacites-${index}-ponderation_min"
                                           class="form-control border-0 me-2" style="width: 80px;" value="0">
                                    <span class="me-2">-</span>
                                    <input type="number" name="capacites-${index}-ponderation_max"
                                           class="form-control border-0 me-2" style="width: 80px;" value="100">
                                    <span>%)</span>
                                </div>
                            </div>
                            
                            <div class="mb-4">
                                <div class="d-flex justify-content-between align-items-center mb-2">
                                    <label class="fw-bold">Savoirs nécessaires</label>
                                    <button type="button" class="btn btn-success btn-sm add-savoir"
                                            onclick="addSavoir(${index}, 'necessaire')">
                                        <i class="bi bi-plus-circle"></i>
                                    </button>
                                </div>
                                <div id="savoirs-necessaires-${index}" class="savoirs-list"></div>
                            </div>

                            <div class="mb-4">
                                <div class="d-flex justify-content-between align-items-center mb-2">
                                    <label class="fw-bold">Savoirs faire</label>
                                    <button type="button" class="btn btn-success btn-sm add-savoir-faire"
                                            onclick="addSavoirFaire(${index})">
                                        <i class="bi bi-plus-circle"></i>
                                    </button>
                                </div>
                                <div id="savoirs-faire-${index}" class="savoirs-faire-list"></div>
                            </div>

                            <div class="mb-4">
                                <div class="d-flex justify-content-between align-items-center mb-2">
                                    <label class="fw-bold">Moyens d'évaluation</label>
                                    <button type="button" class="btn btn-success btn-sm add-moyen"
                                            onclick="addMoyen(${index})">
                                        <i class="bi bi-plus-circle"></i>
                                    </button>
                                </div>
                                <div id="moyens-evaluation-${index}" class="moyens-list"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', html);
    let newCapaciteItem = container.lastElementChild;
    if (newCapaciteItem) {
        newCapaciteItem.querySelectorAll('textarea.use-toast').forEach(function(tx) {
            if (!tx.classList.contains('toast-initialized')) {
                initToastEditorWhenVisible(tx);
            }
        });
    }
    showFloatingButtons();
}

function addSavoir(capaciteIndex, type) {
    const container = document.getElementById(`savoirs-${type}s-${capaciteIndex}`);
    if (!container) return;
    const index = container.querySelectorAll('.savoir-item').length;
    
    const html = `
        <div class="savoir-item d-flex align-items-center gap-2 mb-1">
            <input type="text" name="capacites-${capaciteIndex}-savoirs_${type}s-${index}"
                   class="form-control auto-resize border-0"
                   oninput="autoResize(this)">
            <button type="button" class="btn btn-danger btn-sm remove-item"
                    onclick="removeItem(this)">
                <i class="bi bi-dash-circle"></i>
            </button>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', html);
    showFloatingButtons();
}

function addSavoirFaire(capaciteIndex) {
    const container = document.getElementById(`savoirs-faire-${capaciteIndex}`);
    if (!container) return;
    const index = container.querySelectorAll('.savoir-faire-item').length;
    
    const html = `
        <div class="savoir-faire-item mb-4">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1 me-2">
                    <input type="text" name="capacites-${capaciteIndex}-savoirs_faire-${index}-texte"
                           class="form-control fw-bold mb-2 auto-resize border-0"
                           placeholder="Savoir faire">
                    <div class="row mb-2">
                        <div class="col-6 mb-2">
                            <label class="fw-bold text-dark px-2 rounded" style="background-color: #28a745;">
                                Cible
                            </label>
                            <textarea name="capacites-${capaciteIndex}-savoirs_faire-${index}-cible"
                                      class="form-control auto-resize border-0 mt-1"
                                      oninput="autoResize(this)"
                                      style="overflow:hidden; resize:none;"
                                      placeholder="Cible"></textarea>
                        </div>
                        <div class="col-6 mb-2">
                            <label class="fw-bold text-dark px-2 rounded" style="background-color: #ffc107;">
                                Seuil de réussite
                            </label>
                            <textarea name="capacites-${capaciteIndex}-savoirs_faire-${index}-seuil_reussite"
                                      class="form-control auto-resize border-0 mt-1"
                                      oninput="autoResize(this)"
                                      style="overflow:hidden; resize:none;"
                                      placeholder="Seuil de réussite"></textarea>
                        </div>
                    </div>
                </div>
                <button type="button" class="btn btn-danger btn-sm remove-item"
                        onclick="removeItem(this)">
                    <i class="bi bi-dash-circle"></i>
                </button>
            </div>
            <hr>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', html);
    showFloatingButtons();
}

function addMoyen(capaciteIndex) {
    const container = document.getElementById(`moyens-evaluation-${capaciteIndex}`);
    if (!container) return;
    const index = container.querySelectorAll('.moyen-item').length;
    
    const html = `
        <div class="moyen-item d-flex align-items-center gap-2 mb-1">
            <input type="text" name="capacites-${capaciteIndex}-moyens_evaluation-${index}"
                   class="form-control auto-resize border-0"
                   oninput="autoResize(this)">
            <button type="button" class="btn btn-danger btn-sm remove-item"
                    onclick="removeItem(this)">
                <i class="bi bi-dash-circle"></i>
            </button>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', html);
    showFloatingButtons();
}

function removeItem(button) {
    const parentItem = button.closest('.savoir-item, .savoir-faire-item, .moyen-item, .competences_developpees-item, .objets_cibles-item, .competences_certifiees-item, .cours_corequis-item, .cours_prealables-item, .savoir-etre-item, .cours_relies-item');
    if (parentItem) {
        parentItem.remove();
        showFloatingButtons();
    }
}

function removeCapacite(button) {
    if (confirm('Êtes-vous sûr de vouloir supprimer cette capacité ?')) {
        const capaciteItem = button.closest('.capacite-item');
        if (capaciteItem) {
            capaciteItem.remove();
            showFloatingButtons();
        }
    }
}

function showFloatingButtons() {
    const floatingSaveBtn = document.getElementById('floatingSaveBtn');
    const floatingCancelBtn = document.getElementById('floatingCancelBtn');
    if (floatingSaveBtn && floatingCancelBtn) {
        floatingSaveBtn.classList.remove('d-none');
        floatingCancelBtn.classList.remove('d-none');
    }
}

function hideFloatingButtons() {
    const floatingSaveBtn = document.getElementById('floatingSaveBtn');
    const floatingCancelBtn = document.getElementById('floatingCancelBtn');
    if (floatingSaveBtn && floatingCancelBtn) {
        floatingSaveBtn.classList.add('d-none');
        floatingCancelBtn.classList.add('d-none');
    }
}

function showFlashMessage(message, type) {
    const flashMessage = document.getElementById('flashMessageSystem');
    flashMessage.className = `alert alert-${type}`;
    flashMessage.textContent = message;
    flashMessage.classList.remove('d-none');

    setTimeout(() => {
        flashMessage.classList.add('d-none');
    }, 5000);
}

document.addEventListener('DOMContentLoaded', function() {
    // Initialisation des éditeurs Toast UI pour les textarea ciblés (ceux avec la classe use-toast)
    initAllToastEditors();

    // Ajout des écouteurs sur les boutons d'ajout des éléments de listes
    const addCompetenceBtn = document.getElementById('add-competence-developpee');
    if (addCompetenceBtn) {
        addCompetenceBtn.addEventListener('click', function() {
            addItemWithDescription('competences-developpees-container', 'competences_developpees');
        });
    }
    const addObjetCibleBtn = document.getElementById('add-objet-cible');
    if (addObjetCibleBtn) {
        addObjetCibleBtn.addEventListener('click', function() {
            addItemWithDescription('objets-cibles-container', 'objets_cibles');
        });
    }
    const addCompetenceCertifieeBtn = document.getElementById('add-competence-certifiee');
    if (addCompetenceCertifieeBtn) {
        addCompetenceCertifieeBtn.addEventListener('click', function() {
            addItemWithDescription('competences-certifiees-container', 'competences_certifiees');
        });
    }
    const addCoursCorequisBtn = document.getElementById('add-cours-corequis');
    if (addCoursCorequisBtn) {
        addCoursCorequisBtn.addEventListener('click', function() {
            addItemWithDescription('cours-corequis-container', 'cours_corequis');
        });
    }
    const addCoursPrealableBtn = document.getElementById('add-cours-prealable');
    if (addCoursPrealableBtn) {
        addCoursPrealableBtn.addEventListener('click', function() {
            addItemWithDescription('cours-prealables-container', 'cours_prealables');
        });
    }
    const addCoursRelieBtn = document.getElementById('add-cours-relies');
    if (addCoursRelieBtn) {
        addCoursRelieBtn.addEventListener('click', function() {
            addItemWithDescription('cours-relies-container', 'cours_relies');
        });
    }
    const addSavoirEtreBtn = document.getElementById('add-savoir-etre');
    if (addSavoirEtreBtn) {
        addSavoirEtreBtn.addEventListener('click', addSavoirEtre);
    }
    const addCapaciteBtn = document.getElementById('add-capacite');
    if (addCapaciteBtn) {
        addCapaciteBtn.addEventListener('click', addCapacite);
    }

    const planCadreForm = document.getElementById('planCadreForm');
    const floatingSaveBtn = document.getElementById('floatingSaveBtn');
    const floatingCancelBtn = document.getElementById('floatingCancelBtn');

    if (planCadreForm && floatingSaveBtn && floatingCancelBtn) {
        planCadreForm.addEventListener('input', showFloatingButtons);
        planCadreForm.addEventListener('change', showFloatingButtons);

        planCadreForm.addEventListener('submit', function(event) {
            event.preventDefault();
            const loadingSpinner = floatingSaveBtn.querySelector('#loadingSpinner');
            const btnText = floatingSaveBtn.querySelector('.btn-text');
            if (loadingSpinner && btnText) {
                loadingSpinner.classList.remove('d-none');
                btnText.classList.add('d-none');
            }

            const formData = new FormData(planCadreForm);
            fetch(planCadreForm.action, {
                method: planCadreForm.method,
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (loadingSpinner && btnText) {
                    loadingSpinner.classList.add('d-none');
                    btnText.classList.remove('d-none');
                }
                if (data.success) {
                    hideFloatingButtons();
                    showFlashMessage(data.message || 'Plan-cadre sauvegardé avec succès.', 'success');
                } else {
                    showFlashMessage(data.message || 'Erreur lors de la sauvegarde.', 'danger');
                }
            })
            .catch(() => {
                if (loadingSpinner && btnText) {
                    loadingSpinner.classList.add('d-none');
                    btnText.classList.remove('d-none');
                }
                showFlashMessage('Erreur lors de la sauvegarde du plan-cadre.', 'danger');
            });
        });

        floatingSaveBtn.addEventListener('click', function() {
            planCadreForm.requestSubmit();
        });

        floatingCancelBtn.addEventListener('click', function() {
            if (confirm('Êtes-vous sûr de vouloir annuler les modifications ? Toutes les modifications non sauvegardées seront perdues.')) {
                planCadreForm.reset();
                hideFloatingButtons();
                showFlashMessage('Modifications annulées.', 'warning');
            }
        });
    }

    document.addEventListener('click', function(e) {
        if (e.target.closest('.remove-item-btn')) {
            const parentItem = e.target.closest('.savoir-item, .savoir-faire-item, .moyen-item, .competences_developpees-item, .objets_cibles-item, .competences_certifiees-item, .cours_corequis-item, .cours_prealables-item, .savoir-etre-item, .cours_relies-item');
            if (parentItem) {
                parentItem.remove();
                showFloatingButtons();
            }
        }
    });

    document.querySelectorAll('.auto-resize').forEach(autoResize);
});

document.addEventListener('DOMContentLoaded', function() {
    const generateForm = document.getElementById('generateContentForm');
    const confirmGenerateBtn = document.getElementById('confirmGenerateBtn');
    const modalLoadingSpinner = document.getElementById('modalLoadingSpinner');
    const improveCheckbox = null; // Checkbox non utilisée : mode déterminé par les boutons
    const modeHidden = document.getElementById('genMode');
    const modalTitle = document.getElementById('generateModalLabel');
    const openImproveBtn = document.getElementById('openImproveBtn');
    const openGenerateBtn = document.getElementById('openGenerateBtn');
    const targetColumnsHidden = document.getElementById('genTargetColumns');
    const streamHidden = document.getElementById('genStream');
    const generalPromptGroup = document.getElementById('generalPromptGroup');
    const wandPromptGroup = document.getElementById('wandPromptGroup');

    if (!generateForm || !confirmGenerateBtn || !modalLoadingSpinner) {
        return;
    }

    // Préconfigurer le modal selon le bouton choisi
    if (openImproveBtn && modalTitle) {
        openImproveBtn.addEventListener('click', function() {
            if (modeHidden) modeHidden.value = 'improve';
            if (targetColumnsHidden) targetColumnsHidden.value = '';
            modalTitle.textContent = 'Améliorer le plan-cadre';
            confirmGenerateBtn.querySelector('.btn-text').textContent = 'Générer la proposition';
            // Vue: prompt global visible, prompt baguette caché
            if (generalPromptGroup) generalPromptGroup.classList.remove('d-none');
            if (wandPromptGroup) wandPromptGroup.classList.add('d-none');
            if (streamHidden) streamHidden.value = '0';
        });
    }
    if (openGenerateBtn && modalTitle) {
        openGenerateBtn.addEventListener('click', function() {
            if (modeHidden) modeHidden.value = 'generate';
            if (targetColumnsHidden) targetColumnsHidden.value = '';
            modalTitle.textContent = 'Générer le plan-cadre';
            confirmGenerateBtn.querySelector('.btn-text').textContent = 'Générer le plan-cadre';
            // Nettoyer additional_info au besoin
            const aiField = generateForm.querySelector('textarea[name="additional_info"]');
            if (aiField) aiField.value = '';
            // Vue: prompt global visible, prompt baguette caché
            if (generalPromptGroup) generalPromptGroup.classList.remove('d-none');
            if (wandPromptGroup) wandPromptGroup.classList.add('d-none');
            if (streamHidden) streamHidden.value = '0';
        });
    }

    // Magic wand per-section: open modal in improve mode with target column
    document.querySelectorAll('.magic-generate').forEach(btn => {
        btn.addEventListener('click', function() {
            const col = this.getAttribute('data-target-column') || '';
            if (modeHidden) modeHidden.value = 'improve';
            if (targetColumnsHidden) targetColumnsHidden.value = col;
            // Activer le mode "wand" pour un prompt distinct et simple
            if (modeHidden) modeHidden.value = 'wand';
            // Déterminer un titre humain lisible depuis l'étiquette proche
            let sectionTitle = '';
            const labelEl = this.closest('label, h6');
            if (labelEl) {
                sectionTitle = (labelEl.innerText || '').trim();
            }
            if (!sectionTitle) sectionTitle = 'Section sélectionnée';
            if (modalTitle) modalTitle.textContent = `Améliorer: ${sectionTitle}`;
            if (confirmGenerateBtn) confirmGenerateBtn.querySelector('.btn-text').textContent = 'Générer la proposition';
            // Afficher le prompt baguette et masquer le prompt global
            if (generalPromptGroup) generalPromptGroup.classList.add('d-none');
            if (wandPromptGroup) {
                wandPromptGroup.classList.remove('d-none');
                const wandField = generateForm.querySelector('textarea[name="wand_instruction"]');
                if (wandField) {
                    wandField.value = `Améliorer uniquement la section « ${sectionTitle} ». Rendre le texte plus clair, simple et concis sans ajouter d'information.`;
                }
            }
            if (streamHidden) streamHidden.value = '1';
        });
    });

    generateForm.addEventListener('submit', function(e) {
        e.preventDefault();
        confirmGenerateBtn.disabled = true;
        modalLoadingSpinner.classList.remove('d-none');
        confirmGenerateBtn.querySelector('.btn-text').textContent = 'Génération en cours...';

        fetch(generateForm.action, {
            method: generateForm.method,
            body: new FormData(generateForm),
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => response.json())
        .then(data => {
            confirmGenerateBtn.disabled = false;
            modalLoadingSpinner.classList.add('d-none');
            // Rétablir le texte selon le mode actuel
            if (modeHidden && (modeHidden.value === 'improve' || modeHidden.value === 'wand')) {
                confirmGenerateBtn.querySelector('.btn-text').textContent = 'Générer la proposition';
            } else {
                confirmGenerateBtn.querySelector('.btn-text').textContent = 'Générer le plan-cadre';
            }

            const generateModalEl = document.getElementById('generateModal');
            const modalInstance = bootstrap.Modal.getInstance(generateModalEl);

            if (data.success) {
                taskId = data.task_id;
                sessionStorage.setItem('currentTaskId', taskId);
                // Activer l'aperçu streaming si demandé
                const doStream = streamHidden && streamHidden.value === '1';
                if (doStream) {
                    const container = document.getElementById('streamContainer');
                    const out = document.getElementById('streamOutput');
                    const status = document.getElementById('streamStatus');
                    if (container && out) {
                        out.textContent = '';
                        container.classList.remove('d-none');
                    }
                    window.onTaskStreamUpdate = function(meta) {
                        try {
                            if (!meta) return;
                            const out = document.getElementById('streamOutput');
                            const status = document.getElementById('streamStatus');
                            if (status && meta.message) status.textContent = meta.message;
                            if (out) {
                                if (meta.stream_buffer) {
                                    out.textContent = meta.stream_buffer;
                                } else if (meta.stream_chunk) {
                                    out.textContent += meta.stream_chunk;
                                }
                                out.scrollTop = out.scrollHeight;
                            }
                        } catch (e) { console.warn('stream update error', e); }
                    };
                } else {
                    window.onTaskStreamUpdate = null;
                    if (modalInstance) {
                        modalInstance.hide();
                    }
                }
                // Démarrer le polling uniquement après la configuration du streaming
                if (typeof startTaskPolling === 'function') {
                    startTaskPolling(taskId);
                }
                flashMessageSystem.info(data.message);
            } else {
                flashMessageSystem.error(data.message || 'Action non autorisée.');
            }
        })
        .catch(error => {
            confirmGenerateBtn.disabled = false;
            modalLoadingSpinner.classList.add('d-none');
            if (modeHidden && (modeHidden.value === 'improve' || modeHidden.value === 'wand')) {
                confirmGenerateBtn.querySelector('.btn-text').textContent = 'Générer la proposition';
            } else {
                confirmGenerateBtn.querySelector('.btn-text').textContent = 'Générer le plan-cadre';
            }
            flashMessageSystem.error('Erreur lors de la génération du plan-cadre.');
            console.error("Erreur lors de la génération du plan-cadre:", error);
        });
    });
});
