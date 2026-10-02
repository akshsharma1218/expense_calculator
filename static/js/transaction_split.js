document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector(".split-form");
    const groupSelect = document.getElementById("id_group");
    const payerSelect = document.getElementById("id_paid_by");
    const modeSelect = document.getElementById("id_split_mode");
    const memberList = document.getElementById("splitMembers");
    const summary = document.getElementById("splitSummary");
    const memberData = JSON.parse(document.getElementById("split-group-members-data")?.textContent || "[]");
    const groups = new Map(memberData.map((group) => [group.id, group.members]));
    if (!form || !groupSelect || !payerSelect || !modeSelect || !memberList || !summary) return;

    const totalCents = Math.round(Number(form.dataset.transactionAmount) * 100);
    const money = (cents) => `₹${(cents / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;

    function renderMembers() {
        const members = groups.get(groupSelect.value) || [];
        memberList.replaceChildren();
        payerSelect.replaceChildren(new Option("Choose a payer", ""));
        members.forEach((member) => payerSelect.add(new Option(member.name, member.id)));
        const currentUser = document.querySelector(".split-page")?.dataset.currentUser;
        if (members.some((member) => member.id === currentUser)) payerSelect.value = currentUser;
        if (!members.length) {
            summary.textContent = "Choose a group to see its members.";
            return;
        }

        const base = Math.floor(totalCents / members.length);
        const remainder = totalCents % members.length;
        members.forEach((member, memberIndex) => {
            const row = document.createElement("div");
            row.className = "split-allocation-row";
            const identity = document.createElement("div");
            identity.className = "split-allocation-person";
            const name = document.createElement("strong");
            name.textContent = member.name;
            const shareCents = base + (memberIndex < remainder ? 1 : 0);

            if (modeSelect.value === "custom") {
                const selected = document.createElement("input");
                selected.type = "checkbox";
                selected.name = "selected_members";
                selected.value = member.id;
                selected.checked = true;
                selected.className = "form-check-input";
                selected.setAttribute("aria-label", `Include ${member.name} in the split`);
                identity.append(selected);
            }
            identity.append(name);
            row.append(identity);
            const amount = document.createElement("span");
            amount.className = "split-equal-amount";
            amount.textContent = money(shareCents);
            row.append(amount);

            if (modeSelect.value === "custom") {
                const customAmount = document.createElement("input");
                customAmount.type = "number";
                customAmount.min = "0.01";
                customAmount.step = "0.01";
                customAmount.inputMode = "decimal";
                customAmount.className = "form-control split-custom-amount";
                customAmount.name = `share_${member.id}`;
                customAmount.value = (shareCents / 100).toFixed(2);
                customAmount.dataset.memberId = member.id;
                customAmount.setAttribute("aria-label", `${member.name}'s share`);
                amount.remove();
                row.append(customAmount);
                customAmount.addEventListener("input", updateSummary);
                const selected = identity.querySelector('input[name="selected_members"]');
                selected.addEventListener("change", () => {
                    customAmount.disabled = !selected.checked;
                    updateSummary();
                });
            }
            memberList.append(row);
        });
        updateSummary();
    }

    function updateSummary() {
        const custom = modeSelect.value === "custom";
        const inputs = Array.from(memberList.querySelectorAll(".split-custom-amount"));
        const selectedInputs = inputs.filter((input) => !input.disabled);
        const allocated = custom
            ? selectedInputs.reduce((sum, input) => sum + (Math.round(Number(input.value) * 100) || 0), 0)
            : totalCents;
        summary.textContent = custom
            ? `${money(allocated)} of ${money(totalCents)} allocated to ${selectedInputs.length} selected members.`
            : `Split equally among ${(groups.get(groupSelect.value) || []).length} group members.`;
        summary.classList.toggle("is-invalid", custom && (!selectedInputs.length || allocated !== totalCents));
    }

    groupSelect.addEventListener("change", renderMembers);
    modeSelect.addEventListener("change", renderMembers);
    form.addEventListener("submit", (event) => {
        if (!groupSelect.value || !payerSelect.value || (modeSelect.value === "custom" && summary.classList.contains("is-invalid"))) {
            event.preventDefault();
            summary.focus?.();
        }
    });
    if (groupSelect.value) renderMembers();
});
