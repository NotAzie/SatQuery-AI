import fs from 'node:fs';
import path from 'node:path';

let eccodesPromise = null;
let eccodesSupported = null;

function checkWasmSupport() {
  if (eccodesSupported !== null) return eccodesSupported;
  try {
    const candidatePath = path.resolve(
      process.cwd(),
      'node_modules/@meri-imperiumi/eccodes-wasm/build/eccodes/eccodes.wasm',
    );
    if (fs.existsSync(candidatePath)) {
      eccodesSupported = WebAssembly.validate(fs.readFileSync(candidatePath));
      return eccodesSupported;
    }
  } catch {
    eccodesSupported = false;
  }
  eccodesSupported = false;
  return eccodesSupported;
}

function loadEccodes() {
  if (!checkWasmSupport()) {
    throw new Error('WebAssembly ecCodes binary is incompatible with current runtime');
  }
  eccodesPromise ??= import('@meri-imperiumi/eccodes-wasm')
    .then((module) => module.createEccodes())
    .catch((error) => {
      eccodesPromise = null;
      throw error;
    });
  return eccodesPromise;
}

export async function decodeWindGribMessage(buffer, { eccodesModule } = {}) {
  if (buffer.byteLength > 8 * 1024 * 1024) {
    throw new Error('Wind GRIB exceeds byte budget');
  }
  const eccodes = eccodesModule ?? (await loadEccodes());
  const file = '/gev-wind.grib2';
  let handle = null;
  try {
    eccodes.writeFile(file, buffer);
    handle = eccodes.openGrib(file);
    const ni = handle.getLong('Ni');
    const nj = handle.getLong('Nj');
    if (
      !Number.isInteger(ni) ||
      !Number.isInteger(nj) ||
      ni < 1 ||
      nj < 1 ||
      ni * nj > 2_000_000
    ) {
      throw new Error('Invalid wind GRIB geometry');
    }
    return {
      ni,
      nj,
      lo1: handle.getDouble('longitudeOfFirstGridPointInDegrees'),
      la1: handle.getDouble('latitudeOfFirstGridPointInDegrees'),
      di: handle.getDouble('iDirectionIncrementInDegrees'),
      dj: handle.getDouble('jDirectionIncrementInDegrees'),
      values: handle.getDoubleArray('values'),
      shortName: handle.getString('shortName'),
      level: handle.getLong('level'),
      units: handle.getString('units'),
    };
  } finally {
    handle?.delete();
    eccodes.writeFile(file, new Uint8Array(0));
  }
}
