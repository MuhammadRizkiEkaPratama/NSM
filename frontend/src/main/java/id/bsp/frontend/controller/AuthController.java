package id.bsp.frontend.controller;

import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.UserRepository;
import id.bsp.frontend.service.AuditService;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;
import jakarta.servlet.http.HttpSession;
import jakarta.servlet.http.HttpServletRequest;

import java.time.LocalDateTime;

/** Login and sign-up pages. Sign-up creates a pending account (enabled=false) that an admin must approve. */
@Controller
public class AuthController {

    private final UserRepository repo;
    private final PasswordEncoder encoder;
    private final AuditService audit;

    public AuthController(UserRepository repo, PasswordEncoder encoder, AuditService audit) {
        this.repo = repo;
        this.encoder = encoder;
        this.audit = audit;
    }

    @GetMapping("/login")
    public String login() {
        return "login";
    }

    @GetMapping("/signup")
    public String signupForm() {
        return "signup";
    }

    @PostMapping("/signup")
    public String signup(@RequestParam String username,
                         @RequestParam String email,
                         @RequestParam String password,
                         @RequestParam String confirm,
                         @RequestParam String captcha,
                         HttpSession session,
                         HttpServletRequest request,
                         Model model) {

        // Check the captcha first (single use, removed from the session).
        Object expected = session.getAttribute(CaptchaController.SESSION_KEY);
        session.removeAttribute(CaptchaController.SESSION_KEY);
        if (expected == null || captcha == null
                || !captcha.trim().equalsIgnoreCase(expected.toString())) {
            model.addAttribute("error", "Captcha salah, coba lagi.");
            return "signup";
        }

        // Validasi (Fase 2a: password policy terpusat)
        if (!password.equals(confirm)) {
            model.addAttribute("error", "Password dan konfirmasi tidak sama.");
            return "signup";
        }
        String policyError = id.bsp.frontend.security.PasswordPolicy.validate(password, username);
        if (policyError != null) {
            model.addAttribute("error", policyError);
            return "signup";
        }
        if (repo.existsByUsername(username)) {
            model.addAttribute("error", "Username sudah dipakai.");
            return "signup";
        }
        if (repo.existsByEmail(email)) {
            model.addAttribute("error", "Email sudah terdaftar.");
            return "signup";
        }

        User u = new User();
        u.setUsername(username);
        u.setEmail(email);
        u.setPassword(encoder.encode(password));
        u.setRole("VIEWER");
        u.setEnabled(false);                         // pending, tunggu approve admin
        u.setCreatedAt(LocalDateTime.now());
        repo.save(u);

        audit.log(username, AuditService.SIGNUP, null, "daftar akun baru - status pending",
                AuditService.clientIp(request), AuditService.userAgent(request), true);

        model.addAttribute("success", "Akun dibuat. Menunggu persetujuan admin sebelum bisa login.");
        return "signup";
    }
}
