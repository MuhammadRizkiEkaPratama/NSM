package id.bsp.frontend.security;

import id.bsp.frontend.repository.BlockedIpRepository;
import id.bsp.frontend.service.AuditService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * Rejects login attempts (POST /login) from IPs blocked at level 3. Other requests are unaffected,
 * so a logged-in admin can still unblock from /admin/users. Deliberately not a @Component
 * (created manually in SecurityConfig) so it is not auto-registered in the main filter chain.
 */
public class IpBlockFilter extends OncePerRequestFilter {

    private final BlockedIpRepository blockedIps;
    private final AuditService audit;

    public IpBlockFilter(BlockedIpRepository blockedIps, AuditService audit) {
        this.blockedIps = blockedIps;
        this.audit = audit;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {

        if ("POST".equalsIgnoreCase(request.getMethod())
                && "/login".equals(request.getServletPath())) {
            String ip = request.getRemoteAddr();
            // Loopback (localhost) is never blocked, so a local admin is safe
            if (ip != null && !LoginAttemptListener.isLoopback(ip) && blockedIps.existsByIp(ip)) {
                String attempted = request.getParameter("username");
                audit.log(attempted, AuditService.LOGIN_BLOCKED_IP, ip,
                        "percobaan login dari IP terblokir", ip, AuditService.userAgent(request), false);
                response.sendRedirect(request.getContextPath() + "/login?ipblocked");
                return; // stop: do not process the login
            }
        }
        chain.doFilter(request, response);
    }
}
