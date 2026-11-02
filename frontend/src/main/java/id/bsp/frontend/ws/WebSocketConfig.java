package id.bsp.frontend.ws;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

/**
 * Registers `/ws/topologi`. No separate authorization rule on purpose: the WebSocket handshake
 * is a normal HTTP GET and is covered by `SecurityConfig`'s `.anyRequest().authenticated()`, so any
 * logged-in user may view the map. No cross-origin `setAllowedOrigins`: browser and Spring are
 * always the same origin, and relaxing it would let other sites read the network map.
 */
@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    private final TopologiWebSocketHandler handler;

    public WebSocketConfig(TopologiWebSocketHandler handler) {
        this.handler = handler;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(handler, "/ws/topologi");
    }
}
