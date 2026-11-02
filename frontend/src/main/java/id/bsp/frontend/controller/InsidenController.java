package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.client.RestClientResponseException;
import tools.jackson.databind.ObjectMapper;

import java.util.Map;

/**
 * INCIDENTS: one outage, not one symptom. When Router A goes down, several devices go down with it; this page groups them into one incident instead of separate alarms.
 * Not admin-only on purpose: it answers "what is happening on the network", which matters most to non-admins.
 * Entirely read-only: no POST endpoint, so no CSRF meta in the template (same as {@code DriftController}). Incidents are assembled in Python (`korelasi.py`), which only reads recorded events and triggers nothing.
 */
@Controller
public class InsidenController {

    private final NetmonApiClient api;
    private final AuditService audit;
    private final ObjectMapper mapper;

    public InsidenController(NetmonApiClient api, AuditService audit,
                             ObjectMapper mapper) {
        this.api = api;
        this.audit = audit;
        this.mapper = mapper;
    }

    private String ambilDitolak(RestClientResponseException e) {
        try {
            Map<?, ?> badan = mapper.readValue(e.getResponseBodyAsString(), Map.class);
            Object d = badan.get("ditolak");
            return d != null ? String.valueOf(d) : e.getMessage();
        } catch (Exception parseErr) {
            return e.getMessage();
        }
    }

    // -------------------------------------------------------------------
    // HALAMAN
    // -------------------------------------------------------------------

    @GetMapping("/insiden")
    public String daftar(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_INSIDEN, null,
                "buka daftar Insiden", true, request);
        return "insiden";
    }

    @GetMapping("/insiden/{id}")
    public String detail(@PathVariable int id, Model model,
                         HttpServletRequest request) {
        model.addAttribute("insidenId", id);
        audit.logRequest(AuditService.VIEW_INSIDEN, String.valueOf(id),
                "buka garis waktu satu insiden", true, request);
        return "insiden_detail";
    }


    /** The time window is capped server-side, not left to the client: `?jam=99999999` would make Python scan the whole incident history. 1..720 hours (30 days) is plenty. */
    @GetMapping("/api/insiden")
    @ResponseBody
    public Object daftarApi(@RequestParam(defaultValue = "24") int jam) {
        int aman = Math.max(1, Math.min(jam, 720));
        return api.getInsiden(aman);
    }

    @GetMapping("/api/insiden/{id}")
    @ResponseBody
    public Object detailApi(@PathVariable int id) {
        try {
            return api.getInsidenDetail(id);
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ambilDitolak(e)));
        }
    }
}
