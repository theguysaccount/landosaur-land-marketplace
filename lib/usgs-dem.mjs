import { fromUrl } from "geotiff";

const USGS_DEM_ROOT = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation";
const METERS_PER_FOOT = 0.3048;

function tileFor(latitude, longitude) {
  const north = Math.ceil(latitude);
  const west = Math.floor(longitude);
  return `${north < 0 ? "s" : "n"}${String(Math.abs(north)).padStart(2, "0")}` +
    `${west < 0 ? "w" : "e"}${String(Math.abs(west)).padStart(3, "0")}`;
}

async function sampleTile(tile, points, resolution, signal) {
  const url = `${USGS_DEM_ROOT}/${resolution}/TIFF/current/${tile}/USGS_${resolution}_${tile}.tif`;
  const tiff = await fromUrl(url, { allowFullFile: false }, signal);
  const image = await tiff.getImage();
  const crs = image.getGeoKeys()?.GeographicTypeGeoKey;
  if (crs !== 4269 && crs !== 4326) return {};
  const [west, north] = image.getOrigin();
  const [pixelWidth, pixelHeight] = image.getResolution();
  const pixelIndex = image.pixelIsArea() ? Math.floor : Math.round;
  const pixels = points.map(([key, lat, lon]) => [key,
    pixelIndex((lon - west) / pixelWidth), pixelIndex((lat - north) / pixelHeight),
  ]).filter(([, col, row]) => col >= 0 && row >= 0 && col < image.getWidth() && row < image.getHeight());
  if (!pixels.length) return {};

  const left = Math.min(...pixels.map(([, col]) => col));
  const top = Math.min(...pixels.map(([, , row]) => row));
  const right = 1 + Math.max(...pixels.map(([, col]) => col));
  const bottom = 1 + Math.max(...pixels.map(([, , row]) => row));
  const raster = await image.readRasters({ window: [left, top, right, bottom], samples: [0], interleave: true, signal });
  const noData = image.getGDALNoData();
  const samples = {};
  for (const [key, col, row] of pixels) {
    const meters = raster[(row - top) * raster.width + col - left];
    if (Number.isFinite(meters) && meters !== noData && meters > -420 && meters < 9200) {
      samples[key] = meters / METERS_PER_FOOT;
    }
  }
  return samples;
}

export async function sampleUsgsDem(points) {
  const tiles = new Map();
  for (const [key, lat, lon] of points) {
    const longitude = lon < -180 ? lon + 360 : lon >= 180 ? lon - 360 : lon;
    const tile = tileFor(lat, longitude);
    if (!tiles.has(tile)) tiles.set(tile, []);
    tiles.get(tile).push([key, lat, longitude]);
  }

  const signal = AbortSignal.timeout(7000);
  for (const [resolution, seconds] of [["13", "1/3"], ["1", "1"]]) {
    const requests = [...tiles].map(([tile, locations]) => sampleTile(tile, locations, resolution, signal));
    const results = await Promise.allSettled(requests);
    const samples = Object.assign({}, ...results.filter((result) => result.status === "fulfilled").map((result) => result.value));
    if (samples.c != null) return { samples, seconds };
    if (signal.aborted) break;
  }
  return null;
}
