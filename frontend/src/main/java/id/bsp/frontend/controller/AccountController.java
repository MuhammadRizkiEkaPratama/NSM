package id.bsp.frontend.controller;

import id.bsp.frontend.entity.EmailChangeToken;
import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.EmailChangeTokenRepository;
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

import java.security.Principal;
import java.time.LocalDateTime;
import java.util.Optional;
import java.util.UUID;

/**
 * Change-password UI for the logged-in user (admins included). The new password must pass PasswordPolicy.
 *
 * <p>The first admin password is random and stored only as a hash, so changing it here is the only way to own it.
 *
 * Self-service email change with verification:
 *   /account/email         (GET)  form: new email + password
 *   /account/email         (POST) send a verification link to the NEW email and a notice to the old one
 *   /account/email/verify  (GET)  clicking the link actually changes the email
 */
@Controller
public class AccountController {

    private static final int EMAIL_TOKEN_MINUTES = 30;

    private final UserRepository repo;
    private final PasswordEncoder encoder;
    private final AuditService audit;
    private final EmailChangeTokenRepository emailTokens;
    private final EmailService emailService;

    public AccountController(UserRepository repo, PasswordEncoder encoder, AuditService audit,
                            EmailChangeTokenRepository emailTokens, EmailService emailService) {
        this.repo = repo;
        this.encoder = encoder;
        this.audit = audit;
        this.emailTokens = emailTokens;
        this.emailService = emailService;
    }

    @GetMapping("/account/password")
    public String form() {
        return "account_password";
    }

    @PostMapping("/account/password")
    public String changePassword(@RequestParam String current,
                                 @RequestParam String password,
                                 @RequestParam String confirm,
                                 Principal principal,
                                 HttpServletRequest request,
                                 Model model) {

        User u = repo.findByUsername(principal.getName()).orElse(null);
        if (u == null) {
            model.addAttribute("error", "User tidak ditemukan.");
            return "account_password";
        }

        if (!encoder.matches(current, u.getPassword())) {
            model.addAttribute("error", "Password lama salah.");
            return "account_password";
        }
        if (!password.equals(confirm)) {
            model.addAttribute("error", "Password baru dan konfirmasi tidak sama.");
            return "account_password";
        }
        String policyError = PasswordPolicy.validate(password, u.getUsername());
        if (policyError != null) {
            model.addAttribute("error", policyError);
            return "account_password";
        }
        if (encoder.matches(password, u.getPassword())) {
            model.addAttribute("error", "Password baru tidak boleh sama dengan yang lama.");
            return "account_password";
        }

        u.setPassword(encoder.encode(password));
        repo.save(u);
        audit.logRequest(AuditService.PASSWORD_CHANGE, u.getUsername(),
                "ganti password sendiri via /account/password", true, request);
        model.addAttribute("success", "Password berhasil diganti.");
        return "account_password";
    }


    @GetMapping("/account/email")
    public String emailForm(Principal principal, Model model) {
        User u = repo.findByUsername(principal.getName()).orElse(null);
        model.addAttribute("emailSekarang", u != null ? u.getEmail() : "-");
        return "account_email";
    }

    @PostMapping("/account/email")
    public String requestEmailChange(@RequestParam String current,
                                     @RequestParam("email") String newEmail,
                                     Principal principal,
                                     HttpServletRequest request,
                                     Model model) {
        User u = repo.findByUsername(principal.getName()).orElse(null);
        if (u == null) {
            model.addAttribute("error", "User tidak ditemukan.");
            return "account_email";
        }
        model.addAttribute("emailSekarang", u.getEmail());

        if (!encoder.matches(current, u.getPassword())) {
            model.addAttribute("error", "Password salah.");
            return "account_email";
        }
        newEmail = newEmail == null ? "" : newEmail.trim();
        // 2) bentuk email minimal masuk akal
        if (newEmail.isBlank() || !newEmail.contains("@") || newEmail.contains(" ")) {
            model.addAttribute("error", "Alamat email tidak valid.");
            return "account_email";
        }
        if (newEmail.equalsIgnoreCase(u.getEmail())) {
            model.addAttribute("error", "Email baru sama dengan email sekarang.");
            return "account_email";
        }
        Optional<User> pemakai = repo.findByEmail(newEmail);
        if (pemakai.isPresent() && !pemakai.get().getUsername().equals(u.getUsername())) {
            model.addAttribute("error", "Email itu sudah dipakai akun lain.");
            return "account_email";
        }

        emailTokens.deleteByUsername(u.getUsername());
        String token = UUID.randomUUID().toString();
        emailTokens.save(new EmailChangeToken(token, u.getUsername(), newEmail,
                LocalDateTime.now().plusMinutes(EMAIL_TOKEN_MINUTES)));

        try {
            emailService.sendEmailChangeVerify(newEmail, u.getUsername(), token);
            if (u.getEmail() != null && !u.getEmail().isBlank()) {
                emailService.sendEmailChangeNotice(u.getEmail(), u.getUsername(), newEmail);
            }
        } catch (Exception e) {
            System.out.println(">>> NSM: gagal kirim email verifikasi ganti email: " + e.getMessage());
        }
        audit.logRequest(AuditService.EMAIL_CHANGE, newEmail,
                "minta ganti email - link verifikasi dikirim ke alamat baru", true, request);
        model.addAttribute("success",
                "Link verifikasi dikirim ke " + newEmail + ". Email baru berlaku "
                + "setelah kamu klik link itu. Email lama masih aktif sampai saat itu.");
        return "account_email";
    }

    @GetMapping("/account/email/verify")
    public String verifyEmailChange(@RequestParam String token,
                                    HttpServletRequest request,
                                    Model model) {
        Optional<EmailChangeToken> maybe = emailTokens.findByToken(token);
        if (maybe.isEmpty() || maybe.get().isExpired()) {
            model.addAttribute("error", "Link verifikasi tidak valid atau sudah kadaluarsa.");
            return "account_email";
        }
        EmailChangeToken t = maybe.get();
        User u = repo.findByUsername(t.getUsername()).orElse(null);
        if (u == null) {
            model.addAttribute("error", "User tidak ditemukan.");
            return "account_email";
        }
        // Re-check: the new email may have been taken by another account since the request.
        Optional<User> pemakai = repo.findByEmail(t.getNewEmail());
        if (pemakai.isPresent() && !pemakai.get().getUsername().equals(u.getUsername())) {
            emailTokens.deleteByUsername(u.getUsername());
            model.addAttribute("error", "Email itu sudah dipakai akun lain.");
            return "account_email";
        }

        u.setEmail(t.getNewEmail());
        repo.save(u);
        emailTokens.deleteByUsername(u.getUsername()); // one-time token

        audit.logRequest(AuditService.EMAIL_CHANGE, t.getNewEmail(),
                "email berhasil diganti via verifikasi", true, request);
        model.addAttribute("emailSekarang", u.getEmail());
        model.addAttribute("success", "Email berhasil diganti menjadi " + t.getNewEmail() + ".");
        return "account_email";
    }
}
