// Ambil warna dominan dari cover album (dipakai overlay kartu & lirik).
window.SNPColor = (() => {
  function rgbToHsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
    if (max === min) return [0, 0, l];
    const d = max - min, s = l > .5 ? d / (2 - max - min) : d / (max + min);
    const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h * 60, s, l];
  }

  const hsl = (h, s, l, a = 1) =>
    `hsl(${h.toFixed(0)} ${(s * 100).toFixed(0)}% ${(l * 100).toFixed(0)}% / ${a})`;

  function hexToHsl(hex) {
    const n = parseInt(String(hex).replace("#", ""), 16) || 0;
    return rgbToHsl(n >> 16 & 255, n >> 8 & 255, n & 255);
  }

  /** Warna dominan yang "berwarna", disesuaikan supaya teks putih & gelap sama-sama terbaca. */
  function dominant(img) {
    const c = document.createElement("canvas");
    c.width = c.height = 40;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, 40, 40);
    const px = ctx.getImageData(0, 0, 40, 40).data;
    const buckets = new Map();
    const all = [0, 0, 0, 0];
    for (let i = 0; i < px.length; i += 4) {
      const [h, s, l] = rgbToHsl(px[i], px[i + 1], px[i + 2]);
      all[0] += px[i]; all[1] += px[i + 1]; all[2] += px[i + 2]; all[3]++;
      if (l < .12 || l > .9 || s < .18) continue;       // abaikan hitam/putih/abu
      const key = Math.round(h / 24);                     // 15 kelompok hue
      const b = buckets.get(key) || { w: 0, h: 0, s: 0, l: 0 };
      const w = s * (1 - Math.abs(l - .5));               // utamakan warna kuat & mid-tone
      b.w += w; b.h += h * w; b.s += s * w; b.l += l * w;
      buckets.set(key, b);
    }
    let best = null;
    for (const b of buckets.values()) if (!best || b.w > best.w) best = b;
    let h, s, l;
    if (best && best.w > 6) { h = best.h / best.w; s = best.s / best.w; l = best.l / best.w; }
    else { [h, s, l] = rgbToHsl(all[0] / all[3], all[1] / all[3], all[2] / all[3]); s = Math.min(s, .15); }
    s = s < .15 ? s : Math.min(.72, Math.max(.35, s));
    l = Math.min(.44, Math.max(.32, l));
    return [h, s, l];
  }

  return { rgbToHsl, hsl, hexToHsl, dominant };
})();
