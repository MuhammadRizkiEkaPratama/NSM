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
 * Services page: answers "is the service serving?", not just "is the machine up?".
 * Ping can succeed while Apache is down, so service state is tracked separately. Open to
 * Admin and Viewer (read-only, no credentials). Java computes nothing; health, failing layer,
 * and suggested action come from Python (connectors/layanan.py, report_service.py).
 */
@Controller
public class ServicesController {

    private final NetmonApiClient api;
    private final AuditService audit;

    public ServicesController(NetmonApiClient api, AuditService audit) {
        this.api = api;
        this.audit = audit;
    }

    @GetMapping("/services")
    public String halaman(@RequestParam(defaultValue = "24h") String period,
                          Model model, HttpServletRequest request) {
        model.addAttribute("period", bersihkanPeriode(period));
        audit.logRequest(AuditService.VIEW_SERVICES, null,
                "buka halaman Layanan (periode " + bersihkanPeriode(period) + ")",
                true, request);
        return "services";
    }

    /** Page data. Not audited (the page auto-refreshes); opening the page is audited. */
    @GetMapping("/api/services")
    @ResponseBody
    public Object daftar(@RequestParam(defaultValue = "24h") String period) {
        return api.getServices(bersihkanPeriode(period));
    }

    /** Current service state per device, for the dashboard cards. Not audited (polled every five seconds). */
    @GetMapping("/api/services/ringkas")
    @ResponseBody
    public Object ringkas() {
        return api.getServicesRingkas();
    }

    @GetMapping("/api/services/{id}/history")
    @ResponseBody
    public Object riwayat(@PathVariable int id,
                          @RequestParam(defaultValue = "24h") String period) {
        return api.getServiceHistory(id, bersihkanPeriode(period));
    }

    @GetMapping("/api/devices/{id}/services")
    @ResponseBody
    public Object perDevice(@PathVariable int id,
                            @RequestParam(defaultValue = "24h") String period) {
        return api.getDeviceServices(id, bersihkanPeriode(period));
    }

    /** Allowed periods. Input validation: raw URL values are not forwarded to the backend. */
    private String bersihkanPeriode(String p) {
        if (p == null) return "24h";
        return switch (p) {
            case "1h", "24h", "7d", "30d" -> p;
            default -> "24h";
        };
    }
}
