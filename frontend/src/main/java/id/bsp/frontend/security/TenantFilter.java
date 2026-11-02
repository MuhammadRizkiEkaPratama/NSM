package id.bsp.frontend.security;

import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.UserRepository;
import id.bsp.frontend.service.KonteksTenant;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.annotation.Order;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * Sets {@link KonteksTenant} from the logged-in account. The tenant comes from the account
 * database, never from anything the client sends. Platform admins set nothing, so Python applies
 * no filter. Cleared in {@code finally} because Tomcat reuses threads.
 */
@Component
@Order(1)
public class TenantFilter extends OncePerRequestFilter {

    private final UserRepository users;

    public TenantFilter(UserRepository users) {
        this.users = users;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain chain)
            throws ServletException, IOException {
        try {
            Authentication auth = SecurityContextHolder.getContext().getAuthentication();
            if (auth != null && auth.isAuthenticated()
                    && !"anonymousUser".equals(String.valueOf(auth.getPrincipal()))) {
                User u = users.findByUsername(auth.getName()).orElse(null);
                if (u != null && !u.isAdminPlatform()) {
                    KonteksTenant.setel(u.getTenantId());
                }
            }
            chain.doFilter(request, response);
        } finally {
            KonteksTenant.bersihkan();
        }
    }
}
