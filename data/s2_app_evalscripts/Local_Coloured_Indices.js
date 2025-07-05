//VERSION=3
const gain = 2.5;              // brightness
const viz  = new ColorRampVisualizer([
  [-0.8 , 0x800000], [-0.24, 0xff0000], [-0.032,0xffff00],
  [0.032, 0x00ffff], [0.24 , 0x0000ff], [0.8,  0x000080]
]);

function setup () {
  return {
    input : [{bands:["B01","B02","B03","B04","B05","B06",
                     "B07","B08","B8A","B09","B11","B12"],
              units:"DN"}],
    output: {bands: 15, sampleType: SampleType.UINT16}
  };
}

function evaluatePixel (s) {
  const raw = [s.B01,s.B02,s.B03,s.B04,s.B05,s.B06,
               s.B07,s.B08,s.B8A,s.B09,s.B11,s.B12];

  // 0-255 → 0-65 535 × gain   (255*257 = 65535)
  const rgb8  = viz.process(index(s.B8A, s.B11)).slice(0,3);
  const rgb16 = rgb8.map(v => Math.min(65535, v*257*gain));

  return raw.concat(rgb16);
}
