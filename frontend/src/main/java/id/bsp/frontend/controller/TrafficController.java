package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;

/**
 * Traffic page: who fetched what, and how much. Interface counters do not record the peer, so
 * this comes from the serving host's logs. Open to Admin and Viewer (read-only). Java computes
 * nothing; aggregation is done by Python in report_service.py.
 */
@Controller
public class TrafficController {

    private final NetmonApiClient api;
    private final AuditService audit;

    public TrafficController(NetmonApiClient api, AuditService audit) {
        this.api = api;
        this.audit = audit;
    }

    @GetMapping("/traffic")
    public String halaman(@RequestParam(defaultValue = "24h") String period,
                          Model model, HttpServletRequest request) {
        model.addAttribute("period", bersihkanPeriode(period));
        audit.logRequest(AuditService.VIEW_TRAFFIC, null,
                "buka halaman Lalu Lintas (periode " + bersihkanPeriode(period) + ")",
                true, request);
        return "traffic";
    }

    /** Page data. Not audited (the page auto-refreshes). */
    @GetMapping("/api/traffic")
    @ResponseBody
    public Object data(@RequestParam(defaultValue = "24h") String period) {
        return api.getTraffic(bersihkanPeriode(period));
    }

    /**
     * Traffic anomalies with comparison figures. Separate from `/api/traffic` because it is much
     * more expensive. Thresholds and baselines live only in Python.
     */
    @GetMapping("/api/traffic/anomali")
    @ResponseBody
    public Object anomali(@RequestParam(defaultValue = "7d") String period) {
        return api.getTrafficAnomali(bersihkanPeriode(period));
    }

    /** File transfers over SFTP. Separate from `/api/traffic` because the source (SFTP log) differs and one failure must not take down the other. */
    @GetMapping("/api/traffic/berkas")
    @ResponseBody
    public Object berkas(@RequestParam(defaultValue = "24h") String period) {
        return api.getTrafficBerkas(bersihkanPeriode(period));
    }

    @GetMapping("/api/devices/{id}/traffic")
    @ResponseBody
    public Object perDevice(@PathVariable int id,
                            @RequestParam(defaultValue = "24h") String period) {
        return api.getDeviceTraffic(id, bersihkanPeriode(period));
    }

    /** Allowed periods. Input validation only; the meaning of each period stays in Python. */
    private String bersihkanPeriode(String p) {
        if (p == null) return "24h";
        return switch (p) {
            case "1h", "24h", "7d", "30d" -> p;
            default -> "24h";
        };
    }
}
