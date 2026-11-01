export interface PixelCrop {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface DisplaySize {
  width: number;
  height: number;
}

export function scaleCropToImage(
  selection: PixelCrop,
  display: DisplaySize,
  image: DisplaySize,
): PixelCrop | null {
  if (
    !Number.isFinite(display.width) ||
    !Number.isFinite(display.height) ||
    !Number.isFinite(image.width) ||
    !Number.isFinite(image.height) ||
    !Number.isFinite(selection.left) ||
    !Number.isFinite(selection.top) ||
    !Number.isFinite(selection.width) ||
    !Number.isFinite(selection.height) ||
    display.width <= 0 ||
    display.height <= 0 ||
    image.width <= 0 ||
    image.height <= 0 ||
    selection.left < 0 ||
    selection.top < 0 ||
    selection.width <= 0 ||
    selection.height <= 0 ||
    selection.left + selection.width > display.width ||
    selection.top + selection.height > display.height
  ) {
    return null;
  }
  const left = Math.floor((selection.left / display.width) * image.width);
  const top = Math.floor((selection.top / display.height) * image.height);
  const right = Math.min(
    image.width,
    Math.ceil(((selection.left + selection.width) / display.width) * image.width),
  );
  const bottom = Math.min(
    image.height,
    Math.ceil(((selection.top + selection.height) / display.height) * image.height),
  );
  if (right <= left || bottom <= top) return null;
  return { left, top, width: right - left, height: bottom - top };
}
