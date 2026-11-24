/* 站点子路径（next.config 的 basePath，来自 POLARIS_BASE_PATH）。
   正式环境部署在根路径，这里为空，所有地址原样返回；开发预览挂在 /site 下时，
   public 目录里的静态资源（/images、/polaris-mark*.svg 等）要带上这个前缀，否则会 404。
   Next 和 vinext 都会在构建时把 process.env.__NEXT_ROUTER_BASEPATH 换成配置值。 */

export const BASE_PATH = (process.env.__NEXT_ROUTER_BASEPATH || "").replace(/\/+$/, "");

/** withBasePath("/images/a.webp") → "/site/images/a.webp"（无子路径时原样返回；已带前缀、外链和相对地址不动） */
export function withBasePath(path: string, base = BASE_PATH): string {
  if (!base || !path.startsWith("/") || path.startsWith("//")) return path;
  if (path === base || path.startsWith(`${base}/`)) return path;
  return `${base}${path}`;
}

/** srcset 里的每个地址都加上子路径 */
export function withBasePathSrcSet(srcSet: string, base = BASE_PATH): string {
  return srcSet.split(",").map(part => {
    const [url, ...rest] = part.trim().split(/\s+/);
    return [withBasePath(url, base), ...rest].join(" ");
  }).join(", ");
}
