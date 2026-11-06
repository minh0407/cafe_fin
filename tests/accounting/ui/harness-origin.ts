// Dedicated accounting test port. Production desktop/Vite origins stay unchanged.
export const HARNESS_PORT = 1424;
export const HARNESS_ORIGIN = `http://127.0.0.1:${HARNESS_PORT}`;
export const HARNESS_DEV_COMMAND = `npm --prefix frontend run dev -- --port ${HARNESS_PORT}`;
