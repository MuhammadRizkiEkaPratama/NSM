package id.bsp.frontend.controller;

import id.bsp.frontend.service.AuditService;
import id.bsp.frontend.service.NetmonApiClient;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.client.RestClientResponseException;
import tools.jackson.databind.ObjectMapper;

import java.security.Principal;
import java.util.Map;

/**
 * Source of truth page: what SHOULD be deployed (intent), as opposed to the current snapshot or
 * compliance results. Never touches a device; it only reads and writes NSM's own database
 * (`intent_*` tables) through Python (`sot/service.py`). Admin only, same pattern as
 * `KonfigController`. Java validates nothing; shape, limits, and rejections are decided by
 * Python (`sot/katalog.py`).
 */
@Controller
public class SotController {

    private final NetmonApiClient api;
    private final AuditService audit;
    private final ObjectMapper mapper;

    public SotController(NetmonApiClient api, AuditService audit, ObjectMapper mapper) {
        this.api = api;
        this.audit = audit;
        this.mapper = mapper;
    }

    /**
     * Extracts Python's actual rejection reason (`{"ditolak": "..."}`). Same as
     * `KonfigController.ambilDitolak`, copied rather than shared.
     */
    private String ambilDitolak(RestClientResponseException e) {
        try {
            Map<?, ?> badan = mapper.readValue(e.getResponseBodyAsString(), Map.class);
            Object d = badan.get("ditolak");
            return d != null ? String.valueOf(d) : e.getMessage();
        } catch (Exception parseErr) {
            return e.getMessage();
        }
    }

    private static String potong(String s, int n) {
        if (s == null) return null;
        return s.length() > n ? s.substring(0, n) + "..." : s;
    }

    // -------------------------------------------------------------------
    // HALAMAN
    // -------------------------------------------------------------------

    @GetMapping("/admin/konfig/sot")
    public String beranda(Model model, HttpServletRequest request) {
        audit.logRequest(AuditService.VIEW_SOT, null,
                "buka daftar Sumber Kebenaran", true, request);
        return "konfig_sot";
    }

    @GetMapping("/admin/konfig/sot/{deviceId}")
    public String detail(@PathVariable int deviceId, Model model,
                         HttpServletRequest request) {
        model.addAttribute("deviceId", deviceId);
        audit.logRequest(AuditService.VIEW_SOT, String.valueOf(deviceId),
                "buka intent device", true, request);
        return "konfig_sot_device";
    }

    // API: GET. Read-only but can still return 409 (unsupported platform or incomplete intent); a Python rejection is not a server error.

    @GetMapping("/api/sot/katalog")
    @ResponseBody
    public Object katalog(@RequestParam(required = false) String platform) {
        return api.getSotKatalog(platform);
    }

    @GetMapping("/api/sot")
    @ResponseBody
    public Object ringkasan() {
        return api.getSotRingkasan();
    }

    @GetMapping("/api/sot/{deviceId}")
    @ResponseBody
    public Object ambil(@PathVariable int deviceId) {
        try {
            return api.getSotDevice(deviceId);
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ambilDitolak(e)));
        }
    }

    @GetMapping("/api/sot/{deviceId}/render")
    @ResponseBody
    public Object render(@PathVariable int deviceId) {
        try {
            return api.getSotRender(deviceId);
        } catch (RestClientResponseException e) {
            // Not audited as a failure: an "incomplete" render is the normal state of an unfinished form.
            // Intent changes (`simpanNilai` and friends) are what get audited.
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ambilDitolak(e)));
        }
    }

    @GetMapping("/api/sot/{deviceId}/riwayat")
    @ResponseBody
    public Object riwayat(@PathVariable int deviceId) {
        try {
            return api.getSotRiwayat(deviceId);
        } catch (RestClientResponseException e) {
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ambilDitolak(e)));
        }
    }

    // API: POST, writes intent. Audited with who and what changed. "oleh" is taken from the
    // session, never from the request body, so the audit trail cannot be forged.

    @PostMapping("/api/sot/{deviceId}/nilai")
    @ResponseBody
    public Object simpanNilai(@PathVariable int deviceId,
                              @RequestBody Map<String, Object> isi,
                              Principal siapa, HttpServletRequest request) {
        isi.put("oleh", siapa != null ? siapa.getName() : "?");
        try {
            Object hasil = api.postSotNilai(deviceId, isi);
            audit.logRequest(AuditService.SOT_UBAH, String.valueOf(deviceId),
                    "ubah nilai intent (" + ((Map<?, ?>) isi.getOrDefault(
                            "nilai", Map.of())).size() + " kunci dikirim)",
                    true, request);
            return hasil;
        } catch (RestClientResponseException e) {
            String ditolak = ambilDitolak(e);
            audit.logRequest(AuditService.SOT_UBAH, String.valueOf(deviceId),
                    "ubah nilai intent DITOLAK: " + potong(ditolak, 400),
                    false, request);
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ditolak));
        }
    }

    @PostMapping("/api/sot/{deviceId}/interface")
    @ResponseBody
    public Object simpanInterface(@PathVariable int deviceId,
                                  @RequestBody Map<String, Object> isi,
                                  Principal siapa, HttpServletRequest request) {
        isi.put("oleh", siapa != null ? siapa.getName() : "?");
        try {
            Object hasil = api.postSotInterface(deviceId, isi);
            audit.logRequest(AuditService.SOT_UBAH, String.valueOf(deviceId),
                    "selaraskan interface intended", true, request);
            return hasil;
        } catch (RestClientResponseException e) {
            String ditolak = ambilDitolak(e);
            audit.logRequest(AuditService.SOT_UBAH, String.valueOf(deviceId),
                    "selaraskan interface intended DITOLAK: " + potong(ditolak, 400),
                    false, request);
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ditolak));
        }
    }

    @PostMapping("/api/sot/{deviceId}/vlan")
    @ResponseBody
    public Object simpanVlan(@PathVariable int deviceId,
                             @RequestBody Map<String, Object> isi,
                             Principal siapa, HttpServletRequest request) {
        isi.put("oleh", siapa != null ? siapa.getName() : "?");
        try {
            Object hasil = api.postSotVlan(deviceId, isi);
            audit.logRequest(AuditService.SOT_UBAH, String.valueOf(deviceId),
                    "selaraskan VLAN intended", true, request);
            return hasil;
        } catch (RestClientResponseException e) {
            String ditolak = ambilDitolak(e);
            audit.logRequest(AuditService.SOT_UBAH, String.valueOf(deviceId),
                    "selaraskan VLAN intended DITOLAK: " + potong(ditolak, 400),
                    false, request);
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ditolak));
        }
    }

    @PostMapping("/api/sot/{deviceId}/rute")
    @ResponseBody
    public Object simpanRute(@PathVariable int deviceId,
                             @RequestBody Map<String, Object> isi,
                             Principal siapa, HttpServletRequest request) {
        isi.put("oleh", siapa != null ? siapa.getName() : "?");
        try {
            Object hasil = api.postSotRute(deviceId, isi);
            audit.logRequest(AuditService.SOT_UBAH, String.valueOf(deviceId),
                    "selaraskan rute statis intended", true, request);
            return hasil;
        } catch (RestClientResponseException e) {
            String ditolak = ambilDitolak(e);
            audit.logRequest(AuditService.SOT_UBAH, String.valueOf(deviceId),
                    "selaraskan rute statis intended DITOLAK: " + potong(ditolak, 400),
                    false, request);
            return ResponseEntity.status(e.getStatusCode())
                    .body(Map.of("ok", false, "ditolak", ditolak));
        }
    }
}
