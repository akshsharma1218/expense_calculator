document.addEventListener("DOMContentLoaded", function () {
    const totalForms = document.getElementById("id_items-TOTAL_FORMS");
    const tbody = document.getElementById("items-body");
    const template = document.getElementById("empty-form");
    const addBtn = document.getElementById("add-item-btn");

    if (!totalForms || !tbody || !template || !addBtn) {
        return;
    }

    addBtn.addEventListener("click", function () {
        let index = parseInt(totalForms.value, 10) || 0;
        let html = template.content.firstElementChild.outerHTML.replace(/__prefix__/g, index);
        tbody.insertAdjacentHTML("beforeend", html);
        totalForms.value = index + 1;
        calculateTotal();
    });

    tbody.addEventListener("click", function (e) {
        if (e.target.classList.contains("remove-row")) {
            const rows = tbody.querySelectorAll(".item-row");
            if (rows.length === 1) {
                alert("At least one item is required.");
                return;
            }
            e.target.closest(".item-row").remove();
            reindexForms();
            calculateTotal();
        }
    });

    tbody.addEventListener("input", calculateTotal);

    function calculateTotal() {
        let grandTotal = 0;
        document.querySelectorAll(".item-row").forEach(row => {
            const qty = parseFloat(row.querySelector('[name$="quantity"]')?.value) || 0;
            const price = parseFloat(row.querySelector('[name$="unit_price"]')?.value) || 0;
            const total = qty * price;
            row.querySelector(".row-total").innerText = "₹" + total.toFixed(2);
            grandTotal += total;
        });
        document.getElementById("grand-total").innerText = grandTotal.toFixed(2);
    }

    function reindexForms() {
        const rows = tbody.querySelectorAll(".item-row");
        rows.forEach((row, index) => {
            row.querySelectorAll("input, select, textarea").forEach(field => {
                if (field.name) field.name = field.name.replace(/items-\d+-/, `items-${index}-`);
                if (field.id) field.id = field.id.replace(/id_items-\d+-/, `id_items-${index}-`);
            });
        });
        totalForms.value = rows.length;
    }

    calculateTotal();
});