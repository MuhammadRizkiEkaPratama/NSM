package id.bsp.frontend.controller;

import id.bsp.frontend.entity.User;
import id.bsp.frontend.repository.BlockedIpRepository;
import id.bsp.frontend.repository.UserRepository;
import id.bsp.frontend.service.AuditService;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

/**
 * Admin page to approve or reject sign-ups, manage active accounts, and unblock IPs. ADMIN role only (SecurityConfig).
 *
 * Three guards for account management:
 *   1. An admin cannot revoke or disable themselves.
 *   2. The last active admin cannot be revoked; a system with no admin can only be fixed through SQL.
 *   3. Disabling is preferred over deleting, so audit rows do not point to a user who no longer exists.
 */
@Controller
@RequestMapping("/admin")
public class AdminController {

    private final UserRepository repo;
    private final BlockedIpRepository blockedIps;
    private final AuditService audit;

    public AdminController(UserRepository repo, BlockedIpRepository blockedIps, AuditService audit) {
        this.repo = repo;
        this.blockedIps = blockedIps;
        this.audit = audit;
    }

    @GetMapping("/users")
    public String users(Model model, java.security.Principal siapa) {
        model.addAttribute("pending", repo.findByEnabledFalseAndNonaktifFalse());
        model.addAttribute("all", repo.findAll());
        model.addAttribute("blockedIps", blockedIps.findAll());
        // Used by the template to hide dangerous buttons on the admin's own row. A convenience, not security: the guards are in the methods below, since a hidden button can still be called.
        model.addAttribute("akuSendiri", siapa != null ? siapa.getName() : null);
        model.addAttribute("jumlahAdminAktif", repo.countByRoleAndEnabledTrue("ADMIN"));
        return "admin_users";
    }

    @PostMapping("/unblock-ip")
    public String unblockIp(@RequestParam String ip, HttpServletRequest request) {
        blockedIps.deleteByIp(ip);
        audit.logRequest(AuditService.UNBLOCK_IP, ip, "blokir IP dibuka admin", true, request);
        return "redirect:/admin/users";
    }

    @PostMapping("/users/{id}/reset-lockout")
    public String resetLockout(@PathVariable Long id, HttpServletRequest request) {
        repo.findById(id).ifPresent(u -> {
            u.setFailedAttempts(0);
            u.setLockedUntil(null);
            u.setLockLevel(0);
            repo.save(u);
            audit.logRequest(AuditService.RESET_LOCKOUT, u.getUsername(),
                    "lockout akun di-reset admin", true, request);
        });
        return "redirect:/admin/users";
    }

    @PostMapping("/users/{id}/approve")
    public String approve(@PathVariable Long id, HttpServletRequest request) {
        repo.findById(id).ifPresent(u -> {
            u.setEnabled(true);
            repo.save(u);
            audit.logRequest(AuditService.APPROVE_USER, u.getUsername(),
                    "user di-approve jadi aktif", true, request);
        });
        return "redirect:/admin/users";
    }

    @PostMapping("/users/{id}/reject")
    public String reject(@PathVariable Long id, HttpServletRequest request) {
        repo.findById(id).ifPresent(u -> {
            String uname = u.getUsername();
            repo.deleteById(id);
            audit.logRequest(AuditService.REJECT_USER, uname,
                    "pendaftaran ditolak & user dihapus", true, request);
        });
        return "redirect:/admin/users";
    }


    /** Change role between ADMIN and VIEWER. */
    @PostMapping("/users/{id}/role")
    public String ubahRole(@PathVariable Long id, @RequestParam String role,
                           HttpServletRequest request) {
        String baru = "ADMIN".equalsIgnoreCase(role) ? "ADMIN" : "VIEWER";
        var mungkin = repo.findById(id);
        if (mungkin.isEmpty()) return "redirect:/admin/users?galat=tidak-ada";
        User u = mungkin.get();

        String tolak = alasanTidakBolehDilemahkan(u, baru.equals("ADMIN"), request,
                AuditService.UBAH_ROLE, "ubah role jadi " + baru);
        if (tolak != null) return "redirect:/admin/users?galat=" + tolak;

        String lama = u.getRole();
        if (baru.equals(lama)) return "redirect:/admin/users";
        u.setRole(baru);
        repo.save(u);
        audit.logRequest(AuditService.UBAH_ROLE, u.getUsername(),
                "role diubah dari " + lama + " jadi " + baru, true, request);
        return "redirect:/admin/users?pesan=role-diubah";
    }

