const nameInput = document.querySelector('[data-msf-id="customer/form/name"]');
const typeSelect = document.querySelector('[data-msf-id="customer/form/type"]');
const notifications = document.querySelector('[data-msf-id="customer/form/notifications"]');
const saveButton = document.querySelector('[data-msf-id="customer/form/save"]');
const status = document.querySelector('[data-msf-id="customer/form/status"]');
const validation = document.querySelector('[data-msf-id="customer/form/validation/name"]');
const details = document.querySelector('[data-msf-id="customer/form/details"]');

function setState(element, state) {
  element.dataset.msfState = state;
}

nameInput.addEventListener('input', () => setState(nameInput, nameInput.value ? 'populated' : 'empty'));
typeSelect.addEventListener('change', () => setState(typeSelect, typeSelect.value ? 'selected' : 'unselected'));
notifications.addEventListener('change', () => setState(notifications, notifications.checked ? 'checked' : 'unchecked'));

details.addEventListener('click', () => {
  const expanded = details.getAttribute('aria-expanded') === 'true';
  details.setAttribute('aria-expanded', String(!expanded));
  details.querySelector('span').textContent = expanded ? '+' : '-';
  setState(details, expanded ? 'collapsed' : 'expanded');
  setState(document.querySelector('[data-msf-id="customer/form/panel"]'), expanded ? 'collapsed' : 'expanded');
});

document.querySelectorAll('[data-msf-id^="customer/navigation/"]').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('[data-msf-id^="customer/navigation/"]').forEach((item) => setState(item, 'inactive'));
    setState(tab, 'active');
    document.querySelectorAll('.tab').forEach((item) => item.classList.toggle('active', item === tab));
  });
});

saveButton.addEventListener('click', () => {
  if (!nameInput.value.trim()) {
    setState(validation, 'error');
    validation.textContent = 'Name is required.';
    setState(status, 'error');
    status.textContent = 'Please fix the highlighted field.';
    return;
  }

  setState(validation, 'clear');
  validation.textContent = '';
  saveButton.disabled = true;
  setState(saveButton, 'disabled');
  setState(status, 'saving');
  status.textContent = 'Saving...';

  window.setTimeout(() => {
    setState(status, 'saved');
    status.textContent = 'Customer saved.';
    saveButton.disabled = false;
    setState(saveButton, 'enabled');
  }, 500);
});
