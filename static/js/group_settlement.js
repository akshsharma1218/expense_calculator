(function () {
    document.querySelectorAll('[data-settlement-expenses]').forEach((fieldset) => {
        const checkboxes = [...fieldset.querySelectorAll('.settlement-expense-checkbox')];
        const count = fieldset.querySelector('[data-selected-count]');
        const total = fieldset.querySelector('[data-selected-total]');
        const selectAll = fieldset.querySelector('[data-select-all]');
        const selectNone = fieldset.querySelector('[data-select-none]');

        function updateSummary() {
            let selectedTotal = 0;
            let selectedCount = 0;

            checkboxes.forEach((checkbox) => {
                const option = checkbox.closest('.settlement-expense-option');
                option.classList.toggle('selected', checkbox.checked);
                if (checkbox.checked) {
                    selectedTotal += Number(checkbox.dataset.amount);
                    selectedCount += 1;
                }
            });

            count.textContent = String(selectedCount);
            total.textContent = `₹${selectedTotal.toFixed(2)}`;
        }

        checkboxes.forEach((checkbox) => {
            checkbox.addEventListener('change', updateSummary);
        });
        selectAll.addEventListener('click', () => {
            checkboxes.forEach((checkbox) => {
                checkbox.checked = true;
            });
            updateSummary();
        });
        selectNone.addEventListener('click', () => {
            checkboxes.forEach((checkbox) => {
                checkbox.checked = false;
            });
            updateSummary();
        });
        updateSummary();
    });
})();
