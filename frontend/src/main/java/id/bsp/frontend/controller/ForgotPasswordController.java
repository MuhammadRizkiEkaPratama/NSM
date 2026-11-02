package id.bsp.frontend.controller;

import id.bsp.frontend.entity.PasswordResetToken;
import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.PasswordResetTokenRepository;
import id.bsp.frontend.repository.UserRepository;
import id.bsp.frontend.security.PasswordPolicy;
import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.EmailService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.time.LocalDateTime;
import java.util.Optional;
import java.util.UUID;

/**
 * "Forgot password" flow by email.
 *   /forgot  -> user enters email, system sends a reset link (if registered)
 *   /reset   -> user opens the emailed link and sets a new password
 *
 * Anti user-enumeration: /forgot always shows the same success message.
 */
@Controller
public class ForgotPasswordController {

    private static final int TOKEN_VALID_MINUTES = 30;

    private final UserRepository users;
    private final PasswordResetTokenRepository tokens;
    private final EmailService emailService;
    private final PasswordEncoder encoder;
    private final AuditService audit;

    public ForgotPasswordController(UserRepository users,
                                    PasswordResetTokenRepository tokens,
                                    EmailService emailService,
                                    PasswordEncoder encoder,
                                    AuditService audit) {
        this.users = users;
        this.tokens = tokens;
        this.emailService = emailService;
        this.encoder = encoder;
        this.audit = audit;
    }

    @GetMapping("/forgot")
    public String forgotForm() {
        return "forgot";
    }

    @PostMapping("/forgot")
    public String forgot(@RequestParam String email, HttpServletRequest request, Model model) {
        Optional<User> maybe = users.findByEmail(email);
        if (maybe.isPresent()) {
            User u = maybe.get();
            tokens.deleteByUsername(u.getUsername());

            String token = UUID.randomUUID().toString();
            tokens.save(new PasswordResetToken(
                    token, u.getUsername(),
                    LocalDateTime.now().plusMinutes(TOKEN_VALID_MINUTES)));

            try {
                emailService.sendResetLink(u.getEmail(), u.getUsername(), token);
            } catch (Exception e) {
                // Do not leak details; log them on the server for debugging
                System.out.println(">>> NSM: gagal kirim email reset: " + e.getMessage());
            }
            audit.log(u.getUsername(), AuditService.FORGOT_REQUEST, u.getEmail(),
                    "permintaan reset password - link dikirim", AuditService.clientIp(request),
                    AuditService.userAgent(request), true);
        } else {
            audit.log("anonymous", AuditService.FORGOT_REQUEST, email,
                    "permintaan reset untuk email tak terdaftar", AuditService.clientIp(request),
                    AuditService.userAgent(request), false);
        }
        // Same message regardless of outcome (anti-enumeration).
        model.addAttribute("success",
                "Kalau email terdaftar, link reset sudah dikirim. Cek inbox/spam.");
        return "forgot";
    }

    @GetMapping("/reset")
    public String resetForm(@RequestParam String token, Model model) {
        Optional<PasswordResetToken> maybe = tokens.findByToken(token);
        if (maybe.isEmpty() || maybe.get().isExpired()) {
            model.addAttribute("error", "Link reset tidak valid atau sudah kadaluarsa.");
            return "reset";
        }
        model.addAttribute("token", token);
        return "reset";
    }

    @PostMapping("/reset")
    public String reset(@RequestParam String token,
                        @RequestParam String password,
                        @RequestParam String confirm,
                        HttpServletRequest request,
                        Model model) {

        Optional<PasswordResetToken> maybe = tokens.findByToken(token);
        if (maybe.isEmpty() || maybe.get().isExpired()) {
            model.addAttribute("error", "Link reset tidak valid atau sudah kadaluarsa.");
            return "reset";
        }
        PasswordResetToken prt = maybe.get();

        User u = users.findByUsername(prt.getUsername()).orElse(null);
        if (u == null) {
            model.addAttribute("error", "User tidak ditemukan.");
            return "reset";
        }
        if (!password.equals(confirm)) {
            model.addAttribute("error", "Password dan konfirmasi tidak sama.");
            model.addAttribute("token", token);
            return "reset";
        }
        String policyError = PasswordPolicy.validate(password, u.getUsername());
        if (policyError != null) {
            model.addAttribute("error", policyError);
            model.addAttribute("token", token);
            return "reset";
        }

        // Set the new password and unlock the account (reset all lockout levels).
        u.setPassword(encoder.encode(password));
        u.setFailedAttempts(0);
        u.setLockedUntil(null);
        u.setLockLevel(0);
        users.save(u);

        tokens.deleteByUsername(u.getUsername()); // single-use token

        audit.log(u.getUsername(), AuditService.PASSWORD_RESET, null,
                "reset password via link email - lockout dibuka", AuditService.clientIp(request),
                AuditService.userAgent(request), true);

        return "redirect:/login?reset";
    }
}
