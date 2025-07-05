//VERSION=3
const viz = new ColorRampVisualizer([
  [-0.8,   0x800000],
  [-0.24,  0xff0000],
  [-0.032, 0xffff00],
  [0.032,  0x00ffff],
  [0.24,   0x0000ff],
  [0.8,    0x000080]
]);

function setup() {
  return {
    input: [{
      bands: [
        "B01","B02","B03","B04","B05","B06",
        "B07","B08","B8A","B09","B11","B12"
      ],
      units: [
        "DN","DN","DN","DN","DN","DN","DN","DN",
        "REFLECTANCE", // B8A
        "DN",
        "REFLECTANCE", // B11
        "DN"
      ]
    }],
    output: {
      bands:      15,                 // 12 raw DN + 3 NDMI-RGB
      sampleType: SampleType.UINT16
    }
  };
}

function evaluatePixel(s) {
  // 1) recover the 12 raw DN bands:
  //    for everything except B8A/B11, s.<band> is already DN
  //    for B8A and B11, s.<band> is reflectance → multiply by 10000
  const rawDN = [
    s.B01, s.B02, s.B03, s.B04,
    s.B05, s.B06, s.B07, s.B08,
    Math.round(s.B8A * 10000),  // back to DN
    s.B09,
    Math.round(s.B11 * 10000),  // back to DN
    s.B12
  ];

  // 2) compute NDMI on true reflectance
  const ndmi = index(s.B8A, s.B11);

  // 3) look up the exact same 0–255 ramp colours
  const rgb8 = viz.process(ndmi).slice(0, 3);

  // 4) stretch 8-bit → 16-bit for preview
  const rgb16 = rgb8.map(v => v * 257);

  // 5) return raw DN bands + NDMI-RGB
  return rawDN.concat(rgb16);
}
