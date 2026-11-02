package id.bsp.frontend.security;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * NSM security rules: every page requires login except /login, /signup and static assets;
 * /admin/** is ADMIN only; custom login form, logout, 1-hour remember-me, bcrypt passwords;
 * explicit CSRF; security headers (anti-clickjacking, CSP, nosniff, referrer policy, HSTS).
 */
@Configuration
public class SecurityConfig {

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    private final id.bsp.frontend.repository.BlockedIpRepository blockedIps;
    private final id.bsp.frontend.repository.UserRepository users;
    private final id.bsp.frontend.service.AuditService audit;

    public SecurityConfig(id.bsp.frontend.repository.BlockedIpRepository blockedIps,
                          id.bsp.frontend.repository.UserRepository users,
                          id.bsp.frontend.service.AuditService audit) {
        this.blockedIps = blockedIps;
        this.users = users;
        this.audit = audit;
    }

    @Bean
    public SecurityFilterChain filterChain(
            HttpSecurity http,
            org.springframework.security.authentication.AuthenticationManager manager,
            @org.springframework.beans.factory.annotation.Value("${nsm.remember-me-key:${NSM_REMEMBER_ME_KEY:}}") String rememberMeKey)
            throws Exception {
        // Remember-me signing key comes from application.properties or the
        // NSM_REMEMBER_ME_KEY environment variable. If neither is set, a random
        // key is generated at startup, so remember-me cookies expire on restart.
        String kunciIngatSaya = rememberMeKey.isBlank()
                ? java.util.UUID.randomUUID().toString()
                : rememberMeKey;
        http
            // Must be set explicitly. Defining an `AuthenticationManager` bean is not enough: otherwise
            // Spring Security builds its default manager from the `UserDetailsService` and the LDAP path is
            // never called (LDAP logins rejected, MySQL logins accepted).
            .authenticationManager(manager)
            .addFilterBefore(new IpBlockFilter(blockedIps, audit), UsernamePasswordAuthenticationFilter.class)
            .authorizeHttpRequests(auth -> auth
                // /css/** and /js/** hold shared styles and scripts also used before login (sign-up, reset password).
                .requestMatchers("/login", "/signup", "/captcha", "/forgot", "/reset",
                                 "/app.js", "/css/**", "/js/**", "/error").permitAll()
                // /vendor/** holds the font and third-party libraries (ECharts, GSAP, Three.js, Vanta) used by the
                // login page, which is viewed without a session. Without this, Spring answers with the login page
                // and the browser silently fails to parse it as CSS or JavaScript.
                .requestMatchers("/vendor/**", "/ikon-tabler.svg").permitAll()
                // Favicon, requested on every page including login. Without a permit the request gets the login page and the tab has no icon.
                .requestMatchers("/favicon.svg", "/favicon.ico").permitAll()
                // Email-change verification is clicked from the new inbox, possibly without a session. The
                // one-time URL token (30 minutes) is the key, same as /reset.
                .requestMatchers("/account/email/verify").permitAll()
                // Python poller -> Java path for device alerts. The poller has no login session; the
                // controller only accepts calls from this host (127.0.0.1).
                .requestMatchers("/internal/**").permitAll()
                .requestMatchers("/admin/**").hasRole("ADMIN")
                // Device configuration data: admin only, same as the page. Without this line `/api/konfig`
                // would be open to any account even though `/admin/konfig` is guarded, and hiding the link is not
                // security. The content is masked but still reveals network layout, addresses and running services.
                .requestMatchers("/api/konfig/**", "/api/konfig").hasRole("ADMIN")
                // Source of truth: admin only, same reasoning as /api/konfig; intent determines what may be sent to real devices.
                .requestMatchers("/api/sot/**", "/api/sot").hasRole("ADMIN")
                // Drift detection: read-only, but as sensitive as /api/konfig, so admin only.
                .requestMatchers("/api/drift/**", "/api/drift").hasRole("ADMIN")
                // Automation guardrails: read-only, admin only, same reason as drift detection.
                .requestMatchers("/api/pagar/**", "/api/pagar").hasRole("ADMIN")
                // Tenants: admin only. The page is already under /admin/**; this line guards the API path, which that pattern does not cover.
                .requestMatchers("/api/tenant/**", "/api/tenant").hasRole("ADMIN")
                // Device discovery: admin only. It scans the network (sends packets to every address in a
                // subnet) and adds devices that NSM then monitors indefinitely. The page is already under
                // /admin/**; this line guards the API path, and hiding the link is not security.
                .requestMatchers("/api/penemuan/**", "/api/penemuan").hasRole("ADMIN")
                // The only WRITE path in the app: pausing/resuming device monitoring. Viewers may only look, not change what is monitored.
                .requestMatchers(org.springframework.http.HttpMethod.POST,
                                 "/api/devices/*/aktif").hasRole("ADMIN")
                .requestMatchers(org.springframework.http.HttpMethod.POST,
                                 "/api/devices/*/penting").hasRole("ADMIN")
                // Auto-ban: blocking/unblocking an IP on a firewall/ACL WRITES to a device, so admin only, same as /api/konfig.
                .requestMatchers(org.springframework.http.HttpMethod.POST,
                                 "/api/firewall/blokir",
                                 "/api/firewall/blokir-acl",
                                 "/api/firewall/buka-blokir").hasRole("ADMIN")
                .anyRequest().authenticated()
            )
            .formLogin(form -> form
                .loginPage("/login")
                .defaultSuccessUrl("/", true)
                .failureHandler((request, response, exception) -> {
                    String url = "/login?error";
                    if (exception instanceof org.springframework.security.authentication.LockedException) {
                        StringBuilder u = new StringBuilder("/login?locked");
                        String uname = request.getParameter("username");
                        if (uname != null) {
                            var maybe = users.findByUsername(uname);
                            if (maybe.isPresent() && maybe.get().getLockedUntil() != null) {
                                long secs = java.time.Duration.between(
                                        java.time.LocalDateTime.now(),
                                        maybe.get().getLockedUntil()).getSeconds();
                                if (secs > 0 && secs <= 3600) {
                                    u.append("&secs=").append(secs);
                                }
                                if (maybe.get().getLockLevel() == 2) {
                                    u.append("&emailed");
                                }
                                if (maybe.get().getLockLevel() >= 3) {
                                    u.append("&hard");
                                }
                            }
                        }
                        url = u.toString();
                    } else if (exception instanceof org.springframework.security.authentication.DisabledException) {
                        // Two causes give the same DisabledException: never approved, and access revoked by an admin.
                        // Calling both "not approved" would tell a removed user to wait for an approval that will not come.
                        String uname = request.getParameter("username");
                        boolean dicabut = uname != null
                                && users.findByUsername(uname)
                                        .map(id.bsp.frontend.entity.User::isNonaktif)
                                        .orElse(false);
                        url = dicabut ? "/login?dicabut" : "/login?pending";
                    } else if (exception instanceof LdapTakTerjangkauException) {
                        // Identity server down, not wrong password: show the real reason instead of "Username atau
                        // password salah", which sends users to fix something that is not broken.
                        url = "/login?ldapmati";
                    }
                    response.sendRedirect(request.getContextPath() + url);
                })
                .permitAll()
            )
            .logout(logout -> logout
                .logoutSuccessHandler((request, response, authentication) -> {
                    String actor = authentication != null ? authentication.getName() : "anonymous";
                    audit.log(actor, id.bsp.frontend.service.AuditService.LOGOUT, null, "logout",
                            id.bsp.frontend.service.AuditService.clientIp(request),
                            id.bsp.frontend.service.AuditService.userAgent(request), true);
                    response.sendRedirect(request.getContextPath() + "/login?logout");
                })
                .permitAll()
            )
            .rememberMe(rm -> rm
                .key(kunciIngatSaya)
                .tokenValiditySeconds(3600)
            )
            .sessionManagement(sm -> sm
                .sessionFixation(sf -> sf.newSession())
            )
            // CSRF stays enabled for all pages (Thymeleaf adds the token to every POST form). Only
            // /internal/** is exempt, because its caller is a program (the Python poller) with no session or
            // token; CSRF protects browser sessions.
            .csrf(csrf -> csrf.ignoringRequestMatchers("/internal/**"))
            // A stale CSRF token must not produce a blank 403 page (for example a login page opened before
            // a restart). Redirect to /login with a message saying what happened.
            .exceptionHandling(ex -> ex
                .accessDeniedHandler((req, res, e) ->
                    res.sendRedirect(req.getContextPath() + "/login?kedaluwarsa")))
            // Fase 2b — security headers eksplisit
            .headers(headers -> headers
                // Anti-clickjacking: the page must not be embedded in an <iframe> on another site
                .frameOptions(fo -> fo.sameOrigin())
                // Content Security Policy. script-src has no 'unsafe-inline': all JavaScript is in separate
                // files under /js/ and server values are passed as data-* attributes on <body>, so CSP is a real
                // XSS defense. style-src still allows 'unsafe-inline' (known debt): some style values are
                // computed at runtime, and injected styles can break layout but cannot steal a session.
                .contentSecurityPolicy(csp -> csp.policyDirectives(
                    "default-src 'self'; " +
                    "script-src 'self'; " +
                    "style-src 'self' 'unsafe-inline'; " +
                    "img-src 'self' data:; " +
                    "object-src 'none'; " +
                    "base-uri 'self'; " +
                    "form-action 'self'; " +
                    "frame-ancestors 'self'"
                ))
                .contentTypeOptions(cto -> { })
                .referrerPolicy(rp -> rp.policy(
                    org.springframework.security.web.header.writers.ReferrerPolicyHeaderWriter
                        .ReferrerPolicy.SAME_ORIGIN))
                // HSTS: forces HTTPS. Only effective over HTTPS; browsers ignore it on plain http://localhost.
                .httpStrictTransportSecurity(hsts -> hsts
                    .includeSubDomains(true)
                    .maxAgeInSeconds(31536000))
            );

        return http.build();
    }
}
