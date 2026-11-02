package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.client.RestClientResponseException;

import java.util.Map;

/**
 * Syslog page: what devices report about themselves. Read-only by design: syslog over UDP is
 * unauthenticated and spoofable, so nothing here may trigger actions from message content.
 * Open to all logged-in users.
 */
@Controller
public class SyslogController {

    private final NetmonApiClient api;
    private final AuditService audit;

    public SyslogController(NetmonApiClient api, AuditService audit) {
        this.api = api;
        this.audit = audit;
    }

    /** Time window is capped server-side; otherwise "?jam=99999999" forces Python to scan the whole history. */
    private static int jamAman(int jam) {
        return Math.max(1, Math.min(jam, 720));
    }

    /** Rows per page are capped too, so "?per_halaman=100000" cannot pull the whole table. */
    private static int perHalamanAman(int n) {
        return Math.max(1, Math.min(n, 50));
    }

    private Object bungkusGalat(RestClientResponseException e) {
        return ResponseEntity.status(e.getStatusCode())
                .body(Map.of("ok", false, "ditolak", e.getMessage()));
    }

    // -------------------------------------------------------------------
    // HALAMAN
    // -------------------------------------------------------------------

    @GetMapping("/syslog")
    public String syslog(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_SYSLOG, null,
                "buka halaman Syslog", true, request);
        return "syslog";
    }


    @GetMapping("/api/syslog/dasbor")
    @ResponseBody
    public Object dasbor(@RequestParam(defaultValue = "24") int jam) {
        try {
            return api.getSyslogDasbor(jamAman(jam));
        } catch (RestClientResponseException e) {
            return bungkusGalat(e);
        }
    }

    @GetMapping("/api/syslog/pesan")
    @ResponseBody
    public Object pesan(@RequestParam(defaultValue = "24") int jam,
                        @RequestParam(required = false) Integer deviceId,
                        @RequestParam(required = false) String tag,
                        @RequestParam(defaultValue = "false") boolean penting,
                        @RequestParam(required = false) String cari,
                        @RequestParam(defaultValue = "1") int halaman,
                        @RequestParam(defaultValue = "5") int perHalaman) {
        try {
            return api.getSyslogPesan(jamAman(jam), deviceId, tag, penting, cari,
                    Math.max(1, halaman), perHalamanAman(perHalaman));
        } catch (RestClientResponseException e) {
            return bungkusGalat(e);
        }
    }
}