    /** Revoke or restore login access of an account that was active. */
    @PostMapping("/users/{id}/nonaktif")
    public String setNonaktif(@PathVariable Long id, @RequestParam boolean nonaktif,
                              HttpServletRequest request) {
        var mungkin = repo.findById(id);
        if (mungkin.isEmpty()) return "redirect:/admin/users?galat=tidak-ada";
        User u = mungkin.get();

        if (nonaktif) {
            String tolak = alasanTidakBolehDilemahkan(u, false, request,
                    AuditService.NONAKTIF_USER, "cabut akses");
            if (tolak != null) return "redirect:/admin/users?galat=" + tolak;
        }

        u.setNonaktif(nonaktif);
        u.setEnabled(!nonaktif);
        if (!nonaktif) {
            // Restored clean: old failed-login counts and lockouts must not come back with it.
            u.setFailedAttempts(0);
            u.setLockedUntil(null);
            u.setLockLevel(0);
        }
        repo.save(u);
        audit.logRequest(nonaktif ? AuditService.NONAKTIF_USER : AuditService.AKTIFKAN_USER,
                u.getUsername(),
                nonaktif ? "akses akun dicabut admin, akun tidak dihapus"
                         : "akses akun dikembalikan admin",
                true, request);
        return "redirect:/admin/users?pesan=" + (nonaktif ? "akses-dicabut" : "akses-dikembalikan");
    }

    /** Delete an account entirely. Available but not recommended. */
    @PostMapping("/users/{id}/hapus")
    public String hapus(@PathVariable Long id, HttpServletRequest request) {
        var mungkin = repo.findById(id);
        if (mungkin.isEmpty()) return "redirect:/admin/users?galat=tidak-ada";
        User u = mungkin.get();

        String tolak = alasanTidakBolehDilemahkan(u, false, request,
                AuditService.HAPUS_USER, "hapus akun");
        if (tolak != null) return "redirect:/admin/users?galat=" + tolak;

        String uname = u.getUsername();
        repo.deleteById(id);
        // The username is kept in the target column even after the row is gone, so the audit entry stays readable.
        audit.logRequest(AuditService.HAPUS_USER, uname,
                "akun dihapus permanen oleh admin", true, request);
        return "redirect:/admin/users?pesan=akun-dihapus";
    }

    /**
     * Shared guard for the three actions that can reduce someone's access.
     * Returns null if allowed, otherwise a refusal reason code. Refusals are audited as failures.
     * `jadiAdmin` says whether the action promotes the user to admin; promoting never reduces anyone's access, so it is not guarded.
     */
    private String alasanTidakBolehDilemahkan(User u, boolean jadiAdmin,
                                              HttpServletRequest request,
                                              String aksi, String maksud) {
        if (jadiAdmin) return null;

        String aku = AuditService.currentActor();
        if (u.getUsername() != null && u.getUsername().equals(aku)) {
            audit.logRequest(aksi, u.getUsername(),
                    "ditolak: admin tidak boleh " + maksud + " untuk dirinya sendiri",
                    false, request);
            return "diri-sendiri";
        }

        // Applies only if this person is currently an active admin; demoting a viewer never reduces the admin count.
        boolean adminAktif = "ADMIN".equalsIgnoreCase(u.getRole()) && u.isEnabled();
        if (adminAktif && repo.countByRoleAndEnabledTrue("ADMIN") <= 1) {
            audit.logRequest(aksi, u.getUsername(),
                    "ditolak: ini admin aktif terakhir, sistem akan kehilangan "
                    + "semua admin (" + maksud + ")",
                    false, request);
            return "admin-terakhir";
        }
        return null;
    }
}
