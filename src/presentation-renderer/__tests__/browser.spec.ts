import { afterAll, describe, expect, it } from 'vitest';

// Drives a real browser: run with CHROMIUM_PATH set, e.g. on macOS
// CHROMIUM_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
const { capture, closeBrowser } = await import('../src/capture.js');

const deck = `<!doctype html><html><head><title>Deck</title><style>
  body{margin:0;font:40px sans-serif}.s{display:none;height:100vh;place-items:center}.s.on{display:grid}
</style></head><body>
<div class="s on" style="background:#123;color:#fff">One</div>
<div class="s" style="background:#fff">Two</div>
<div class="s" style="background:#c33">Three</div>
<script>
  let i = 0; const s = document.querySelectorAll('.s');
  addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' || i === s.length - 1) return;
    s[i].classList.remove('on'); s[++i].classList.add('on');
  });
  fetch('http://backend:8000/api/v1.0/users/me/').then(() => document.title = 'LEAK', () => {});
</script></body></html>`;

describe.skipIf(!process.env.CHROMIUM_PATH)('capture, in a real browser', () => {
  afterAll(closeBrowser);

  it('steps through the slides, one picture each', async () => {
    const captured = await capture(deck);
    expect(captured.kind).toBe('slides');
    expect(captured.kind === 'slides' && captured.slides.length).toBe(3);
  });

  it('captures once a page that keeps changing on its own', async () => {
    const playing = `<body style="margin:0;font:60px sans-serif"><div id="t">0</div>
      <script>let n=0;setInterval(()=>{document.getElementById('t').textContent=++n},50)</script></body>`;
    const captured = await capture(playing);
    expect(captured.kind === 'slides' && captured.slides.length).toBe(1);
  });

  it('pictures a slide whole, through a CSS transition', async () => {
    const fading = deck.replace(
      '.s.on{display:grid}',
      '.s.on{display:grid;animation:fade 2s}@keyframes fade{from{opacity:0}to{opacity:1}}',
    );
    const captured = await capture(fading);
    expect(captured.kind === 'slides' && captured.slides.length).toBe(3);
  });

  it('prints a presentation whose slides are one below the other', async () => {
    const tall = `<body style="margin:0">${['a', 'b', 'c']
      .map((x) => `<section style="height:720px;font:60px serif">${x}</section>`)
      .join('')}</body>`;
    const captured = await capture(tall);
    expect(captured.kind).toBe('pdf');
  });
});
