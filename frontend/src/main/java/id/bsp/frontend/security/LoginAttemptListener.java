package id.bsp.frontend.security;

import id.bsp.frontend.entity.BlockedIp;
import id.bsp.frontend.entity.PasswordResetToken;
import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.BlockedIpRepository;
import id.bsp.frontend.repository.PasswordResetTokenRepository;
import id.bsp.frontend.repository.UserRepository;
import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.EmailService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.event.EventListener;
import org.springframework.security.authentication.event.AbstractAuthenticationFailureEvent;
import org.springframework.security.authentication.event.AuthenticationFailureBadCredentialsEvent;
import org.springframework.security.authentication.event.AuthenticationFailureDisabledEvent;
import org.springframework.security.authentication.event.AuthenticationFailureLockedEvent;
import org.springframework.security.authentication.event.AuthenticationSuccessEvent;
import org.springframework.security.core.Authentication;
import org.springframework.security.web.authentication.WebAuthenticationDetails;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.Optional;
import java.util.UUID;

/**
 * Three-level lockout plus login audit.
 *   level 0 -> 1: account frozen
 *   level 1 -> 2: frozen and a reset link emailed
 *   level 2 -> 3: IP blocked (only an admin can unblock)
 * A successful login or password reset resets all counters to 0.
 */
@Component
public class LoginAttemptListener {

    @Value("${nsm.lock-max-attempts:3}")
    private int maxAttempts;

    @Value("${nsm.lock-minutes:5}")
    private int lockMinutes;

    private final UserRepository users;
    private final PasswordResetTokenRepository tokens;
    private final BlockedIpRepository blockedIps;
    private final EmailService emailService;
    private final AuditService audit;

    public LoginAttemptListener(UserRepository users,
                                PasswordResetTokenRepository tokens,
                                BlockedIpRepository blockedIps,
                                EmailService emailService,
                                AuditService audit) {
        this.users = users;
        this.tokens = tokens;
        this.blockedIps = blockedIps;
        this.emailService = emailService;
        this.audit = audit;
    }

    @EventListener
    public void onFailure(AuthenticationFailureBadCredentialsEvent event) {
        String username = event.getAuthentication().getName();
        String ip = ipOf(event.getAuthentication());

        // Audits failed logins even for unknown usernames (detects enumeration).
        audit.logAuth(username, AuditService.LOGIN_FAILED, null, "password salah", ip, false);

        Optional<User> maybe = users.findByUsername(username);
        if (maybe.isEmpty()) {
            return;
        }
        User u = maybe.get();

        // Currently frozen -> do not increment the count
        if (u.getLockedUntil() != null && u.getLockedUntil().isAfter(LocalDateTime.now())) {
            return;
        }

        int attempts = u.getFailedAttempts() + 1;
        if (attempts < maxAttempts) {
            u.setFailedAttempts(attempts);
            users.save(u);
            return;
        }

        // Capai batas -> eskalasi
        u.setFailedAttempts(0);
        int level = u.getLockLevel();

        if (level == 0) {
            u.setLockLevel(1);
            u.setLockedUntil(LocalDateTime.now().plusMinutes(lockMinutes));
            audit.logAuth(username, AuditService.LOCKOUT_L1, null,
                    "akun freeze " + lockMinutes + " menit", ip, true);
        } else if (level == 1) {
            u.setLockLevel(2);
            u.setLockedUntil(LocalDateTime.now().plusMinutes(lockMinutes));
            kirimEmailReset(u);
            audit.logAuth(username, AuditService.LOCKOUT_L2, u.getEmail(),
                    "freeze + email link reset dikirim", ip, true);
        } else {
            u.setLockLevel(3);
            u.setLockedUntil(LocalDateTime.now().plusYears(100));
            if (ip != null && !isLoopback(ip) && !blockedIps.existsByIp(ip)) {
                blockedIps.save(new BlockedIp(ip, username, LocalDateTime.now()));
                audit.logAuth(username, AuditService.LOCKOUT_L3, ip,
                        "IP diblokir permanen (sampai admin buka)", ip, true);
                System.out.println(">>> NSM: IP diblokir (tingkat 3): " + ip + " oleh " + username);
            } else if (isLoopback(ip)) {
                audit.logAuth(username, AuditService.LOCKOUT_L3, ip,
                        "tingkat 3 dari localhost - IP TIDAK diblokir (whitelist)", ip, true);
                System.out.println(">>> NSM: tingkat 3 dari localhost (" + ip + ") - IP TIDAK diblokir (whitelist).");
            }
        }
        users.save(u);
    }

    @EventListener
    public void onSuccess(AuthenticationSuccessEvent event) {
        String username = event.getAuthentication().getName();
        String ip = ipOf(event.getAuthentication());
        audit.logAuth(username, AuditService.LOGIN_SUCCESS, null, "login berhasil", ip, true);

        users.findByUsername(username).ifPresent(u -> {
            if (u.getFailedAttempts() != 0 || u.getLockedUntil() != null || u.getLockLevel() != 0) {
                u.setFailedAttempts(0);
                u.setLockedUntil(null);
                u.setLockLevel(0);
                users.save(u);
            }
        });
    }

    @EventListener
    public void onLocked(AuthenticationFailureLockedEvent event) {
        String username = event.getAuthentication().getName();
        audit.logAuth(username, AuditService.LOGIN_BLOCKED_LOCKED, null,
                "login ditolak: akun sedang terkunci", ipOf(event.getAuthentication()), false);
    }

    @EventListener
    public void onDisabled(AuthenticationFailureDisabledEvent event) {
        String username = event.getAuthentication().getName();
        audit.logAuth(username, AuditService.LOGIN_BLOCKED_PENDING, null,
                "login ditolak: akun belum di-approve", ipOf(event.getAuthentication()), false);
    }

    private void kirimEmailReset(User u) {
        try {
            tokens.deleteByUsername(u.getUsername());
            String token = UUID.randomUUID().toString();
            tokens.save(new PasswordResetToken(
                    token, u.getUsername(), LocalDateTime.now().plusMinutes(30)));
            emailService.sendResetLink(u.getEmail(), u.getUsername(), token);
            System.out.println(">>> NSM: email reset (tingkat 2) dikirim ke " + u.getEmail());
        } catch (Exception e) {
            System.out.println(">>> NSM: gagal kirim email reset tingkat 2: " + e.getMessage());
        }
    }

    private String ipOf(Authentication auth) {
        if (auth != null && auth.getDetails() instanceof WebAuthenticationDetails wad) {
            return wad.getRemoteAddress();
        }
        return null;
    }

    static boolean isLoopback(String ip) {
        if (ip == null) return false;
        return ip.equals("127.0.0.1") || ip.equals("::1")
                || ip.equals("0:0:0:0:0:0:0:1") || ip.startsWith("127.");
    }
}
