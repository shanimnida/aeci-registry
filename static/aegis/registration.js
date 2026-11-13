(() => {
    "use strict";
    const form = document.getElementById("registration-form");
    if (!form) return;
    const summary = document.getElementById("form-errors");
    if (summary) summary.focus();
    const rows = document.getElementById("children-rows");
    const total = document.getElementById("id_children-TOTAL_FORMS");
    const add = document.getElementById("add-child");
    const template = document.getElementById("child-template");
    function updateChildren() {
        const items = [...rows.querySelectorAll(".child-row")];
        items.forEach((row, i) => {
            row.querySelector("[data-child-number]").textContent = i + 1;
            row.querySelector("[data-remove-child]").hidden = false;
            row.querySelectorAll("input,label,small,ul").forEach(element => {
                ["id", "name", "for", "aria-describedby"].forEach(attribute => {
                    if (element.hasAttribute(attribute)) element.setAttribute(attribute, element.getAttribute(attribute).replace(/children-(?:\d+|__prefix__)-/g, `children-${i}-`));
                });
            });
        });
        total.value = items.length;
        add.hidden = false;
        add.disabled = items.length >= 10;
        document.getElementById("child-limit").textContent = items.length >= 10 ? "Ten children listed. For additional details, use the notes box or speak to the Secretariat." : "";
    }
    rows.addEventListener("click", event => {
        const button = event.target.closest("[data-remove-child]");
        if (button) { button.closest(".child-row").remove(); updateChildren(); }
    });
    add.addEventListener("click", () => {
        if (rows.querySelectorAll(".child-row").length >= 10) return;
        rows.appendChild(template.content.cloneNode(true));
        updateChildren();
        rows.lastElementChild.querySelector("input").focus();
    });
    updateChildren();
    const committees = [...form.querySelectorAll('input[name="committees"]')];
    const count = document.getElementById("committee-count");
    function countCommittees() {
        const selected = committees.filter(input => input.checked).length;
        count.textContent = `${selected} of 2 selected`;
        committees.forEach(input => { input.disabled = selected >= 2 && !input.checked; });
    }
    committees.forEach(input => input.addEventListener("change", countCommittees));
    countCommittees();
    const check = document.getElementById("check-record");
    const result = document.getElementById("record-check-result");
    check.hidden = false;
    check.addEventListener("click", async () => {
        const data = new FormData();
        ["submission_token", "csrfmiddlewaretoken", "first_name", "last_name", "middle_name", "suffix", "date_of_birth"].forEach(name => data.append(name, form.elements[name].value));
        if (form.elements.consent_given.checked) data.append("consent_given", "on");
        data.append("action", "check_record");
        check.disabled = true;
        result.textContent = "Checking your details…";
        result.dataset.state = "checking";
        try {
            const response = await fetch(form.action, { method: "POST", body: data, credentials: "same-origin", headers: { "Accept": "application/json" } });
            const body = await response.json();
            result.textContent = body.message || "We could not complete the check. Please try again.";
            result.dataset.state = body.status || "error";
        } catch (_) {
            result.textContent = "We could not complete the check. Your entered details are still here; please try again.";
            result.dataset.state = "error";
        } finally { check.disabled = false; }
    });
    ["first_name", "last_name", "middle_name", "suffix", "date_of_birth"].forEach(name => form.elements[name].addEventListener("input", () => { result.textContent = ""; delete result.dataset.state; }));
    form.addEventListener("submit", () => {
        // Native validation runs before submit. Preserve every entered value
        // while preventing repeated clicks; the server also enforces idempotency.
        const submit = document.getElementById("submit-registration");
        submit.disabled = true;
        submit.textContent = "Sending registration…";
    });
    window.addEventListener("pageshow", () => {
        const submit = document.getElementById("submit-registration");
        submit.disabled = false;
        submit.textContent = "Send registration →";
    });
})();
