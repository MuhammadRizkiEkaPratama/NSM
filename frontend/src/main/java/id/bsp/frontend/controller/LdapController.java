package id.bsp.frontend.controller;

import id.bsp.frontend.dto.DeviceDto;
import id.bsp.frontend.entity.AuditLog;
import id.bsp.frontend.repository.AuditLogRepository;
import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * LDAP management page. Three read-only parts:
 *   1. People in the directory (name, title, group), from `orang_ldap`.
 *   2. Recent NSM logins, linked to those identities.
 *   3. Status of the LDAP server itself (`.101`), from already-monitored device data.
 * Modifying data (add/delete users, change passwords) is deliberately absent: it would require NSM to hold WRITE credentials to the LDAP that also backs NSM and E-Canteen logins, a different risk class that needs its own design first.
 * No E-Canteen data: `audit_logs` records only logins to NSM, so this page must not pretend to know who logged in there.
 */
@Controller
public class LdapController {

    private final NetmonApiClient api;
    private final AuditLogRepository auditRepo;

    public LdapController(NetmonApiClient api, AuditLogRepository auditRepo) {
        this.api = api;
        this.auditRepo = auditRepo;
    }

    // Under /admin like Audit Log and Backup: staff emails, titles and login history are ADMIN-only via the /admin/** matcher in SecurityConfig.
    @GetMapping("/admin/ldap")
    public String ldap(Model model) {
        // --- 1. Direktori (Python, salinan orang_ldap) ---
        Object direktori;
        try {
            direktori = api.getLdapDirektori();
        } catch (Exception e) {
            direktori = null;
            System.out.println(">>> NSM: direktori LDAP tidak terbaca: " + e.getMessage());
        }
        model.addAttribute("direktori", direktori);

        // Recent NSM logins, summarized to once per person. findTop100 returns raw rows (one per login); the page needs the LAST login per person. LinkedHashMap keeps the newest-first order of the incoming rows.
        List<AuditLog> loginMentah =
                auditRepo.findTop100ByActionOrderByTimestampDesc(AuditService.LOGIN_SUCCESS);
        Map<String, AuditLog> loginTerakhir = new LinkedHashMap<>();
        for (AuditLog a : loginMentah) {
            loginTerakhir.putIfAbsent(a.getActor(), a);
        }
        model.addAttribute("loginTerakhir", new ArrayList<>(loginTerakhir.values()));

        // LDAP server status (.101) from data the poller already collects; no new check. Looked up by IP, not name, because device names can change (see docs/LAB-SETUP.md).
        DeviceDto serverLdap = null;
        try {
            List<DeviceDto> devices = api.getDevices();
            for (DeviceDto d : devices) {
                if ("192.168.20.101".equals(d.ipAddress)) {
                    serverLdap = d;
                    break;
                }
            }
        } catch (Exception e) {
            System.out.println(">>> NSM: status server LDAP tidak terbaca: " + e.getMessage());
        }
        model.addAttribute("serverLdap", serverLdap);

        return "ldap";
    }
}
