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
 * Insights (`/wawasan`: what NSM has learned) and SOC agent (`/agen`: what NSM proposes, and what
 * the guardrails say about each proposal). Entirely read-only and open to all logged-in users:
 * turning the agent on is a deliberate decision made through `.env` on the host, not a web click.
 */
@Controller
public class WawasanController {

    private final NetmonApiClient api;
    private final AuditService audit;

    public WawasanController(NetmonApiClient api, AuditService audit) {
        this.api = api;
        this.audit = audit;
    }

    /** Time window is capped server-side (same reason as `InsidenController`). */
    private static int jamAman(int jam) {
        return Math.max(1, Math.min(jam, 720));
    }

    private Object bungkusGalat(RestClientResponseException e) {
        return ResponseEntity.status(e.getStatusCode())
                .body(Map.of("ok", false, "ditolak", e.getMessage()));
    }

    // -------------------------------------------------------------------
    // HALAMAN
    // -------------------------------------------------------------------

    @GetMapping("/wawasan")
    public String wawasan(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_WAWASAN, null,
                "buka halaman Wawasan", true, request);
        return "wawasan";
    }

    @GetMapping("/agen")
    public String agen(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_AGEN, null,
                "buka halaman Agen SOC", true, request);
        return "agen";
    }


    @GetMapping("/api/baseline")
    @ResponseBody
    public Object baseline() {
        try {
            return api.getBaseline();
        } catch (RestClientResponseException e) {
            return bungkusGalat(e);
        }
    }

    @GetMapping("/api/pola-log")
    @ResponseBody
    public Object polaLog(@RequestParam(defaultValue = "24") int jam) {
        try {
            return api.getPolaLog(jamAman(jam));
        } catch (RestClientResponseException e) {
            return bungkusGalat(e);
        }
    }

    @GetMapping("/api/prakiraan")
    @ResponseBody
    public Object prakiraan() {
        try {
            return api.getPrakiraan();
        } catch (RestClientResponseException e) {
            return bungkusGalat(e);
        }
    }

    /**
     * Separate from {@link #prakiraan()} on purpose: the error budget calls
     * `report_service.hitung_device()`, which touches many tables and is much slower than the
     * other forecast parts, so combining them would delay the whole page.
     */
    @GetMapping("/api/prakiraan/anggaran")
    @ResponseBody
    public Object prakiraanAnggaran() {
        try {
            return api.getPrakiraanAnggaran();
        } catch (RestClientResponseException e) {
            return bungkusGalat(e);
        }
    }

    @GetMapping("/api/agen-soc")
    @ResponseBody
    public Object agenSoc(@RequestParam(defaultValue = "24") int jam) {
        try {
            return api.getAgenSoc(jamAman(jam));
        } catch (RestClientResponseException e) {
            return bungkusGalat(e);
        }
    }
}
