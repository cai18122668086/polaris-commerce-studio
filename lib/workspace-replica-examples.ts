import { withBasePath } from "./base-path";
/** Original input, reference and output files from completed website history. */
export const WORKSPACE_REPLICA_EXAMPLES = {
  "exact": {
    "product": {
      "src": withBasePath("/images/cases/olay-20261030/product-01.webp"),
      "width": 720,
      "height": 960
    },
    "reference": {
      "src": withBasePath("/images/cases/olay-20261030/reference-01.jpg"),
      "width": 800,
      "height": 800
    },
    "result": {
      "src": withBasePath("/images/cases/olay-20261030/replica-01.png"),
      "width": 1254,
      "height": 1254
    }
  },
  "style": {
    "product": {
      "src": withBasePath("/images/cases/olay-20261030/product-01.webp"),
      "width": 720,
      "height": 960
    },
    "reference": {
      "src": withBasePath("/images/cases/olay-20261030/reference-01.jpg"),
      "width": 800,
      "height": 800
    },
    "result": {
      "src": withBasePath("/images/cases/olay-20261030/replica-01.png"),
      "width": 1254,
      "height": 1254
    }
  }
} as const;
