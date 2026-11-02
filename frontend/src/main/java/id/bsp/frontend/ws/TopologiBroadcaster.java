package id.bsp.frontend.ws;

import id.bsp.frontend.service.NetmonApiClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.concurrent.atomic.AtomicReference;

/**
 * Pulls `/topologi` from Python every {@link #JEDA_MS} ms and broadcasts the result to all open
 * WebSocket sessions. Java pulls rather than Python pushing, to keep the data flow one-way
 * (Browser -> Java -> Python -> Database) and never call back into Java (see CONTRIBUTING.md).
 * A broadcast is skipped when the content is unchanged, to avoid needless redraws in every
 * browser. The comparison uses `sidik` (a fingerprint Python computes without the timestamp),
 * not the raw JSON: the response contains a `diperiksa` timestamp field, so raw text always differed.
 */
@Component
public class TopologiBroadcaster {

    private static final Logger log = LoggerFactory.getLogger(TopologiBroadcaster.class);
    private static final long JEDA_MS = 2000;

    /**
     * Extracts the `"sidik":"..."` value from the RAW JSON without parsing it (parsing would defeat
     * the point of `getTopologiRaw()`). The pattern matches only that hex field.
     */
    private static final java.util.regex.Pattern POLA_SIDIK =
            java.util.regex.Pattern.compile("\"sidik\"\\s*:\\s*\"([0-9a-f]{8,64})\"");

    private final NetmonApiClient api;
    private final TopologiWebSocketHandler handler;
    private final AtomicReference<String> sidikTerakhir = new AtomicReference<>();

    public TopologiBroadcaster(NetmonApiClient api, TopologiWebSocketHandler handler) {
        this.api = api;
        this.handler = handler;
    }

    @Scheduled(fixedRate = JEDA_MS)
    void siarkan() {
        // Python being down or restarting must not kill this heartbeat: an exception escaping a
        // @Scheduled call silently cancels the whole schedule until Spring restarts.
        String json;
        try {
            json = api.getTopologiRaw();
        } catch (Exception e) {
            log.warn("gagal menarik /topologi dari Python: {}", e.toString());
            return;
        }
        if (json == null) return;

        String sidik = sidikDari(json);
        if (sidik == null) {
            // Older Python (or an unexpected response) has no sidik. Fall back to full-text comparison
            // rather than silently stop broadcasting; a frozen map is worse than extra redraws.
            sidik = json;
        }
        if (sidik.equals(sidikTerakhir.get())) return;
        sidikTerakhir.set(sidik);
        handler.siarkanKeSemua(json);
    }

    static String sidikDari(String json) {
        java.util.regex.Matcher m = POLA_SIDIK.matcher(json);
        return m.find() ? m.group(1) : null;
    }
}
