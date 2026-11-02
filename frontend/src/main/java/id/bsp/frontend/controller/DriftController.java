package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.client.RestClientResponseException;
import tools.jackson.databind.ObjectMapper;

import java.util.Map;

/**
 * Drift detection: does what is currently installed match what the Source of Truth says should be installed?
 * Entirely read-only: no POST endpoint, so no CSRF meta in the template (unlike `SotController`). The comparison runs in Python (`drift/service.py`) and does not touch devices; it compares stored intent with configuration snapshots already in the database.
 * ADMIN only: the drift list reveals the real network layout.
 */
@Controller
public class DriftController {

    private final NetmonApiClient api;
    private final AuditService audit;
    private final ObjectMapper mapper;

    public DriftController(NetmonApiClient api, AuditService audit, ObjectMapper mapper) {
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

    @GetMapping("/admin/konfig/drift")
    public String beranda(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_DRIFT, null,
                "buka daftar Deteksi Penyimpangan", true, request);
        return "konfig_drift";
    }

    @GetMapping("/admin/konfig/drift/{deviceId}")
    public String detail(@PathVariable int deviceId, Model model,
                         HttpServletRequest request) {
        model.addAttribute("deviceId", deviceId);
        audit.logRequest(AuditService.VIEW_DRIFT, String.valueOf(deviceId),
                "buka detail penyimpangan device", true, request);
        return "konfig_drift_device";
    }

    @GetMapping("/api/drift")
    @ResponseBody
    public Object ringkasan() {
        return api.getDriftRingkasan();
    }

    @GetMapping("/api/drift/{deviceId}")
    @ResponseBody
    public Object detailApi(@PathVariable int deviceId) {
        try {
            return api.getDriftDevice(deviceId);
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ambilDitolak(e)));
        }
    }
}
