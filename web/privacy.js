const STORAGE_KEY = 'divledger.privacy-on';

export function isPrivacyShortcut(event) {
  return Boolean(
    event && (event.metaKey || event.ctrlKey) &&
    String(event.key || '').toLowerCase() === 'b'
  );
}

export function applyPrivacyMode(enabled, doc = document) {
  doc.body.classList.toggle('privacy-on', enabled);
  const button = doc.getElementById('privacy-toggle');
  if (!button) return;
  button.setAttribute('aria-pressed', String(enabled));
  button.textContent = enabled ? 'Cmd/Ctrl+B 显示' : 'Cmd/Ctrl+B 模糊';
  button.title = enabled ? '显示敏感文本' : '模糊敏感文本，方便截图';
}

export function installPrivacyMode(win = window, doc = document) {
  let enabled = false;
  try {
    enabled = win.sessionStorage.getItem(STORAGE_KEY) === '1';
  } catch {}

  const setEnabled = value => {
    enabled = Boolean(value);
    applyPrivacyMode(enabled, doc);
    try {
      win.sessionStorage.setItem(STORAGE_KEY, enabled ? '1' : '0');
    } catch {}
  };
  const toggle = () => setEnabled(!enabled);
  const button = doc.getElementById('privacy-toggle');
  if (button) button.addEventListener('click', toggle);
  win.addEventListener('keydown', event => {
    if (!isPrivacyShortcut(event)) return;
    event.preventDefault();
    toggle();
  });
  applyPrivacyMode(enabled, doc);
}
