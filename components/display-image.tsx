import type { ComponentProps } from "react";
import manifest from "@/lib/display-images.json";
import { BASE_PATH, withBasePath, withBasePathSrcSet } from "@/lib/base-path";

const images: Record<string, {src:string;srcSet:string}> = manifest;

/** Only registered public showcase art has derivatives. User assets and
 * download URLs always retain the original source and bytes. */
export function DisplayImage({src, alt = "", sizes = "(max-width: 640px) 50vw, (max-width: 1199px) 33vw, 480px", srcSet, ...props}: Omit<ComponentProps<"img">,"src"> & {src:string}) {
  // 展示图清单按根路径登记；站点挂在子路径下时，src 可能已带前缀，查表前去掉，输出时再统一补上。
  const display = images[BASE_PATH && src.startsWith(`${BASE_PATH}/`) ? src.slice(BASE_PATH.length) : src];
  return <img {...props} alt={alt} src={withBasePath(display ? display.src : src)} srcSet={srcSet ?? (display ? withBasePathSrcSet(display.srcSet) : undefined)} sizes={display ? sizes : undefined} decoding={props.decoding ?? "async"}/>;
}
