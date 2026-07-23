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
        if (!e.target.classList.contains("remove-row")) {
            return;
        }

        const activeRows = getActiveRows();
        if (activeRows.length === 1) {
            alert("At least one item is required.");
            return;
        }

        const row = e.target.closest(".item-row");
        const deleteInput = row.querySelector('[name$="-DELETE"]');
        const idInput = row.querySelector('[name$="-id"]');

        if (idInput && idInput.value) {
            if (deleteInput) {
                deleteInput.checked = true;
            }
            row.classList.add("marked-delete");
            row.style.display = "none";
        } else {
            row.remove();
            reindexForms();
        }

        calculateTotal();
    });

    tbody.addEventListener("input", calculateTotal);
    function getActiveRows() {
        return Array.from(tbody.querySelectorAll(".item-row")).filter(
            (row) => !row.classList.contains("marked-delete")
        );
    }

    function calculateTotal() {
        let grandTotal = 0;
        getActiveRows().forEach((row) => {
            const qty = parseFloat(row.querySelector('[name$="quantity"]')?.value) || 0;
            const price = parseFloat(row.querySelector('[name$="unit_price"]')?.value) || 0;
            const total = qty * price;
            const totalEl = row.querySelector(".row-total");
            if (totalEl) {
                totalEl.innerText = "₹" + total.toFixed(2);
            }
            grandTotal += total;
        });
        const grandTotalEl = document.getElementById("grand-total");
        if (grandTotalEl) {
            grandTotalEl.innerText = grandTotal.toFixed(2);
        }
    }

    function reindexForms() {
        const rows = tbody.querySelectorAll(".item-row");
        rows.forEach((row, index) => {
            row.querySelectorAll("input, select, textarea").forEach((field) => {
                if (field.name) {
                    field.name = field.name.replace(/items-\d+-/, `items-${index}-`);
                }
                if (field.id) {
                    field.id = field.id.replace(/id_items-\d+-/, `id_items-${index}-`);
                }
            });
        });
        totalForms.value = rows.length;
    }

    function submitForm(e) {
        const form = e.target.closest("form");
        console.log("Form found:", form);
        if (form) {
            const rows = getActiveRows();
            let totalAmount = document.getElementById("id_amount")?.value;
            console.log("Total Amount:", totalAmount);
            if(rows.length === 1) {
                let row = rows[0];
                row.querySelectorAll("input, select, textarea").forEach((field) => {
                    if (field.name && field.name.endsWith("-name") && !field.value) {
                        field.value = "Item";
                    }
                    else if (field.name && field.name.endsWith("-quantity") && !field.value) {
                        field.value = 1;
                    }
                    else if (field.name && field.name.endsWith("-unit_price") && !field.value) {
                        field.value = Number(totalAmount);
                    }
                    else if (field.name && field.name.endsWith("-total_price") && !field.value) {
                        field.value = Number(totalAmount);
                    }
                });
            }
            setTimeout(() => {
                form.submit();
            }, 10000);
        }
    }

    window.submitForm = submitForm;

    calculateTotal();
});
