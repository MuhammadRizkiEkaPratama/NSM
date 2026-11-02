package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ResponseBody;

/**
 * AUTOMATION GATE: the mandatory single entry point that all future recovery actions (dead GNS3 node, dead service, dead interface, drifted config) must pass through. See docs/design/CLOSED-LOOP-AUTOMATION.md.
 * Read-only, with deliberately no "try" button: `pagar_otomasi.putuskan()` in Python always writes an audit row and counts toward rate limits, so calling it for a mere look would pollute the audit trail with decisions that never became actions.
 */
@Controller
public class PagarController {

    private final NetmonApiClient api;
    private final AuditService audit;

    public PagarController(NetmonApiClient api, AuditService audit) {
        this.api = api;
        this.audit = audit;
    }

    @GetMapping("/admin/konfig/pagar")
    public String beranda(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_PAGAR, null,
                "buka halaman Pagar Otomasi", true, request);
        return "konfig_pagar";
    }

    @GetMapping("/api/pagar/status")
    @ResponseBody
    public Object status() {
        return api.getPagarStatus();
    }

    @GetMapping("/api/pagar/riwayat")
    @ResponseBody
    public Object riwayat() {
        return api.getPagarRiwayat();
    }
}
