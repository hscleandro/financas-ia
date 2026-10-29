(() => {
    "use strict";

    const accountMenu = document.getElementById("account-menu");
    if (!accountMenu) return;

    document.addEventListener("click", event => {
        if (!accountMenu.contains(event.target)) accountMenu.open = false;
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && accountMenu.open) {
            accountMenu.open = false;
            accountMenu.querySelector("summary").focus();
        }
    });
})();
