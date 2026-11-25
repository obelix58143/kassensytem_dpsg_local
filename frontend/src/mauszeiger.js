// Mauszeiger automatisch aus-/einblenden: bei Touch verschwindet er,
// sobald Maus oder Trackpad bewegt werden, ist er wieder da.
// (Laptops mit Touchscreen: sonst steht der Zeiger mitten auf der Kasse.)
export function mauszeigerAutomatik(root = document.documentElement) {
  const aus = () => root.classList.add('zeiger-aus')
  const an = () => root.classList.remove('zeiger-aus')

  // Geräte mit Touchscreen starten ohne Zeiger
  if (window.matchMedia && window.matchMedia('(any-pointer: coarse)').matches) aus()

  if (window.PointerEvent) {
    window.addEventListener('pointerdown', (e) => { if (e.pointerType === 'touch' || e.pointerType === 'pen') aus() }, true)
    window.addEventListener('pointermove', (e) => { if (e.pointerType === 'mouse') an() }, true)
  } else {
    // Alte Browser (Chrome < 55): Touch-Ereignisse lösen danach künstliche Mausereignisse aus – die ignorieren
    let letzterTouch = 0
    window.addEventListener('touchstart', () => { letzterTouch = Date.now(); aus() }, true)
    window.addEventListener('mousemove', () => { if (Date.now() - letzterTouch > 1000) an() }, true)
  }
}
