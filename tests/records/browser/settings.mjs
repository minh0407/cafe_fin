// Shared only by this test harness; never imported by application code.
const configuredPort = process.env.CAFE_FIN_RECORDS_TEST_PORT ?? "1421";
if (!/^[0-9]+$/.test(configuredPort) || !Number.isSafeInteger(Number(configuredPort)) || Number(configuredPort) < 1 || Number(configuredPort) > 65535) {
  throw new Error("CAFE_FIN_RECORDS_TEST_PORT must be an integer between 1 and 65535.");
}
export const port = Number(configuredPort);
export const origin = `http://127.0.0.1:${port}`;
