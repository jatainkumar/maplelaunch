// Product mode, fixed at build time (NEXT_PUBLIC_APP_MODE).
// "demo" (default) adds one-click demo accounts, synthetic sample documents, the scenario lab and the demo banner.
// "production" builds the same app without any of them; the API also refuses the demo routes in that mode.
export const IS_DEMO = process.env.NEXT_PUBLIC_APP_MODE !== "production";
