package id.bsp.frontend.ws;

import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.io.IOException;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArraySet;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Receiving end of the topology map: one browser equals one open WebSocket session. Computes
 * nothing; it keeps the list of open sessions and forwards the JSON given by
 * {@link TopologiBroadcaster}. A new session is sent the last snapshot immediately, so the map
 * is not blank until the next broadcast.
 */
@Component
public class TopologiWebSocketHandler extends TextWebSocketHandler {

    private final Set<WebSocketSession> sesi = new CopyOnWriteArraySet<>();

    private final AtomicReference<String> potretTerakhir = new AtomicReference<>();

    @Override
    public void afterConnectionEstablished(WebSocketSession session) throws Exception {
        sesi.add(session);
        String terakhir = potretTerakhir.get();
        if (terakhir != null) {
            // Send now. A failure here (for example the session closing) does not affect other sessions;
            // the broken one is dropped by afterConnectionClosed or the next broadcast.
            try {
                session.sendMessage(new TextMessage(terakhir));
            } catch (IOException e) {
                sesi.remove(session);
            }
        }
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        sesi.remove(session);
    }

    @Override
    public void handleTransportError(WebSocketSession session, Throwable exception) {
        // A transport error means this session is no longer usable; drop it so the next broadcast does not fail because of it.
        sesi.remove(session);
    }

    /**
     * Sends the same JSON to ALL open sessions. Called only by {@link TopologiBroadcaster}. Sessions
     * that fail to receive are dropped here too, so dead sessions do not accumulate.
     */
    void siarkanKeSemua(String jsonTopologi) {
        potretTerakhir.set(jsonTopologi);
        TextMessage pesan = new TextMessage(jsonTopologi);
        for (WebSocketSession s : sesi) {
            if (!s.isOpen()) {
                sesi.remove(s);
                continue;
            }
            try {
                s.sendMessage(pesan);
            } catch (IOException e) {
                sesi.remove(s);
            }
        }
    }

    public int jumlahSesiTerbuka() {
        return sesi.size();
    }
}
