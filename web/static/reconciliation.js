(() => {
    "use strict";

    const bootstrap = JSON.parse(document.getElementById("reconciliation-data").textContent);
    let review = bootstrap.state;
    let categories = bootstrap.categories;
    let section = "new";
    let busy = false;
    let previousAttempt = null;
    let toastTimer;
    const selected = new Set();
    const versions = new Map();
    const categorySaves = new Map();
    const suggested = new Set();
    const suggestionQueue = [];
    let suggesting = 0;
    const baseUrl = `/api/reconciliation/${review.statement_id}`;
    const labels = {new: "Só na fatura", matched: "Conciliados", bank: "Só no banco"};
    const descriptions = {
        new: "Selecione as compras que deseja inserir e confira as categorias.",
        matched: "Compare a descrição da fatura com o nome registrado via Telegram antes de confirmar.",
        bank: "Revise os registros do banco que não aparecem na fatura."
    };
    const money = cents => (cents / 100).toLocaleString("pt-BR", {style: "currency", currency: "BRL"});
    const date = value => value ? new Date(`${value}T00:00:00Z`).toLocaleDateString("pt-BR", {
        day: "2-digit", month: "short", year: "numeric", timeZone: "UTC"
    }).replace(/ de /g, " ").replace(".", "") : "Data original indisponível";
    const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);
    const pending = () => review.items.filter(item => item.section === section);

    function toast(message, error = false) {
        clearTimeout(toastTimer);
        const el = document.getElementById("toast");
        el.textContent = message;
        el.className = error ? "toast error" : "toast";
        el.setAttribute("role", error ? "alert" : "status");
        toastTimer = setTimeout(() => el.classList.add("hidden"), error ? 8000 : 3500);
    }

    async function api(url, data) {
        let response;
        try {
            response = await fetch(url, {
                method: data === undefined ? "GET" : "POST",
                credentials: "same-origin",
                cache: "no-store",
                ...(data === undefined ? {} : {
                    headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)
                })
            });
        } catch {
            throw new Error("Sem conexão com o servidor. Sua seleção foi mantida; tente novamente.");
        }
        if (response.status === 401) throw new Error("Sua sessão expirou. Faça login novamente para continuar.");
        let result;
        try {
            result = await response.json();
        } catch {
            throw new Error("Resposta inválida do servidor. Atualize a página para conferir o estado salvo.");
        }
        if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Não foi possível concluir a operação. Confira os itens e tente novamente.");
        return result;
    }

    function matchDetails(item) {
        const candidate = item.candidates?.find(candidate => candidate.expense_id === item.expense_id);
        const bankName = candidate?.name ?? item.bank_name;
        const bankDate = candidate?.date ?? item.bank_date;
        const bankAmount = candidate?.amount_cents ?? item.bank_amount_cents;
        const bankCategory = candidate?.category ?? item.bank_category;
        const choice = item.ambiguous ? `<select class="match-choice" data-match="${esc(item.id)}" aria-label="Registro do Telegram correspondente a ${esc(item.name)}" ${busy ? "disabled" : ""}>
            <option value="">Selecionar registro correspondente</option>
            ${item.candidates.map(candidate => `<option value="${candidate.expense_id}" ${candidate.expense_id === item.expense_id ? "selected" : ""}>${esc(candidate.name)} · ${date(candidate.date)} · ${money(candidate.amount_cents)}</option>`).join("")}
        </select>` : "";
        return `<div class="match-pair">
            <div><div class="match-label">Na fatura do Bradesco</div>
                <div class="match-bank">${esc(item.name)}</div>
                <div class="match-caption">${date(item.date)} · ${money(item.amount_cents)} · Fatura #${item.tx_id}</div>
            </div>
            <div><div class="match-label">Registrado via Telegram</div>${choice}
                <div class="match-bank">${esc(bankName || (item.ambiguous ? "Escolha a correspondência acima" : "Descrição original indisponível"))}</div>
                <div class="match-caption">${[
                    bankDate ? date(bankDate) : "", bankAmount != null ? money(bankAmount) : "",
                    esc(bankCategory), item.expense_id ? `Registro #${item.expense_id}` : ""
                ].filter(Boolean).join(" · ")}</div>
            </div>
        </div>`;
    }

    function renderItem(item) {
        const details = [date(item.date)];
        if (item.installment_info) details.push(`Parcela ${esc(item.installment_info)}`);
        else details.push(item.section === "bank" ? "Registro existente no banco" : "Cartão de crédito");
        if (item.card_last_four) details.push(`Cartão final ${esc(item.card_last_four)}`);
        const hint = item.section === "matched" ? (item.ambiguous ? "Confira a correspondência" : "Correspondência identificada") : (item.category && !item.category_edited && item.section === "new" ? "Sugestão de categoria" : "");
        return `<article class="expense" data-item-id="${esc(item.id)}" ${item.tx_id ? `data-tx-id="${item.tx_id}"` : ""} ${item.expense_id ? `data-expense-id="${item.expense_id}"` : ""}>
            <input type="checkbox" data-check="${esc(item.id)}" aria-label="Selecionar ${esc(item.name)}" ${selected.has(item.id) ? "checked" : ""} ${busy ? "disabled" : ""}>
            <div><div class="name">${esc(item.name)}</div><div class="date">${details.join(" · ")}</div>${hint ? `<span class="pill">${hint}</span>` : ""}</div>
            <div class="amount">${money(item.amount_cents)}</div>
            ${item.section === "matched" ? matchDetails(item) : ""}
            <select class="category" data-cat="${esc(item.id)}" aria-label="Categoria ${esc(item.name)}" ${busy ? "disabled" : ""}>
                <option value="">Selecionar categoria</option>
                ${categories.map(category => `<option value="${esc(category)}" ${item.category === category ? "selected" : ""}>${esc(category)}</option>`).join("")}
            </select>
        </article>`;
    }

    function updateSelection() {
        const items = pending();
        const chosen = items.filter(item => selected.has(item.id));
        document.getElementById("selected-count").textContent = `${chosen.length} ${chosen.length === 1 ? "selecionado" : "selecionados"}`;
        document.getElementById("selected-sum").textContent = money(chosen.reduce((sum, item) => sum + item.amount_cents, 0));
        document.getElementById("approve").disabled = document.getElementById("ignore").disabled = busy || !chosen.length;
        document.getElementById("select-all").disabled = busy || !items.length;
        document.getElementById("select-all").textContent = items.length && chosen.length === items.length ? "Desmarcar todos" : "Selecionar todos";
    }

    function render() {
        document.querySelectorAll(".stat[data-section]").forEach(card => {
            const active = card.dataset.section === section;
            card.classList.toggle("active", active);
            card.setAttribute("aria-pressed", String(active));
            card.disabled = busy;
            document.getElementById(`count-${card.dataset.section}`).textContent = review.counts[card.dataset.section];
        });
        const progress = review.progress;
        document.getElementById("progress-count").textContent = `${progress.reviewed} de ${progress.total} revisados`;
        document.getElementById("progress-fill").style.width = `${progress.percent}%`;
        document.getElementById("progress-track").setAttribute("aria-valuenow", progress.percent);
        document.getElementById("progress-totals").textContent = `${progress.approved} aprovados · ${progress.ignored} ignorados · ${progress.pending} pendentes`;
        document.getElementById("section-info").textContent = descriptions[section];
        const items = pending();
        document.getElementById("items").innerHTML = items.length ? items.map(renderItem).join("") : '<div class="empty">Nenhum lançamento pendente nesta seção.</div>';
        document.getElementById("items").setAttribute("aria-busy", String(busy));
        document.getElementById("history-title").textContent = `Histórico de decisões (${review.history.length})`;
        document.getElementById("history-items").innerHTML = review.history.length ? [...review.history].reverse().map(item => {
            const timestamp = item.reviewed_at ? new Date(item.reviewed_at.replace(" ", "T") + "Z").toLocaleString("pt-BR") : "Data da decisão legada indisponível";
            return `<div class="history-item" data-history-id="${esc(item.id)}"><div><strong>${esc(item.name)}</strong>
                <small>${labels[item.section]} · ${money(item.amount_cents)}${item.category ? ` · ${esc(item.category)}` : ""}</small>
                ${item.section === "matched" ? `<small>Telegram: ${esc(item.bank_name || "Descrição original indisponível")} · ${date(item.bank_date)}${item.bank_amount_cents != null ? ` · ${money(item.bank_amount_cents)}` : ""}</small>` : ""}
                <small>${esc(timestamp)}${item.tx_id ? ` · Fatura #${item.tx_id}` : ""}${item.expense_id ? ` · Registro #${item.expense_id}` : ""}</small></div>
                <span class="status ${item.decision === "ignored" ? "ignored" : ""}">${item.decision === "approved" ? "Aprovado" : "Ignorado"}</span></div>`;
        }).join("") : '<p class="hint">Nenhum lançamento revisado ainda.</p>';
        document.getElementById("warnings").innerHTML = review.warnings.map(warning => `<div class="warning">${esc(warning)}</div>`).join("");
        updateSelection();
    }

    function saveCategory(item, category) {
        item.category = category || null;
        item.category_edited = true;
        const version = (versions.get(item.id) || 0) + 1;
        versions.set(item.id, version);
        // Serialize edits so a slower earlier request cannot overwrite the last choice.
        const save = (categorySaves.get(item.id) || Promise.resolve()).then(async () => {
            try {
                const result = await api(`${baseUrl}/category`, {id: item.id, category});
                if (!result.success) throw new Error("Não foi possível salvar a categoria.");
                const current = review.items.find(current => current.id === item.id);
                if (current && versions.get(item.id) === version) current.category = result.category;
            } catch (error) {
                toast(`${error.message} A categoria será conferida novamente ao aprovar.`, true);
            }
        }).finally(() => {
            if (categorySaves.get(item.id) === save) categorySaves.delete(item.id);
        });
        categorySaves.set(item.id, save);
    }

    function suggestCategories() {
        review.items.filter(item => item.section === "new" && !item.category && !item.category_edited && !suggested.has(item.id)).forEach(item => {
            suggested.add(item.id);
            suggestionQueue.push({id: item.id, txId: item.tx_id, version: versions.get(item.id) || 0});
        });
        while (suggesting < 2 && suggestionQueue.length) {
            const request = suggestionQueue.shift();
            suggesting++;
            api(`/api/suggest-category/${request.txId}`).then(result => {
                const item = review.items.find(item => item.id === request.id);
                if (!item || item.category_edited || (versions.get(item.id) || 0) !== request.version || !categories.includes(result.category)) return;
                item.category = result.category;
                const select = document.querySelector(`[data-cat="${item.id}"]`);
                if (select) select.value = result.category;
            }).catch(() => {}).finally(() => {
                suggesting--;
                suggestCategories();
            });
        }
    }

    async function act(action) {
        if (busy) return;
        const chosen = pending().filter(item => selected.has(item.id));
        if (!chosen.length) return;
        if (action === "approve" && section === "new" && chosen.some(item => !categories.includes(item.category))) {
            toast("Selecione a categoria das compras antes de aprovar.", true);
            return;
        }
        if (action === "approve" && section === "matched" && chosen.some(item => !item.expense_id)) {
            toast("Selecione o registro do Telegram correspondente a cada lançamento ambíguo.", true);
            return;
        }
        busy = true;
        render();
        try {
            // The batch returns the whole screen; include edits outside its selection.
            await Promise.all([...categorySaves.values()]);
            const items = chosen.map(item => ({
                id: item.id, category: item.category || "",
                ...(section === "matched" && item.expense_id ? {expense_id: item.expense_id} : {})
            }));
            const payload = {section, action, items};
            const signature = JSON.stringify(payload);
            // Retain the same key after a lost response, not just after a successful response.
            if (previousAttempt?.signature !== signature) {
                const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
                previousAttempt = {signature, requestId};
            }
            const result = await api(`${baseUrl}/batch`, {...payload, request_id: previousAttempt.requestId});
            if (!result.success || !result.state) throw new Error("A gravação não foi confirmada pelo servidor. Tente novamente.");
            review = result.state;
            previousAttempt = null;
            selected.clear();
            toast(`${result.processed} lançamento(s) ${action === "approve" ? "aprovado(s)" : "ignorado(s)"}.`);
        } catch (error) {
            toast(error.message, true);
        } finally {
            busy = false;
            render();
            suggestCategories();
        }
    }

    document.getElementById("stats").addEventListener("click", event => {
        const card = event.target.closest("[data-section]");
        if (!card || busy) return;
        section = card.dataset.section;
        selected.clear();
        render();
    });
    document.getElementById("select-all").addEventListener("click", () => {
        if (busy) return;
        const items = pending();
        if (items.every(item => selected.has(item.id))) selected.clear();
        else items.forEach(item => selected.add(item.id));
        render();
    });
    document.getElementById("items").addEventListener("change", event => {
        if (busy) return;
        const el = event.target;
        if (el.dataset.check) {
            if (el.checked) selected.add(el.dataset.check);
            else selected.delete(el.dataset.check);
            updateSelection();
        } else if (el.dataset.cat) {
            const item = review.items.find(item => item.id === el.dataset.cat);
            saveCategory(item, el.value);
        } else if (el.dataset.match) {
            const item = review.items.find(item => item.id === el.dataset.match);
            item.expense_id = Number(el.value) || null;
            const candidate = item.candidates.find(candidate => candidate.expense_id === item.expense_id);
            if (candidate && !item.category_edited && categories.includes(candidate.category)) item.category = candidate.category;
            render();
        }
    });
    document.getElementById("approve").addEventListener("click", () => act("approve"));
    document.getElementById("ignore").addEventListener("click", () => act("ignore"));
    document.getElementById("back").addEventListener("click", event => {
        if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        if (document.referrer && history.length > 1) {
            const previous = new URL(document.referrer);
            if (previous.origin === location.origin && previous.pathname !== location.pathname) {
                event.preventDefault();
                history.back();
            }
        }
    });
    window.addEventListener("pageshow", async event => {
        if (!event.persisted) return;
        try {
            const result = await api(baseUrl);
            review = result.state;
            categories = result.categories;
            selected.clear();
            render();
            suggestCategories();
        } catch (error) {
            toast(error.message, true);
        }
    });

    render();
    suggestCategories();
})();
