package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;

/**
 * BACKUP monitoring page.
 * Backup evidence used to be scattered (manifest.log, Task Scheduler result, the second-copy folder) and nobody looked; this shows it on screen. The route is under /admin so it is ROLE_ADMIN-only: it exposes file paths and machine state. Java judges nothing; healthy/problem is computed by Python in backup_status.py.
 */
@Controller
public class BackupController {

    private final NetmonApiClient api;
    private final AuditService audit;

    public BackupController(NetmonApiClient api, AuditService audit) {
        this.api = api;
        this.audit = audit;
    }

    @GetMapping("/admin/backup")
    public String halaman(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_BACKUP, null,
                "buka halaman Backup", true, request);
        return "backup";
    }

    /** Page data. Not audited: the page refreshes itself and logging each refresh would flood the Audit Log. Opening the page is audited above. */
    @GetMapping("/api/backup/status")
    @ResponseBody
    public Object status() {
        return api.getBackupStatus();
    }

    /** Details of one backup file, shown when its row is clicked. */
    @GetMapping("/api/backup/isi")
    @ResponseBody
    public Object isi(@RequestParam String nama) {
        return api.getBackupIsi(nama);
    }
}
