document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector(".split-form");
    const groupSelect = document.getElementById("id_group");
    const modeSelect = document.getElementById("id_split_mode");
    const memberList = document.getElementById("splitMembers");
    const summary = document.getElementById("splitSummary");
    const memberData = JSON.parse(document.getElementById("split-group-members-data")?.textContent || "[]");
    const existingSplitData = JSON.parse(document.getElementById("existing-split-data")?.textContent || "[]");
    const groups = new Map(memberData.map((group) => [group.id, group.members]));
    if (!form || !groupSelect || !modeSelect || !memberList || !summary) return;

    const totalCents = Math.round(Number(form.dataset.transactionAmount) * 100);
    const currentUser = document.querySelector(".split-page")?.dataset.currentUser;
    const page = document.querySelector(".split-page");
    const editingSplit = page?.dataset.editingSplit === "true";
    const originalGroup = page?.dataset.originalGroup;
    const existingShares = new Map(
        existingSplitData.map((share) => [share.user_id, String(share.amount)])
    );
    const money = (cents) => `₹${(cents / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;

    function renderMembers() {
        const groupMembers = groups.get(groupSelect.value) || [];
        const custom = modeSelect.value === "custom";
        const members = custom
            ? groupMembers.filter((member) => member.id !== currentUser)
            : groupMembers;
        memberList.replaceChildren();
        if (!groupMembers.length) {
            summary.textContent = "Choose a group to see its members.";
            return;
        }
        if (custom && !members.length) {
            summary.textContent = "There are no other group members to owe a share.";
            summary.classList.add("is-invalid");
            return;
        }

        const base = Math.floor(totalCents / groupMembers.length);
        let remainder = totalCents % groupMembers.length;
        groupMembers.forEach((member) => {
            const shareCents = base + (remainder > 0 ? 1 : 0);
            if (remainder > 0) remainder -= 1;
            if (custom && member.id === currentUser) return;

            const row = document.createElement("div");
            row.className = "split-allocation-row";
            const identity = document.createElement("div");
            identity.className = "split-allocation-person";
            const name = document.createElement("strong");
            name.textContent = member.id === currentUser
                ? `${member.name} (you paid)`
                : member.name;

            if (custom) {
                const selected = document.createElement("input");
                selected.type = "checkbox";
                selected.name = "selected_members";
                selected.value = member.id;
                const hasExistingShares = editingSplit && groupSelect.value === originalGroup;
                selected.checked = hasExistingShares
                    ? existingShares.has(member.id)
                    : true;
                selected.className = "form-check-input";
                selected.setAttribute("aria-label", `Include ${member.name} in the split`);
                identity.append(selected);
            }
            identity.append(name);
            row.append(identity);
            const amount = document.createElement("span");
            amount.className = "split-equal-amount";
            amount.textContent = member.id === currentUser
                ? `Your share: ${money(shareCents)}`
                : `Owes ${money(shareCents)}`;
            row.append(amount);

            if (custom) {
                const customAmount = document.createElement("input");
                customAmount.type = "number";
                customAmount.min = "0.01";
                customAmount.step = "0.01";
                customAmount.inputMode = "decimal";
                customAmount.className = "form-control split-custom-amount";
                customAmount.name = `share_${member.id}`;
                customAmount.value = editingSplit
                    && groupSelect.value === originalGroup
                    && existingShares.has(member.id)
                    ? existingShares.get(member.id)
                    : (shareCents / 100).toFixed(2);
                customAmount.dataset.memberId = member.id;
                customAmount.setAttribute("aria-label", `Amount owed by ${member.name}`);
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
        const members = groups.get(groupSelect.value) || [];
        const inputs = Array.from(memberList.querySelectorAll(".split-custom-amount"));
        const selectedInputs = inputs.filter((input) => !input.disabled);
        const allocated = custom
            ? selectedInputs.reduce((sum, input) => sum + (Math.round(Number(input.value) * 100) || 0), 0)
            : totalCents;
        summary.textContent = custom
            ? `${money(allocated)} owed by ${selectedInputs.length} selected members; your share is ${money(totalCents - allocated)}.`
            : `You paid. Split equally among ${members.length} group members.`;
        summary.classList.toggle(
            "is-invalid",
            custom && (!selectedInputs.length || allocated > totalCents)
        );
    }

    groupSelect.addEventListener("change", renderMembers);
    modeSelect.addEventListener("change", renderMembers);
    form.addEventListener("submit", (event) => {
        if (!groupSelect.value || (modeSelect.value === "custom" && summary.classList.contains("is-invalid"))) {
            event.preventDefault();
            summary.focus?.();
        }
    });
    if (groupSelect.value) renderMembers();
});
