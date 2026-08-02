/**
 * App Config
 *
 * One fetch of /api/config per page, shared by every component.
 *
 * Six components each fetched the endpoint independently during startup, and
 * because several of them re-run their init after a live fragment swap, a
 * single page load was measured making 13 requests for the same unchanging
 * document. On a Raspberry Pi serving its own display that is pure waste:
 * every one of those is a thread in the dev server and a round trip.
 *
 * The promise is memoised rather than the value, so concurrent callers during
 * startup share one in-flight request instead of racing to start their own.
 */

let configPromise = null;

/**
 * Resolve the browser-safe configuration.
 *
 * Rejects if the request fails; callers already wrap their config load in
 * try/catch and fall back to their own defaults.
 *
 * @param {{force?: boolean}} options - force: bypass and replace the cache.
 */
export function loadAppConfig({ force = false } = {}) {
  if (force) {
    configPromise = null;
  }

  if (!configPromise) {
    configPromise = fetch("/api/config")
      .then((response) => {
        if (!response.ok) {
          throw new Error(`/api/config returned ${response.status}`);
        }
        return response.json();
      })
      .catch((err) => {
        // Do not cache a rejection: a config fetch that failed because the
        // server was still starting would otherwise poison every later
        // caller for the lifetime of the page.
        configPromise = null;
        throw err;
      });
  }

  return configPromise;
}

/** Drop the cached config. Exposed for tests and for post-upgrade reloads. */
export function clearAppConfigCache() {
  configPromise = null;
}

export default loadAppConfig;
