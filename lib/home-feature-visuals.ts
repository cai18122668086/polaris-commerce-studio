export type HomeFeatureImage = {
  src: string;
  width: number;
  height: number;
};

type BeforeAfterVisual = {
  kind: "wipe" | "background" | "amazon";
  before: HomeFeatureImage;
  after: HomeFeatureImage;
};

type RemixVisual = {
  kind: "remix";
  before: HomeFeatureImage;
  after: HomeFeatureImage;
  reference: HomeFeatureImage;
};

type DetailVisual = {
  kind: "detail-scroll";
  before: HomeFeatureImage;
  after: HomeFeatureImage;
  reducedMotionCover: HomeFeatureImage;
};

export type HomeFeatureVisual =
  | BeforeAfterVisual
  | RemixVisual
  | DetailVisual;

const square = (file: string): HomeFeatureImage => ({
  src: `/images/homepage-features/${file}`,
  width: 640,
  height: 640,
});

export const HOME_FEATURE_VISUALS: Readonly<Record<string, HomeFeatureVisual>> = {
  "local-edit": {
    kind: "wipe",
    before: square("card-01-local-edit-before-v1.webp"),
    after: square("card-01-local-edit-after-v1.webp"),
  },
  "change-background": {
    kind: "background",
    before: square("card-02-background-before-v1.webp"),
    after: square("card-02-background-after-v1.webp"),
  },
  "reference-remix": {
    kind: "remix",
    before: square("card-03-remix-before-v1.webp"),
    after: square("card-03-remix-result-serum-landscape-v1.png"),
    reference: square("card-03-remix-reference-v1.webp"),
  },
  "detail-pack": {
    kind: "detail-scroll",
    before: square("card-04-detail-before-v1.webp"),
    after: {
      src: "/images/homepage-features/card-04-detail-after-long-v1.webp",
      width: 720,
      height: 960,
    },
    reducedMotionCover: square("card-04-detail-after-cover-v1.webp"),
  },
  "amazon-visual-suite": {
    kind: "amazon",
    before: square("card-05-amazon-before-v1.webp"),
    after: square("card-05-amazon-hero-v2.png"),
  },
};

