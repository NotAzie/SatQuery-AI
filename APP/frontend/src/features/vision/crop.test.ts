import { describe, expect, it } from "vitest";

import { scaleCropToImage } from "./crop";

describe("Earth capture pixel crop", () => {
  it("scales a displayed selection into source-image pixels", () => {
    expect(
      scaleCropToImage(
        { left: 10, top: 5, width: 40, height: 25 },
        { width: 100, height: 50 },
        { width: 1000, height: 500 },
      ),
    ).toEqual({ left: 100, top: 50, width: 400, height: 250 });
  });

  it("rounds outward and keeps the crop inside the source image", () => {
    expect(
      scaleCropToImage(
        { left: 1, top: 1, width: 2, height: 2 },
        { width: 3, height: 3 },
        { width: 10, height: 10 },
      ),
    ).toEqual({ left: 3, top: 3, width: 7, height: 7 });
  });

  it("rejects empty or out-of-viewport selections", () => {
    expect(
      scaleCropToImage(
        { left: 0, top: 0, width: 0, height: 5 },
        { width: 100, height: 100 },
        { width: 200, height: 200 },
      ),
    ).toBeNull();
    expect(
      scaleCropToImage(
        { left: 90, top: 0, width: 20, height: 5 },
        { width: 100, height: 100 },
        { width: 200, height: 200 },
      ),
    ).toBeNull();
    expect(
      scaleCropToImage(
        { left: Number.NaN, top: 0, width: 10, height: 10 },
        { width: 100, height: 100 },
        { width: 200, height: 200 },
      ),
    ).toBeNull();
  });
});
