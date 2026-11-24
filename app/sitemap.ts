import type { MetadataRoute } from "next";

import { PUBLIC_SITEMAP_ROUTES, siteUrl } from "@/lib/site-seo";

export default function sitemap(): MetadataRoute.Sitemap {
  const base = siteUrl();
  return PUBLIC_SITEMAP_ROUTES.map((route) => ({
    url: `${base}${route.path === "/" ? "/" : route.path}`,
    changeFrequency: route.changeFrequency,
    priority: route.priority,
  }));
}
