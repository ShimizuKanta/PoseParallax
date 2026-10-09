import english from './locales/en.json';
export type Language = 'ja' | 'en';
const messages: Record<string, string> = english;
export let language: Language = 'ja';
try { language = localStorage.getItem('pose-language') === 'en' ? 'en' : 'ja'; } catch { /* Storage can be unavailable in private browsers. */ }
const requestedLanguage = new URLSearchParams(location.search).get('lang');
if (requestedLanguage === 'ja' || requestedLanguage === 'en') {
  language = requestedLanguage;
  try { localStorage.setItem('pose-language', language); } catch { /* Keep the session preference. */ }
}
export function t(source: string, values: Record<string, string | number> = {}): string {
  return (language === 'en' ? messages[source] ?? source : source).replace(/\{(\w+)\}/g, (match, key) => String(values[key] ?? match));
}
const literal = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
function translateText(value: string, previous: Language): string {
  const trimmed = value.trim();
  for (const [ja, en] of Object.entries(messages)) {
    const from = previous === 'ja' ? ja : en;
    const to = language === 'ja' ? ja : en;
    if (trimmed === from.trim()) return value.replace(trimmed, to.trim());
    if (!from.includes('{')) continue;
    const keys: string[] = [];
    const pattern = from.split(/(\{\w+\})/).map(part => {
      if (part.startsWith('{')) { keys.push(part.slice(1, -1)); return '(.+?)'; }
      return literal(part);
    }).join('');
    const match = new RegExp(`^${pattern}$`).exec(trimmed);
    if (match) return value.replace(trimmed, to.replace(/\{(\w+)\}/g, (_, key) => match[keys.indexOf(key) + 1]));
  }
  return value;
}
export function setLanguage(next: Language) {
  const previous = language;
  language = next;
  try { localStorage.setItem('pose-language', next); } catch { /* Preference remains available for this session. */ }
  document.documentElement.lang = next;
  // Update existing nodes rather than rebuilding a live video, worker or 3D canvas.
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    if (node.parentElement?.closest('[data-user-content], script, style, option[data-language]')) continue;
    const translated = translateText(node.data, previous);
    if (translated !== node.data) node.data = translated;
  }
  document.querySelectorAll('[placeholder], [aria-label]').forEach(element => {
    for (const attribute of ['placeholder', 'aria-label']) {
      const value = element.getAttribute(attribute);
      if (value !== null) element.setAttribute(attribute, translateText(value, previous));
    }
  });
}
document.documentElement.lang = language;
