(() => {
    "use strict";

    const data = JSON.parse(document.getElementById("dashboard-data").textContent);
    document.querySelectorAll("[data-auto-submit]").forEach(form => {
        form.addEventListener("change", () => form.requestSubmit());
    });

    const money = cents => (cents / 100).toLocaleString("pt-BR", {style: "currency", currency: "BRL"});
    document.querySelectorAll(".bar[data-month]").forEach(bar => {
        const show = () => {
            document.getElementById("evolution-value").textContent = `${bar.dataset.month} · ${money(Number(bar.dataset.total))}`;
        };
        bar.addEventListener("pointerenter", show);
        bar.addEventListener("focus", show);
        bar.addEventListener("click", show);
    });

    const donut = document.getElementById("donut");
    const tip = document.getElementById("donut-tip");
    let activeSlice = -1;
    function showSlice(index) {
        const part = data.category_parts[index];
        if (!part) return;
        activeSlice = index;
        tip.textContent = `${part.name} · ${money(part.total_cents)}`;
    }
    function sliceAtPointer(event) {
        const rect = donut.getBoundingClientRect();
        const x = event.clientX - rect.left - rect.width / 2;
        const y = event.clientY - rect.top - rect.height / 2;
        const distance = Math.hypot(x, y);
        if (distance < 64 || distance > rect.width / 2) return;
        const angle = (Math.atan2(y, x) * 180 / Math.PI + 450) % 360;
        let accumulated = 0;
        for (let index = 0; index < data.category_parts.length; index++) {
            accumulated += data.category_parts[index].percent * 3.6;
            if (angle <= accumulated + .001) {
                showSlice(index);
                break;
            }
        }
    }
    donut.addEventListener("pointermove", event => {
        if (event.pointerType === "mouse") sliceAtPointer(event);
    });
    donut.addEventListener("click", sliceAtPointer);
    donut.addEventListener("keydown", event => {
        if (!["Enter", " ", "ArrowRight", "ArrowLeft"].includes(event.key) || !data.category_parts.length) return;
        event.preventDefault();
        const step = event.key === "ArrowLeft" ? -1 : 1;
        const count = data.category_parts.length;
        showSlice(activeSlice < 0 ? (step < 0 ? count - 1 : 0) : (activeSlice + step + count) % count);
    });
    document.querySelectorAll("[data-slice]").forEach(entry => {
        entry.addEventListener("click", () => showSlice(Number(entry.dataset.slice)));
    });

    const showAll = document.getElementById("show-all-expenses");
    if (showAll) {
        const extras = document.querySelectorAll(".recent-extra");
        extras.forEach(item => item.hidden = true);
        showAll.hidden = false;
        showAll.addEventListener("click", () => {
            const expanded = showAll.getAttribute("aria-expanded") !== "true";
            extras.forEach(item => item.hidden = !expanded);
            showAll.setAttribute("aria-expanded", String(expanded));
            showAll.textContent = expanded ? "Mostrar menos" : "Ver todos";
        });
    }
})();
