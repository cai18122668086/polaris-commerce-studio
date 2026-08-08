export const IMAGE_UPLOAD_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"] as const;

export const IMAGE_UPLOAD_MIME_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;

export const IMAGE_UPLOAD_ACCEPT = [
  ...IMAGE_UPLOAD_EXTENSIONS,
  ...IMAGE_UPLOAD_MIME_TYPES,
].join(",");

export const IMAGE_UPLOAD_FORMAT_HINT = "支持 JPG/JPEG、PNG 和 WebP 图片";
