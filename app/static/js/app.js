document.addEventListener('DOMContentLoaded', function() {
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : null;

    if (csrfToken) {
        document.querySelectorAll('form[method="POST"], form[method="post"]').forEach(function(form) {
            if (!form.querySelector('input[name="csrf_token"]')) {
                var input = document.createElement('input');
                input.type = 'hidden';
                input.name = 'csrf_token';
                input.value = csrfToken;
                form.appendChild(input);
            }
        });
    }

    function normalizeText(value) {
        // NFD \u015f/\u011f/\u00fc/\u00f6/\u00e7'yi ayr\u0131\u015ft\u0131r\u0131r; noktas\u0131z "\u0131" ayr\u0131\u015fmad\u0131\u011f\u0131 i\u00e7in ayr\u0131ca
        // "i"ye indirgenir ki "pinar" aramas\u0131 "P\u0131nar"\u0131 bulsun.
        return (value || '')
            .toString()
            .toLowerCase()
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .replace(/\u0131/g, 'i');
    }

    // Typeahead for selects with many options
    document.querySelectorAll('select.js-searchable-select').forEach(function(select) {
        if (select.dataset.searchReady === '1') {
            return;
        }

        var placeholder = select.dataset.searchPlaceholder || 'Yazarak ara...';
        var options = Array.from(select.options).filter(function(opt) {
            return opt.value;
        });

        var wrapper = document.createElement('div');
        wrapper.className = 'typeahead-wrapper';

        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'form-control mb-2';
        input.placeholder = placeholder;
        input.autocomplete = 'off';

        var list = document.createElement('div');
        list.className = 'typeahead-list list-group shadow-sm';

        // Set initial value in input
        if (select.value) {
            var selectedOption = options.find(function(opt) { return opt.value === select.value; });
            if (selectedOption) {
                input.value = selectedOption.textContent.trim();
            }
        }

        // Hide the original select (but keep id, name, and option elements intact!)
        select.classList.add('d-none');

        // Insert wrapper before select
        select.parentNode.insertBefore(wrapper, select);
        wrapper.appendChild(input);
        wrapper.appendChild(list);
        wrapper.appendChild(select); // move select inside wrapper for tidy hierarchy

        function renderList(query) {
            var nq = normalizeText(query);
            var matches = options.filter(function(opt) {
                return !nq || normalizeText(opt.textContent).indexOf(nq) !== -1;
            }).slice(0, 100);

            list.innerHTML = '';
            if (!matches.length) {
                list.style.display = 'none';
                return;
            }

            matches.forEach(function(opt) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'list-group-item list-group-item-action';
                btn.textContent = opt.textContent.trim();
                btn.addEventListener('mousedown', function() {
                    select.value = opt.value;
                    input.value = opt.textContent.trim();
                    list.style.display = 'none';
                    // Dispatch change event on the original select so page scripts trigger
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                });
                list.appendChild(btn);
            });

            list.style.display = 'block';
        }

        input.addEventListener('input', function() {
            select.value = ''; // clear select until an item is explicitly clicked
            select.dispatchEvent(new Event('change', { bubbles: true }));
            renderList(input.value);
        });

        input.addEventListener('focus', function() {
            renderList(input.value);
        });

        input.addEventListener('blur', function() {
            window.setTimeout(function() {
                list.style.display = 'none';
                // If user blurs without picking an item and has typed something that doesn't match, or cleared it
                if (!select.value) {
                    input.value = '';
                } else {
                    var selectedOption = options.find(function(opt) { return opt.value === select.value; });
                    if (selectedOption) {
                        input.value = selectedOption.textContent.trim();
                    }
                }
            }, 120);
        });

        select.dataset.searchReady = '1';
    });

    // Live server-side search for paginated lists — no page reload.
    // A client-only row filter can only see the current page's rows, so
    // typing "ö" would never reveal matches on other pages. Instead we fetch
    // just the results fragment (Turkish-aware search across the whole table)
    // and swap it in, keeping the input, focus and scroll position intact.
    document.querySelectorAll('input.js-live-search').forEach(function(input) {
        var form = input.closest('form');
        var results = document.querySelector(input.getAttribute('data-results') || '');
        if (!form || !results || !window.fetch || !window.DOMParser) {
            return; // no JS support: the form still submits normally
        }

        var delay = parseInt(input.getAttribute('data-search-delay'), 10) || 250;
        var timer = null;
        var controller = null;

        function swapResults(html) {
            var parsed = new DOMParser().parseFromString(html, 'text/html');
            var nodes = Array.prototype.slice.call(parsed.body.childNodes);
            results.replaceChildren();
            nodes.forEach(function(node) {
                results.appendChild(document.importNode(node, true));
            });
        }

        function runSearch() {
            var params = new URLSearchParams(new FormData(form));
            params.set('partial', '1');

            if (controller) {
                controller.abort(); // drop the in-flight, now-stale request
            }
            controller = new AbortController();
            results.setAttribute('aria-busy', 'true');

            fetch(form.action + '?' + params.toString(), {
                signal: controller.signal,
                headers: { 'X-Requested-With': 'fetch' },
                credentials: 'same-origin'
            })
                .then(function(response) { return response.text(); })
                .then(function(html) {
                    swapResults(html);
                    results.removeAttribute('aria-busy');
                    // Keep the address bar in sync so refresh/bookmark works,
                    // without pushing a history entry per keystroke.
                    params.delete('partial');
                    var query = params.toString();
                    window.history.replaceState({}, '', form.action + (query ? '?' + query : ''));
                })
                .catch(function(error) {
                    if (error.name !== 'AbortError') {
                        results.removeAttribute('aria-busy');
                    }
                });
        }

        input.addEventListener('input', function() {
            clearTimeout(timer);
            timer = setTimeout(runSearch, delay);
        });

        // Enter would reload the page; results are already live.
        input.addEventListener('keydown', function(event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                clearTimeout(timer);
                runSearch();
            }
        });
    });

    // Generic checkbox list filter
    document.querySelectorAll('input.js-checkbox-filter').forEach(function(input) {
        var targetSelector = input.getAttribute('data-target');
        if (!targetSelector) {
            return;
        }

        var items = document.querySelectorAll(targetSelector);
        input.addEventListener('input', function() {
            var q = normalizeText(input.value.trim());
            items.forEach(function(item) {
                var text = normalizeText(item.textContent || '');
                item.style.display = !q || text.indexOf(q) !== -1 ? '' : 'none';
            });
        });
    });

    // Auto-dismiss alerts after 5 seconds
    document.querySelectorAll('.alert-dismissible').forEach(function(alert) {
        setTimeout(function() {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });

    // ── Dark mode toggle ──────────────────────────────────────
    var themeToggle = document.querySelector('.theme-toggle');
    var storedTheme = localStorage.getItem('makro-theme');
    if (storedTheme === 'dark') {
        document.documentElement.setAttribute('data-bs-theme', 'dark');
        if (themeToggle) themeToggle.querySelector('i').className = 'bi bi-sun';
    }
    if (themeToggle) {
        themeToggle.addEventListener('click', function() {
            var isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
            var icon = themeToggle.querySelector('i');
            if (isDark) {
                document.documentElement.removeAttribute('data-bs-theme');
                localStorage.setItem('makro-theme', 'light');
                icon.className = 'bi bi-moon-stars';
            } else {
                document.documentElement.setAttribute('data-bs-theme', 'dark');
                localStorage.setItem('makro-theme', 'dark');
                icon.className = 'bi bi-sun';
            }
        });
    }

    // ── Confirm modal (replaces browser native confirm()) ─────
    var deleteModalEl = document.getElementById('confirmDeleteModal');
    if (deleteModalEl) {
        var deleteModal = new bootstrap.Modal(deleteModalEl);
        var pendingForm = null;
        var pendingSubmitter = null;

        function prepareConfirmModal(el) {
            var msg = el.getAttribute('data-confirm') || 'Bu işlemi gerçekleştirmek istediğinize emin misiniz?';
            var title = el.getAttribute('data-confirm-title');
            var btnText = el.getAttribute('data-confirm-btn');
            var btnClass = el.getAttribute('data-confirm-btn-class');
            var iconClass = el.getAttribute('data-confirm-icon');

            var lowerMsg = msg.toLowerCase();
            var isDelete = lowerMsg.includes('sil') || lowerMsg.includes('kalıcı') || (el.classList && (el.classList.contains('btn-danger') || el.classList.contains('text-danger')));
            var isSend = lowerMsg.includes('gönder') || lowerMsg.includes('whatsapp');

            if (!title) {
                if (isSend) title = 'WhatsApp Gönderim Onayı';
                else if (isDelete) title = 'Silme Onayı';
                else title = 'İşlem Onayı';
            }

            if (!btnText) {
                if (isSend) btnText = 'Evet, Gönder';
                else if (isDelete) btnText = 'Evet, Sil';
                else btnText = 'Evet, Onayla';
            }

            if (!btnClass) {
                if (isSend) btnClass = 'btn-success';
                else if (isDelete) btnClass = 'btn-danger';
                else btnClass = 'btn-primary';
            }

            if (!iconClass) {
                if (isSend) iconClass = 'bi-whatsapp';
                else if (isDelete) iconClass = 'bi-trash';
                else iconClass = 'bi-check-circle';
            }

            var titleEl = document.getElementById('confirmModalTitle');
            var messageEl = document.getElementById('confirmDeleteMessage');
            var iconEl = document.getElementById('confirmModalIcon');
            var confirmBtn = document.getElementById('confirmDeleteBtn');
            var btnTextEl = document.getElementById('confirmModalBtnText');
            var btnIconEl = document.getElementById('confirmModalBtnIcon');

            if (messageEl) messageEl.textContent = msg;
            if (titleEl) titleEl.textContent = title;
            if (iconEl) iconEl.className = 'bi ' + iconClass + ' me-2';
            if (confirmBtn) confirmBtn.className = 'btn btn-sm ' + btnClass;
            if (btnTextEl) btnTextEl.textContent = btnText;
            if (btnIconEl) btnIconEl.className = 'bi ' + iconClass + ' me-1';
        }

        document.querySelectorAll('form[data-confirm], [data-confirm]').forEach(function(el) {
            if (el.tagName === 'FORM') {
                el.addEventListener('submit', function(e) {
                    if (el.dataset.confirmed === 'true') {
                        el.dataset.confirmed = 'false';
                        return;
                    }
                    e.preventDefault();
                    pendingForm = el;
                    pendingSubmitter = null;
                    prepareConfirmModal(el);
                    deleteModal.show();
                });
            } else if (el.tagName === 'BUTTON' || el.tagName === 'A' || el.tagName === 'INPUT') {
                el.addEventListener('click', function(e) {
                    if (el.dataset.confirmed === 'true') {
                        el.dataset.confirmed = 'false';
                        return;
                    }
                    e.preventDefault();
                    pendingForm = el.form || null;
                    pendingSubmitter = el;
                    prepareConfirmModal(el);
                    deleteModal.show();
                });
            }
        });

        var confirmBtn = document.getElementById('confirmDeleteBtn');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', function() {
                if (pendingSubmitter && pendingSubmitter.tagName === 'A' && pendingSubmitter.href) {
                    window.location.href = pendingSubmitter.href;
                } else if (pendingSubmitter && pendingForm) {
                    pendingSubmitter.dataset.confirmed = 'true';
                    pendingSubmitter.click();
                } else if (pendingForm) {
                    pendingForm.dataset.confirmed = 'true';
                    pendingForm.submit();
                }
                deleteModal.hide();
            });
        }
    }

    // ── Currency input mask ───────────────────────────────────
    document.querySelectorAll('input[data-currency-mask]').forEach(function(input) {
        input.setAttribute('inputmode', 'decimal');
        input.setAttribute('pattern', '[0-9]*[.,]?[0-9]*');
        input.addEventListener('input', function() {
            var val = input.value.replace(/[^\d.,]/g, '');
            // Normalize comma to dot for consistency
            var parts = val.split(/[.,]/);
            if (parts.length > 2) {
                val = parts[0] + '.' + parts.slice(1).join('');
            }
            input.value = val;
        });
    });

    // ── Scrollable table wrappers must be keyboard-reachable ──
    // (axe-core: scrollable-region-focusable)
    document.querySelectorAll('.table-responsive').forEach(function(el) {
        if (!el.hasAttribute('tabindex')) {
            el.setAttribute('tabindex', '0');
        }
    });

    // ── Inline form validation feedback ──────────────────────
    document.querySelectorAll('form.needs-validation').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();
            }
            form.classList.add('was-validated');
        });
    });

    // ── Command Palette (Cmd + K / Ctrl + K) ───────────────────
    document.addEventListener('keydown', function(e) {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            var modalEl = document.getElementById('commandPaletteModal');
            if (modalEl) {
                var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                modal.toggle();
            }
        }
    });

    var cmdModal = document.getElementById('commandPaletteModal');
    if (cmdModal) {
        cmdModal.addEventListener('shown.bs.modal', function() {
            var input = document.getElementById('cmdPaletteInput');
            if (input) {
                input.focus();
            }
        });

        var cmdInput = document.getElementById('cmdPaletteInput');
        var cmdResults = document.getElementById('cmdPaletteResults');
        if (cmdInput && cmdResults) {
            var debounceTimer = null;
            cmdInput.addEventListener('input', function() {
                clearTimeout(debounceTimer);
                var query = cmdInput.value.trim();
                if (!query) {
                    cmdResults.innerHTML = '<div class="text-center text-muted py-3"><small>Doktor, hasta veya iş emri ara...</small></div>';
                    return;
                }
                debounceTimer = setTimeout(function() {
                    cmdResults.innerHTML = '<div class="text-center text-muted py-3"><div class="spinner-border spinner-border-sm me-2"></div>Aranıyor...</div>';
                    fetch('/api/v1/parties?q=' + encodeURIComponent(query))
                        .then(function(res) { return res.json(); })
                        .then(function(data) {
                            var items = data.data || data.items || data;
                            cmdResults.innerHTML = '';
                            if (Array.isArray(items) && items.length > 0) {
                                var group = document.createElement('div');
                                group.className = 'list-group list-group-flush';
                                items.slice(0, 8).forEach(function(item) {
                                    var a = document.createElement('a');
                                    a.className = 'list-group-item list-group-item-action d-flex align-items-center justify-content-between py-2';
                                    a.href = item.id ? '/parties/' + item.id : '#';
                                    a.innerHTML = '<div><strong>' + (item.name || item.display_name || 'Kayıt') + '</strong></div><span class="badge bg-secondary-subtle text-secondary small">Doktor</span>';
                                    group.appendChild(a);
                                });
                                cmdResults.appendChild(group);
                            } else {
                                cmdResults.innerHTML = '<div class="text-center text-muted py-3"><small>Sonuç bulunamadı</small></div>';
                            }
                        })
                        .catch(function() {
                            cmdResults.innerHTML = '<div class="text-center text-danger py-3"><small>Arama sırasında bir hata oluştu.</small></div>';
                        });
                }, 250);
            });
        }
    }

    // ── Mobile FAB Toggle ──────────────────────────────────────
    var fabBtn = document.getElementById('mobileFabBtn');
    var fabMenu = document.getElementById('mobileFabMenu');
    if (fabBtn && fabMenu) {
        fabBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            fabMenu.classList.toggle('show');
            var icon = fabBtn.querySelector('i');
            if (icon) {
                icon.className = fabMenu.classList.contains('show') ? 'bi bi-x-lg' : 'bi bi-plus-lg';
            }
        });

        document.addEventListener('click', function(e) {
            if (fabMenu.classList.contains('show') && !fabMenu.contains(e.target) && e.target !== fabBtn) {
                fabMenu.classList.remove('show');
                var icon = fabBtn.querySelector('i');
                if (icon) {
                    icon.className = 'bi bi-plus-lg';
                }
            }
        });
    }

    // ── Parties View Mode Toggle (Grid vs Table) ───────────────
    var toggleContainer = document.getElementById('partiesViewToggle');
    if (toggleContainer) {
        var gridView = document.getElementById('partiesGridView');
        var tableView = document.getElementById('partiesTableView');
        var buttons = toggleContainer.querySelectorAll('.view-mode-btn');

        function setView(mode) {
            buttons.forEach(function(btn) {
                if (btn.dataset.view === mode) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            });
            if (gridView && tableView) {
                if (mode === 'table') {
                    gridView.classList.add('d-none');
                    tableView.classList.remove('d-none');
                } else {
                    gridView.classList.remove('d-none');
                    tableView.classList.add('d-none');
                }
            }
            try {
                localStorage.setItem('parties_view_mode', mode);
            } catch (err) {}
        }

        buttons.forEach(function(btn) {
            btn.addEventListener('click', function() {
                setView(btn.dataset.view);
            });
        });

        // Load saved preference or default to grid
        var savedMode = 'grid';
        try {
            savedMode = localStorage.getItem('parties_view_mode') || 'grid';
        } catch (err) {}
        setView(savedMode);
    }
});
