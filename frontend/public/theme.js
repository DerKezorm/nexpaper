// Before the first paint: light or dark from the last visit, so nothing flashes. Only a preview; the account's own
// choice replaces it as soon as the page knows it. Own file instead of an inline script, because the server's Content
// Security Policy only allows its own files.
try {
  var mode = localStorage.getItem('nexpaper.theme')
  var dark = mode === 'dark' || (mode !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  if (dark) {
    document.documentElement.setAttribute('data-theme', 'dark')
    document.querySelector('meta[name="theme-color"]').content = '#171310'
  }
} catch (e) {
  /* private mode without localStorage */
}
